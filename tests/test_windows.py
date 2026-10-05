"""Tests against the real Windows APIs. They replace whatever is on the clipboard.

The end-to-end tests also click and type like a user; they only run when CLIPHIST_E2E=1."""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import unittest

from cliphist import history
from tests.helpers import dib, text_entry

ON_WINDOWS = sys.platform == "win32"
if ON_WINDOWS:
    from ctypes import wintypes

    from cliphist import win32

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_hidden_root = None


def clipboard_hwnd():
    """A window owned by this test process to open the clipboard with."""
    global _hidden_root
    if _hidden_root is None:
        _hidden_root = tk.Tk()
        _hidden_root.withdraw()
        _hidden_root.update_idletasks()
    return _hidden_root.winfo_id()


def set_raw_clipboard(items):
    win32._open_clipboard(clipboard_hwnd())
    try:
        win32.EmptyClipboard()
        for fmt, data in items:
            handle = win32.GlobalAlloc(win32.GMEM_MOVEABLE, len(data))
            ctypes.memmove(win32.GlobalLock(handle), data, len(data))
            win32.GlobalUnlock(handle)
            win32.SetClipboardData(fmt, handle)
    finally:
        win32.CloseClipboard()


def clipboard_text():
    win32._open_clipboard(clipboard_hwnd())
    try:
        return win32._until_nul(win32._get(win32.CF_UNICODETEXT), wide=True).decode("utf-16-le")
    finally:
        win32.CloseClipboard()


def wait_for(condition, timeout=10.0, message="condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("timed out waiting for " + message)


@unittest.skipUnless(ON_WINDOWS, "Windows only")
class WindowsApiTest(unittest.TestCase):
    def test_encryption_round_trip(self):
        sealed = win32.protect(b"secret clipboard text")
        self.assertNotIn(b"secret", sealed)
        self.assertEqual(win32.unprotect(sealed), b"secret clipboard text")

    def test_formatted_text_round_trips_through_the_clipboard(self):
        entry = text_entry("héllo wörld", html="<b>héllo</b> wörld")
        win32.write_clipboard(clipboard_hwnd(), entry)
        read = win32.read_clipboard(clipboard_hwnd())
        self.assertEqual((read.kind, read.text), ("text", "héllo wörld"))
        self.assertEqual(read.digest, entry.digest)  # same content is recognised as a duplicate

    def test_files_go_back_as_files_and_as_path_text(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "a.txt")
        open(path, "w").close()
        entry = history.build_entry(paths=[folder, path], dirs=[True, False])
        win32.write_clipboard(clipboard_hwnd(), entry)
        read = win32.read_clipboard(clipboard_hwnd())
        self.assertEqual((read.kind, read.paths, read.dirs), ("files", [folder, path], [True, False]))
        self.assertEqual(clipboard_text(), folder + "\r\n" + path)
        win32.write_clipboard(clipboard_hwnd(), entry, 1)  # one item of the bundle
        self.assertEqual(win32.read_clipboard(clipboard_hwnd()).paths, [path])

    def test_image_round_trips(self):
        win32.write_clipboard(clipboard_hwnd(), history.build_entry({"dib": dib(5, 3)}))
        read = win32.read_clipboard(clipboard_hwnd())
        self.assertEqual((read.kind, read.size), ("image", (5, 3)))
        self.assertTrue(read.data("dib").startswith(dib(5, 3)))

    def test_copies_marked_private_are_not_recorded(self):
        text = (win32.CF_UNICODETEXT, "password".encode("utf-16-le") + b"\0\0")
        set_raw_clipboard([text, (win32.CF_EXCLUDE, b"\0\0\0\0")])
        self.assertIsNone(win32.read_clipboard(clipboard_hwnd()))
        set_raw_clipboard([text, (win32.CF_CAN_INCLUDE, b"\0\0\0\0")])
        self.assertIsNone(win32.read_clipboard(clipboard_hwnd()))
        set_raw_clipboard([text, (win32.CF_CAN_INCLUDE, b"\1\0\0\0")])
        self.assertEqual(win32.read_clipboard(clipboard_hwnd()).text, "password")


# ---------------------------------------------------------------- end to end

if ON_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (ENUM_PROC, wintypes.LPARAM)
    VK_SHIFT, VK_DOWN, VK_RETURN = 0x10, 0x28, 0x0D
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4


def press(*vks):
    """Press keys together and release them in reverse order."""
    events = [(vk, 0) for vk in vks] + [(vk, win32.KEYEVENTF_KEYUP) for vk in reversed(vks)]
    inputs = (win32.INPUT * len(events))()
    for item, (vk, flags) in zip(inputs, events):
        item.type = win32.INPUT_KEYBOARD
        item.ki = win32.KEYBDINPUT(vk, 0, flags, 0, 0)
    win32.SendInput(len(events), inputs, ctypes.sizeof(win32.INPUT))
    time.sleep(0.3)


def click(x, y):
    user32.SetCursorPos(x, y)
    inputs = (win32.INPUT * 2)()
    for item, flags in zip(inputs, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)):
        item.type = 0  # INPUT_MOUSE
        item.mi = win32.MOUSEINPUT(0, 0, 0, flags, 0, 0)
    win32.SendInput(2, inputs, ctypes.sizeof(win32.INPUT))
    time.sleep(0.3)


def visible_windows(pid):
    found = []

    def check(hwnd, _):
        owner = wintypes.DWORD()
        win32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(ENUM_PROC(check), 0)
    return found


def screenshot(name):
    """Save the screen as a PNG when CLIPHIST_SCREENSHOTS names a folder (used by CI)."""
    folder = os.environ.get("CLIPHIST_SCREENSHOTS")
    if not folder:
        return
    os.makedirs(folder, exist_ok=True)
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
        "[System.Drawing.Graphics]::FromImage($i).CopyFromScreen($b.Location,"
        "[System.Drawing.Point]::Empty,$b.Size);"
        "$i.Save('%s')" % os.path.join(folder, name + ".png"))
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False)


def overlay_active(pid):
    """True when a visible window of process pid has the keyboard focus."""
    window = win32.foreground_window()
    owner = wintypes.DWORD()
    win32.GetWindowThreadProcessId(window, ctypes.byref(owner))
    return owner.value == pid and bool(user32.IsWindowVisible(window))


def read_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


@unittest.skipUnless(ON_WINDOWS and os.environ.get("CLIPHIST_E2E") == "1",
                     "set CLIPHIST_E2E=1 on Windows to run")
class EndToEndTest(unittest.TestCase):
    """Runs the real app and a target window, using SendInput like a user would."""

    def start(self, settings):
        folder = tempfile.mkdtemp()
        self.data = os.path.join(folder, "ClipboardHistory")
        os.makedirs(self.data)
        with open(os.path.join(self.data, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(settings, f)
        self.env = dict(os.environ, LOCALAPPDATA=folder)
        self.history_path = os.path.join(self.data, "history.bin")
        self.launch()

    def launch(self):
        log = os.path.join(self.data, "app.log")
        starts = (read_file(log) or "").count("Started")
        self.app = subprocess.Popen([sys.executable, os.path.join(ROOT, "clipboard_history.pyw")],
                                    env=self.env)
        self.addCleanup(self.app.wait)
        self.addCleanup(self.app.kill)
        wait_for(lambda: (read_file(log) or "").count("Started") > starts, 20, "the app to start")

    def wait(self, condition, timeout, message):
        """wait_for, plus a screenshot, the app log and the target text when it times out."""
        try:
            return wait_for(condition, timeout, message)
        except AssertionError:
            screenshot("failed " + message)
            log = read_file(os.path.join(self.data, "app.log")) or ""
            text = read_file(os.path.join(self.target_dir, "text.txt"))
            raise AssertionError("timed out waiting for %s\ntarget text: %r\napp.log:\n%s"
                                 % (message, text, log[-3000:]))

    def saved_entries(self):
        try:
            with open(self.history_path, "rb") as f:
                sealed = f.read()
        except OSError:
            return []
        return [(e.kind, e.text) for e in history.loads(win32.unprotect(sealed), 20).entries]

    def open_target(self):
        self.target_dir = target_dir = tempfile.mkdtemp()
        target = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "target_app.py"),
                                   target_dir])
        self.addCleanup(target.wait)
        self.addCleanup(target.kill)
        ready = wait_for(lambda: read_file(os.path.join(target_dir, "ready.txt")), 20,
                         "the target window")
        x, y, width, height, hwnd = map(int, ready.split())
        click(x + width // 2, y + height // 2)
        wait_for(lambda: win32.toplevel_of(win32.foreground_window()) == hwnd, 5,
                 "the target window to become active")
        return target_dir

    def test_hotkey_overlay_and_paste_into_the_active_window(self):
        self.start({"excluded_apps": [], "auto_paste": True})
        path = os.path.join(tempfile.mkdtemp(), "report.txt")
        open(path, "w").close()
        gradient = [[(x, 120, 255 - x) for x in range(160)] for _ in range(90)]
        copies = [history.build_entry(paths=[path], dirs=[False]),
                  history.build_entry({"dib": dib(160, 90, 32, gradient)}),
                  text_entry("Meeting notes", html="<h1>Meeting notes</h1><p>Agreed on "
                             "<b>three</b> items</p><ul><li><i>ship it</i></li></ul>"),
                  text_entry("alpha"), text_entry("beta")]
        for entry in copies:  # another program copying, as far as the app can tell
            win32.write_clipboard(clipboard_hwnd(), entry)
            time.sleep(0.5)

        expected = [("text", "beta"), ("text", "alpha"), ("text", "Meeting notes"),
                    ("image", "Image 160 \u00d7 90"), ("files", path)]
        wait_for(lambda: self.saved_entries() == expected, 20,
                 "all copies in the encrypted history file")

        target_dir = self.open_target()
        press(win32.VK_CONTROL, VK_SHIFT, win32.VK_V)
        self.wait(lambda: overlay_active(self.app.pid), 5, "the overlay")
        press(VK_DOWN)
        screenshot("overlay")
        press(VK_RETURN)
        pasted = os.path.join(target_dir, "text.txt")
        self.wait(lambda: read_file(pasted) == "alpha", 5, "the pasted text")
        self.assertEqual(visible_windows(self.app.pid), [])

        # The pasted entry moved to the top; after a restart it is still there.
        self.wait(lambda: self.saved_entries()[:1] == [("text", "alpha")], 20, "the new order")
        self.app.kill()
        self.app.wait()
        self.launch()
        press(win32.VK_CONTROL, VK_SHIFT, win32.VK_V)
        self.wait(lambda: overlay_active(self.app.pid), 5, "the overlay after a restart")
        press(VK_RETURN)
        self.wait(lambda: read_file(pasted) == "alphaalpha", 5, "the second paste")

    def test_excluded_app_receives_the_hotkey_itself(self):
        self.start({"excluded_apps": [os.path.basename(sys.executable)]})
        target_dir = self.open_target()
        press(win32.VK_CONTROL, VK_SHIFT, win32.VK_V)

        def got_keystroke():
            keys = read_file(os.path.join(target_dir, "keys.txt")) or ""
            return any(line.split()[0] in ("V", "v") and int(line.split()[1]) & 0x5 == 0x5
                       for line in keys.splitlines())

        wait_for(got_keystroke, 5, "the target app to receive Ctrl+Shift+V")
        self.assertEqual(visible_windows(self.app.pid), [])


if __name__ == "__main__":
    unittest.main()
