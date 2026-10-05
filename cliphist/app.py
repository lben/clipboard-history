"""Application wiring: settings, history, the Windows listener and the overlay."""
import logging
import os
import queue
import subprocess
import threading
import tkinter as tk

from . import history as history_store
from . import settings as settings_file
from . import win32
from .overlay import Overlay

POLL_MS = 40
SAVE_DELAY_MS = 1000
SAVE_RETRY_MS = 5000
PASTE_DELAY_MS = 80


class App:
    def __init__(self, root, data_dir):
        self.root = root
        self.settings_path = os.path.join(data_dir, "settings.json")
        self.history_path = os.path.join(data_dir, "history.bin")
        self.settings, problems = settings_file.load(self.settings_path)
        self.history = self._load_history(problems)
        self.events = queue.Queue()
        self.target = None  # the window that was active when the overlay opened
        self._save_pending = None
        self._save_warned = False
        self._quitting = False
        root.update_idletasks()
        self.clipboard_hwnd = root.winfo_id()
        self.overlay = Overlay(root, self.history, on_choose=self.choose, on_cancel=self.cancel,
                               on_change=self.schedule_save, on_shown=self._activate_overlay)
        self.listener = win32.Listener(self.events, self.settings, self.clipboard_hwnd)
        self.listener.start()
        self.listener.ready.wait(10)
        if not self.listener.hwnd:
            raise RuntimeError("the Windows listener did not start")
        if problems:
            self.listener.notify(win32.APP_NAME, "\n".join(problems))
        logging.info("Started")
        root.after(POLL_MS, self._poll)

    def _load_history(self, problems):
        try:
            return history_store.load(self.history_path, win32.unprotect,
                                      self.settings.history_size)
        except Exception:
            logging.exception("The saved history could not be read")
            try:
                os.replace(self.history_path, self.history_path + ".unreadable")
            except OSError:
                pass
            problems.append("The saved history could not be read; starting with an empty one.")
            return history_store.History(self.settings.history_size)

    def _poll(self):
        try:
            while not self._quitting:
                kind, value = self.events.get_nowait()
                try:
                    self._handle(kind, value)
                except Exception:
                    logging.exception("Error while handling %s", kind)
        except queue.Empty:
            pass
        if not self._quitting:
            self.root.after(POLL_MS, self._poll)

    def _handle(self, kind, value):
        if kind == "clip":
            self.history.add(value)
            self.schedule_save()
            self.overlay.refresh()
        elif kind == "hotkey":
            if not self.overlay.visible:
                self.target = value
                self.overlay.show(win32.window_rect(value), win32.work_area(value))
        elif value == "clear":  # the rest are tray menu actions
            self.history.clear_unpinned()
            self.schedule_save()
            self.overlay.refresh()
        elif value == "settings":
            subprocess.Popen(["notepad.exe", self.settings_path])
        elif value == "reload":
            self.reload_settings()
        elif value == "quit":
            self.quit()

    def _activate_overlay(self, toplevel):
        if not win32.activate(win32.toplevel_of(toplevel.winfo_id())):
            logging.warning("Windows did not let the overlay take the keyboard focus")

    def choose(self, entry, item, shift_held):
        try:
            win32.write_clipboard(self.clipboard_hwnd, entry, item)
        except OSError:
            logging.exception("Could not write to the clipboard")
            self.overlay.hide()
            self.listener.notify(win32.APP_NAME, "Could not access the clipboard. Please try again.")
            return
        self.history.use(entry)
        self.schedule_save()
        target = self.target
        # Hand focus back while the overlay still has it; Windows only lets the active app do that.
        activated = bool(target) and win32.activate(target)
        self.overlay.hide()
        # Shift still held would turn the pasted Ctrl+V into Ctrl+Shift+V.
        if activated and self.settings.auto_paste and not shift_held:
            self.root.after(PASTE_DELAY_MS, lambda: self._paste(target))

    def _paste(self, target):
        # Only ever type into the window the overlay was opened from.
        if win32.foreground_window() == target:
            win32.send_ctrl_v()

    def cancel(self, restore):
        if restore and self.target:
            win32.activate(self.target)

    def schedule_save(self):
        if self._save_pending is None:
            self._save_pending = self.root.after(SAVE_DELAY_MS, self.save)

    def save(self):
        self._save_pending = None
        try:
            history_store.save(self.history, self.history_path, win32.protect)
        except Exception:
            logging.exception("Could not save the history")
            # Another program (an antivirus scan, for example) can hold the file briefly.
            self._save_pending = self.root.after(SAVE_RETRY_MS, self.save)
            if not self._save_warned:
                self._save_warned = True
                self.listener.notify(win32.APP_NAME, "Could not save the history to disk.")

    def reload_settings(self):
        self.settings, problems = settings_file.load(self.settings_path)
        self.history.set_limit(self.settings.history_size)
        self.schedule_save()
        self.overlay.refresh()
        self.listener.apply_settings(self.settings)
        self.listener.notify(win32.APP_NAME, "\n".join(problems) or "Settings reloaded.")

    def quit(self):
        if self._save_pending is not None:
            self.root.after_cancel(self._save_pending)
        self.save()
        if self._save_pending is not None:  # the final save failed; nothing more can be done
            self.root.after_cancel(self._save_pending)
        self.listener.stop()
        self._quitting = True
        self.root.destroy()


def _setup_logging(data_dir):
    """Errors go to a small log file. Clipboard content is never logged."""
    path = os.path.join(data_dir, "app.log")
    try:
        if os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".1")
    except OSError:
        pass
    logging.basicConfig(filename=path, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    threading.excepthook = lambda args: logging.error(
        "Unhandled error", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    return path


def main():
    win32.set_dpi_awareness()
    data_dir = os.path.join(os.environ["LOCALAPPDATA"], "ClipboardHistory")
    os.makedirs(data_dir, exist_ok=True)
    log_path = _setup_logging(data_dir)
    if not win32.acquire_single_instance():
        win32.message_box("Clipboard History is already running. Its icon is in the notification "
                          "area of the taskbar.")
        return
    previous = win32.foreground_window()
    root = tk.Tk()
    root.withdraw()
    root.report_callback_exception = lambda *exc_info: logging.error("UI error", exc_info=exc_info)
    try:
        app = App(root, data_dir)  # noqa: F841 - kept alive by its Tk callbacks as well
    except Exception:
        logging.exception("Startup failed")
        win32.message_box("Clipboard History could not start. Details are in %s" % log_path)
        root.destroy()
        return
    # Tk activates its hidden main window when it creates it, which would leave the user typing
    # into nothing. Give the focus back to the window that had it.
    root.update()
    if previous and win32.foreground_is_ours():
        win32.activate(previous)
    root.mainloop()
