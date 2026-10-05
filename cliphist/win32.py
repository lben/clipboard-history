"""Windows API access through ctypes, and the background thread that listens to Windows.

Safety boundary: only documented, non-invasive APIs are used. Clipboard changes arrive through a
clipboard format listener, the shortcut through RegisterHotKey, app switches through a foreground
window notification, and the tray icon through Shell_NotifyIcon. There are no keyboard hooks,
no key-state polling, no registry access and no network access in this program.
"""
import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes

from . import formats, history

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)

LRESULT = wintypes.LPARAM
ULONG_PTR = ctypes.c_size_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                             wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                  wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _bind(dll, name, restype, *argtypes):
    function = getattr(dll, name)
    function.restype = restype
    function.argtypes = argtypes
    return function


H, U, D, B = wintypes.HANDLE, wintypes.UINT, wintypes.DWORD, wintypes.BOOL
HWND, LPCWSTR = wintypes.HWND, wintypes.LPCWSTR
RegisterClassW = _bind(user32, "RegisterClassW", wintypes.ATOM, ctypes.POINTER(WNDCLASSW))
CreateWindowExW = _bind(user32, "CreateWindowExW", HWND, D, LPCWSTR, LPCWSTR, D, ctypes.c_int,
                        ctypes.c_int, ctypes.c_int, ctypes.c_int, HWND, wintypes.HMENU,
                        wintypes.HINSTANCE, wintypes.LPVOID)
DefWindowProcW = _bind(user32, "DefWindowProcW", LRESULT, HWND, U, wintypes.WPARAM,
                       wintypes.LPARAM)
DestroyWindow = _bind(user32, "DestroyWindow", B, HWND)
PostQuitMessage = _bind(user32, "PostQuitMessage", None, ctypes.c_int)
GetMessageW = _bind(user32, "GetMessageW", B, ctypes.POINTER(wintypes.MSG), HWND, U, U)
TranslateMessage = _bind(user32, "TranslateMessage", B, ctypes.POINTER(wintypes.MSG))
DispatchMessageW = _bind(user32, "DispatchMessageW", LRESULT, ctypes.POINTER(wintypes.MSG))
PostMessageW = _bind(user32, "PostMessageW", B, HWND, U, wintypes.WPARAM, wintypes.LPARAM)
RegisterWindowMessageW = _bind(user32, "RegisterWindowMessageW", U, LPCWSTR)
AddClipboardFormatListener = _bind(user32, "AddClipboardFormatListener", B, HWND)
RemoveClipboardFormatListener = _bind(user32, "RemoveClipboardFormatListener", B, HWND)
RegisterHotKey = _bind(user32, "RegisterHotKey", B, HWND, ctypes.c_int, U, U)
UnregisterHotKey = _bind(user32, "UnregisterHotKey", B, HWND, ctypes.c_int)
SetWinEventHook = _bind(user32, "SetWinEventHook", H, D, D, wintypes.HMODULE, WINEVENTPROC, D,
                        D, D)
UnhookWinEvent = _bind(user32, "UnhookWinEvent", B, H)
GetForegroundWindow = _bind(user32, "GetForegroundWindow", HWND)
SetForegroundWindow = _bind(user32, "SetForegroundWindow", B, HWND)
GetWindowThreadProcessId = _bind(user32, "GetWindowThreadProcessId", D, HWND, wintypes.LPDWORD)
AttachThreadInput = _bind(user32, "AttachThreadInput", B, D, D, B)
GetWindowRect = _bind(user32, "GetWindowRect", B, HWND, ctypes.POINTER(wintypes.RECT))
IsIconic = _bind(user32, "IsIconic", B, HWND)
MonitorFromWindow = _bind(user32, "MonitorFromWindow", H, HWND, D)
GetMonitorInfoW = _bind(user32, "GetMonitorInfoW", B, H, ctypes.POINTER(MONITORINFO))
GetAncestor = _bind(user32, "GetAncestor", HWND, HWND, U)
SendInput = _bind(user32, "SendInput", U, U, ctypes.POINTER(INPUT), ctypes.c_int)
OpenClipboard = _bind(user32, "OpenClipboard", B, HWND)
CloseClipboard = _bind(user32, "CloseClipboard", B)
EmptyClipboard = _bind(user32, "EmptyClipboard", B)
GetClipboardData = _bind(user32, "GetClipboardData", H, U)
SetClipboardData = _bind(user32, "SetClipboardData", H, U, H)
IsClipboardFormatAvailable = _bind(user32, "IsClipboardFormatAvailable", B, U)
RegisterClipboardFormatW = _bind(user32, "RegisterClipboardFormatW", U, LPCWSTR)
GetClipboardOwner = _bind(user32, "GetClipboardOwner", HWND)
CreatePopupMenu = _bind(user32, "CreatePopupMenu", wintypes.HMENU)
AppendMenuW = _bind(user32, "AppendMenuW", B, wintypes.HMENU, U, ctypes.c_size_t, LPCWSTR)
TrackPopupMenu = _bind(user32, "TrackPopupMenu", B, wintypes.HMENU, U, ctypes.c_int, ctypes.c_int,
                       ctypes.c_int, HWND, wintypes.LPVOID)
DestroyMenu = _bind(user32, "DestroyMenu", B, wintypes.HMENU)
GetCursorPos = _bind(user32, "GetCursorPos", B, ctypes.POINTER(wintypes.POINT))
LoadIconW = _bind(user32, "LoadIconW", wintypes.HICON, wintypes.HINSTANCE, wintypes.LPVOID)
MessageBoxW = _bind(user32, "MessageBoxW", ctypes.c_int, HWND, LPCWSTR, LPCWSTR, U)
GetModuleHandleW = _bind(kernel32, "GetModuleHandleW", wintypes.HMODULE, LPCWSTR)
GlobalAlloc = _bind(kernel32, "GlobalAlloc", H, U, ctypes.c_size_t)
GlobalLock = _bind(kernel32, "GlobalLock", wintypes.LPVOID, H)
GlobalUnlock = _bind(kernel32, "GlobalUnlock", B, H)
GlobalSize = _bind(kernel32, "GlobalSize", ctypes.c_size_t, H)
GlobalFree = _bind(kernel32, "GlobalFree", H, H)
LocalFree = _bind(kernel32, "LocalFree", H, H)
OpenProcess = _bind(kernel32, "OpenProcess", H, D, B, D)
QueryFullProcessImageNameW = _bind(kernel32, "QueryFullProcessImageNameW", B, H, D,
                                   wintypes.LPWSTR, wintypes.LPDWORD)
CloseHandle = _bind(kernel32, "CloseHandle", B, H)
CreateMutexW = _bind(kernel32, "CreateMutexW", H, wintypes.LPVOID, B, LPCWSTR)
GetCurrentThreadId = _bind(kernel32, "GetCurrentThreadId", D)
Shell_NotifyIconW = _bind(shell32, "Shell_NotifyIconW", B, D, ctypes.POINTER(NOTIFYICONDATAW))
CryptProtectData = _bind(crypt32, "CryptProtectData", B, ctypes.POINTER(DATA_BLOB), LPCWSTR,
                         ctypes.POINTER(DATA_BLOB), wintypes.LPVOID, wintypes.LPVOID, D,
                         ctypes.POINTER(DATA_BLOB))
CryptUnprotectData = _bind(crypt32, "CryptUnprotectData", B, ctypes.POINTER(DATA_BLOB),
                           wintypes.LPVOID, ctypes.POINTER(DATA_BLOB), wintypes.LPVOID,
                           wintypes.LPVOID, D, ctypes.POINTER(DATA_BLOB))

WM_NULL, WM_DESTROY, WM_CLOSE = 0x0000, 0x0002, 0x0010
WM_HOTKEY, WM_CLIPBOARDUPDATE = 0x0312, 0x031D
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
WM_APP = 0x8000
WM_TRAY, WM_RELOAD = WM_APP + 1, WM_APP + 2
CF_DIB, CF_UNICODETEXT, CF_HDROP = 8, 13, 15
CF_HTML = RegisterClipboardFormatW("HTML Format")
CF_RTF = RegisterClipboardFormatW("Rich Text Format")
CF_PNG = RegisterClipboardFormatW("PNG")
# Formats that password managers and other apps use to say "do not record this copy".
CF_EXCLUDE = RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
CF_VIEWER_IGNORE = RegisterClipboardFormatW("Clipboard Viewer Ignore")
CF_CAN_INCLUDE = RegisterClipboardFormatW("CanIncludeInClipboardHistory")
GMEM_MOVEABLE = 0x0002
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS = 0x0000, 0x0002
MOD_NOREPEAT = 0x4000
HOTKEY_ID = 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO = 0x1
MF_STRING, MF_CHECKED, MF_SEPARATOR = 0x0, 0x8, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
IDI_APPLICATION = 32512
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MONITOR_DEFAULTTONEAREST = 2
GA_ROOT = 2
INPUT_KEYBOARD, KEYEVENTF_KEYUP = 1, 0x2
VK_CONTROL, VK_V = 0x11, 0x56
CRYPTPROTECT_UI_FORBIDDEN = 0x1
ERROR_ALREADY_EXISTS = 183
MAX_FORMAT_BYTES = 64 * 1024 * 1024
APP_NAME = "Clipboard History"

# ---------------------------------------------------------------- process setup

_mutex = None


def set_dpi_awareness():
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        user32.SetProcessDPIAware()


def acquire_single_instance():
    """Return False when another copy of the app is already running in this session."""
    global _mutex
    ctypes.set_last_error(0)
    _mutex = CreateMutexW(None, False, "Local\\ClipboardHistory.SingleInstance")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def message_box(text):
    MessageBoxW(None, text, APP_NAME, 0x40)


# ---------------------------------------------------------------- encryption (DPAPI)

_ENTROPY = b"ClipboardHistory/v1"


def _blob(data):
    buffer = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _take(blob):
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def protect(data):
    """Encrypt so that only the current Windows user on this machine can decrypt."""
    plain, _keep = _blob(data)
    entropy, _keep_entropy = _blob(_ENTROPY)
    out = DATA_BLOB()
    if not CryptProtectData(ctypes.byref(plain), APP_NAME, ctypes.byref(entropy), None, None,
                            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    return _take(out)


def unprotect(data):
    sealed, _keep = _blob(data)
    entropy, _keep_entropy = _blob(_ENTROPY)
    out = DATA_BLOB()
    if not CryptUnprotectData(ctypes.byref(sealed), None, ctypes.byref(entropy), None, None,
                              CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    return _take(out)


# ---------------------------------------------------------------- clipboard


def _open_clipboard(hwnd):
    for _ in range(20):
        if OpenClipboard(hwnd):
            return
        time.sleep(0.025)
    raise OSError("the clipboard is in use by another program")


def _get(fmt):
    handle = GetClipboardData(fmt)
    if not handle:
        return None
    size = GlobalSize(handle)
    if size > MAX_FORMAT_BYTES:
        logging.info("Skipped a clipboard format larger than %d bytes", MAX_FORMAT_BYTES)
        return None
    pointer = GlobalLock(handle)
    if not pointer:
        return None
    try:
        return ctypes.string_at(pointer, size)
    finally:
        GlobalUnlock(handle)


def _until_nul(data, wide=False):
    if data is None:
        return None
    if wide:
        text = data[: len(data) // 2 * 2].decode("utf-16-le", errors="replace")
        return text.split("\0", 1)[0].encode("utf-16-le")
    return data.split(b"\0", 1)[0]


def read_clipboard(hwnd):
    """Return a history Entry for the current clipboard content, or None when there is nothing
    usable or the content asks not to be recorded."""
    paths, raw = None, {}
    _open_clipboard(hwnd)
    try:  # check the "do not record" flags while the clipboard is locked, so they match the data
        if IsClipboardFormatAvailable(CF_EXCLUDE) or IsClipboardFormatAvailable(CF_VIEWER_IGNORE):
            return None
        allowed = _get(CF_CAN_INCLUDE)
        if allowed is not None and allowed[:4] == b"\0\0\0\0":
            return None
        if IsClipboardFormatAvailable(CF_HDROP):
            drop = _get(CF_HDROP)
            paths = formats.parse_dropfiles(drop) if drop else []
        else:
            raw["text"] = _until_nul(_get(CF_UNICODETEXT), wide=True)
            if raw["text"] and raw["text"].decode("utf-16-le", errors="replace").strip():
                raw["html"] = _until_nul(_get(CF_HTML))
                raw["rtf"] = _until_nul(_get(CF_RTF))
            else:  # only read images when there is no text (Excel renders cells as pictures)
                raw["dib"] = _get(CF_DIB)
                raw["png"] = _get(CF_PNG)
    finally:
        CloseClipboard()
    if paths is not None:
        # Outside the clipboard lock: checking network paths can be slow.
        return history.build_entry(paths=paths, dirs=[os.path.isdir(p) for p in paths])
    return history.build_entry(raw)


def write_clipboard(hwnd, entry, item=None):
    """Put an entry back on the clipboard; for a bundle, item selects one of its paths."""
    if entry.kind == "files":
        paths = entry.paths if item is None else [entry.paths[item]]
        # The file list for Explorer and the paths as text for editors.
        items = [(CF_HDROP, formats.build_dropfiles(paths)),
                 (CF_UNICODETEXT, ("\r\n".join(paths) + "\0").encode("utf-16-le"))]
    else:
        ids = {"rtf": CF_RTF, "html": CF_HTML, "text": CF_UNICODETEXT, "png": CF_PNG,
               "dib": CF_DIB}
        terminators = {"rtf": b"\0", "html": b"\0", "text": b"\0\0"}
        items = [(ids[name], entry.data(name) + terminators.get(name, b""))
                 for name in ids if name in entry.formats]  # richest format first
    _open_clipboard(hwnd)
    try:
        if not EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        for fmt, data in items:
            handle = GlobalAlloc(GMEM_MOVEABLE, len(data))
            pointer = GlobalLock(handle) if handle else None
            if not pointer:
                if handle:
                    GlobalFree(handle)
                raise OSError("out of memory while copying to the clipboard")
            ctypes.memmove(pointer, data, len(data))
            GlobalUnlock(handle)
            if not SetClipboardData(fmt, handle):
                GlobalFree(handle)
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        CloseClipboard()


# ---------------------------------------------------------------- windows and input


def process_name(hwnd):
    """Lower-case executable name of the process that owns hwnd, or '' if unknown."""
    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if not QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(buffer.value).lower()
    finally:
        CloseHandle(handle)


def foreground_window():
    return GetForegroundWindow()


def toplevel_of(hwnd):
    return GetAncestor(hwnd, GA_ROOT)


def activate(hwnd):
    """Bring hwnd to the foreground. Returns True on success."""
    if SetForegroundWindow(hwnd):
        return True
    other = GetWindowThreadProcessId(GetForegroundWindow(), None)
    me = GetCurrentThreadId()
    if not other or other == me:
        return False
    AttachThreadInput(me, other, True)
    try:
        return bool(SetForegroundWindow(hwnd))
    finally:
        AttachThreadInput(me, other, False)


def window_rect(hwnd):
    rect = wintypes.RECT()
    if not hwnd or IsIconic(hwnd) or not GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def work_area(hwnd):
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor or not GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    area = info.rcWork
    return area.left, area.top, area.right, area.bottom


def send_ctrl_v():
    """Type Ctrl+V into the foreground window."""
    keys = [(VK_CONTROL, 0), (VK_V, 0), (VK_V, KEYEVENTF_KEYUP), (VK_CONTROL, KEYEVENTF_KEYUP)]
    inputs = (INPUT * len(keys))()
    for item, (vk, flags) in zip(inputs, keys):
        item.type = INPUT_KEYBOARD
        item.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    return SendInput(len(keys), inputs, ctypes.sizeof(INPUT)) == len(keys)


# ---------------------------------------------------------------- listener thread


class Listener(threading.Thread):
    """Owns a hidden window on its own thread. Reports ('clip', Entry), ('hotkey', hwnd of the
    active window) and ('menu', action) tuples on the events queue."""

    def __init__(self, events, settings, own_clipboard_hwnd):
        super().__init__(name="windows-listener", daemon=True)
        self.events = events
        self.settings = settings
        self.own_clipboard_hwnd = own_clipboard_hwnd  # our clipboard writes are not recorded
        self.hwnd = None
        self.ready = threading.Event()
        self.paused = False
        self._hotkey_on = False
        self._hotkey_warned = False
        self._hook = None
        self._icon = LoadIconW(None, IDI_APPLICATION)
        self._taskbar_created = RegisterWindowMessageW("TaskbarCreated")
        # Windows keeps calling these; holding references keeps them alive.
        self._wndproc = WNDPROC(self._window_proc)
        self._winevent = WINEVENTPROC(self._on_foreground)

    # Called from other threads.

    def apply_settings(self, settings):
        self.settings = settings
        self._hotkey_warned = False
        PostMessageW(self.hwnd, WM_RELOAD, 0, 0)

    def notify(self, title, text):
        self._tray(NIM_MODIFY, title, text)

    def stop(self):
        PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        self.join(timeout=5)

    # Listener thread.

    def run(self):
        try:
            instance = GetModuleHandleW(None)
            window_class = WNDCLASSW()
            window_class.lpfnWndProc = self._wndproc
            window_class.hInstance = instance
            window_class.lpszClassName = "ClipboardHistory.%d" % id(self)
            if not RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            hwnd = CreateWindowExW(0, window_class.lpszClassName, APP_NAME, 0, 0, 0, 0, 0, None,
                                   None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            if not AddClipboardFormatListener(hwnd):
                raise ctypes.WinError(ctypes.get_last_error())
            self.hwnd = hwnd
            self._hook = SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None,
                                         self._winevent, 0, 0,
                                         WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
            self._tray(NIM_ADD)
            self._update_hotkey(GetForegroundWindow())
        except Exception:
            logging.exception("Could not start the Windows listener")
            self.hwnd = None
            return
        finally:
            self.ready.set()
        msg = wintypes.MSG()
        while GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            TranslateMessage(ctypes.byref(msg))
            DispatchMessageW(ctypes.byref(msg))

    def _window_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_CLIPBOARDUPDATE:
                self._on_clipboard()
                return 0
            if msg == WM_HOTKEY:
                self._on_hotkey()
                return 0
            if msg == WM_TRAY:
                if lparam in (WM_LBUTTONUP, WM_RBUTTONUP):
                    self._show_menu()
                return 0
            if msg == WM_RELOAD:
                self._unregister_hotkey()
                self._update_hotkey(GetForegroundWindow())
                return 0
            if msg == self._taskbar_created:  # Explorer restarted; show the icon again
                self._tray(NIM_ADD)
                return 0
            if msg == WM_CLOSE:
                DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self._unregister_hotkey()
                if self._hook:
                    UnhookWinEvent(self._hook)
                RemoveClipboardFormatListener(hwnd)
                self._tray(NIM_DELETE)
                PostQuitMessage(0)
                return 0
        except Exception:
            logging.exception("Error while handling window message 0x%x", msg)
        return DefWindowProcW(hwnd, msg, wparam, lparam)

    def _on_clipboard(self):
        if self.paused or GetClipboardOwner() == self.own_clipboard_hwnd:
            return
        try:
            entry = read_clipboard(self.hwnd)
        except OSError as error:
            logging.warning("Could not read the clipboard: %s", error)
            return
        if entry is not None:
            self.events.put(("clip", entry))

    def _on_hotkey(self):
        window = GetForegroundWindow()
        if process_name(window) in self.settings.excluded_apps:
            self._unregister_hotkey()  # missed app switch; the next press reaches the app
            return
        self.events.put(("hotkey", window))

    def _on_foreground(self, hook, event, hwnd, id_object, id_child, thread, event_time):
        try:
            self._update_hotkey(hwnd)
        except Exception:
            logging.exception("Error while handling an app switch")

    def _update_hotkey(self, window):
        """Hold the hotkey only while the active app is not excluded, so excluded apps receive
        the keystroke themselves."""
        wanted = process_name(window) not in self.settings.excluded_apps
        if wanted and not self._hotkey_on:
            settings = self.settings
            if RegisterHotKey(self.hwnd, HOTKEY_ID, settings.hotkey_modifiers | MOD_NOREPEAT,
                              settings.hotkey_vk):
                self._hotkey_on = True
            elif not self._hotkey_warned:
                self._hotkey_warned = True
                self.notify("Hotkey unavailable", "%s is already used by another program. Pick "
                            "another hotkey in the settings." % settings.hotkey)
        elif not wanted and self._hotkey_on:
            self._unregister_hotkey()

    def _unregister_hotkey(self):
        if self._hotkey_on:
            UnregisterHotKey(self.hwnd, HOTKEY_ID)
            self._hotkey_on = False

    def _tray(self, message, info_title=None, info_text=None):
        if not self.hwnd:
            return
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self._icon
        data.szTip = APP_NAME + (" (paused)" if self.paused else "")
        if info_text:
            data.uFlags |= NIF_INFO
            data.szInfoTitle = info_title[:63]
            data.szInfo = info_text[:255]
            data.dwInfoFlags = NIIF_INFO
        Shell_NotifyIconW(message, ctypes.byref(data))

    def _show_menu(self):
        actions = {2: "clear", 3: "settings", 4: "reload", 5: "quit"}
        menu = CreatePopupMenu()
        try:
            AppendMenuW(menu, MF_STRING | (MF_CHECKED if self.paused else 0), 1, "Pause recording")
            AppendMenuW(menu, MF_STRING, 2, "Clear history (keeps pinned)")
            AppendMenuW(menu, MF_SEPARATOR, 0, None)
            AppendMenuW(menu, MF_STRING, 3, "Open settings file")
            AppendMenuW(menu, MF_STRING, 4, "Reload settings")
            AppendMenuW(menu, MF_SEPARATOR, 0, None)
            AppendMenuW(menu, MF_STRING, 5, "Quit")
            point = wintypes.POINT()
            GetCursorPos(ctypes.byref(point))
            SetForegroundWindow(self.hwnd)  # required so the menu closes when clicking elsewhere
            command = TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                                     point.x, point.y, 0, self.hwnd, None)
            PostMessageW(self.hwnd, WM_NULL, 0, 0)
        finally:
            DestroyMenu(menu)
        if command == 1:
            self.paused = not self.paused
            self._tray(NIM_MODIFY)
        elif command in actions:
            self.events.put(("menu", actions[command]))
