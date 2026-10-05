# Clipboard History for Windows

A small clipboard manager for Windows 10 and 11. Everything you copy goes into a history: text
(with its formatting), images, and files or folders. Press **Ctrl+Shift+V** and a picker opens
over the active window. Choose an entry with the arrow keys, press **Enter**, and it is pasted.

It is a plain Python script that uses only the standard library. There is no installer, it needs
no admin rights, it has no compiled executable, and it downloads nothing besides this repository.

## What it does and does not do

- It sees clipboard changes through the Windows clipboard listener API, the same mechanism the
  built-in Windows clipboard history uses.
- It gets its shortcut through `RegisterHotKey`, the standard API for global shortcuts. **There
  is no keyboard hook**, so it never sees any other keystroke.
- It skips copies that password managers mark as private.
- The history is encrypted with Windows DPAPI for your account and kept in
  `%LOCALAPPDATA%\ClipboardHistory`. Only your Windows account on this PC can read it, and
  there is no password prompt.
- It has no network access, makes no registry changes, and runs no background service. Its tray
  icon is always visible, and you can quit at any time.
- With auto-paste on, it types a single Ctrl+V into the window you opened the picker from, and
  only if that window is active again.

## Requirements

You need Windows 10 or 11 and Python 3.9 or newer from python.org, installed with tcl/tk (the
default). To check:

```powershell
py -3.12 -c "import tkinter; print('tkinter OK')"
```

## Install and run

```powershell
git clone https://github.com/lben/clipboard-history.git
cd clipboard-history
pyw -3.12 clipboard_history.pyw
```

`pyw` runs it without a console window. A tray icon appears in the notification area; right-click
it for Pause, Clear history, Settings and Quit.

## Start automatically when you sign in (optional, no admin needed)

1. Find your `pythonw.exe`:
   `py -3.12 -c "import sys; print(sys.executable.replace('python.exe', 'pythonw.exe'))"`
2. Press Win+R, type `shell:startup` and press Enter.
3. Right-click inside that folder, choose **New > Shortcut**, and enter
   `"<path from step 1>" "<path to clipboard-history>\clipboard_history.pyw"`.

You never need to type a password: Windows unlocks the encrypted history when you sign in.

## Keys in the picker

| Key | Action |
| --- | --- |
| Up / Down | Move |
| Enter | Paste the entry (Shift+Enter: only copy it, without pasting) |
| Typing | Filter the list; Backspace edits the filter |
| Del | Remove the entry |
| Ctrl+P | Pin or unpin. Pinned entries stay on top and are never pushed out |
| Right / Left | Open or close a bundle of several copied files |
| Esc | Close |

A copied file or folder shows its name on one line and its full path below it. Pasting it gives
you the file in Explorer and the path in a text editor.

## Settings

Tray > **Open settings file** opens `settings.json`. After saving it, choose tray >
**Reload settings**.

| Setting | Default | Meaning |
| --- | --- | --- |
| `hotkey` | `"ctrl+shift+v"` | Modifiers (`ctrl`, `alt`, `shift`, `win`) plus a letter, digit or `f1`..`f24` |
| `history_size` | `20` | How many unpinned entries to keep (1-500) |
| `auto_paste` | `true` | Paste after Enter. When `false`, Enter only copies and you press Ctrl+V yourself |
| `excluded_apps` | JetBrains IDEs | Programs that keep their own meaning of the hotkey, such as `pycharm64.exe`. Empty the list to use the picker everywhere |

## Your data

`%LOCALAPPDATA%\ClipboardHistory` holds these files:

- `history.bin`: the history, encrypted
- `settings.json`
- `app.log`: errors only, never clipboard content

Tray > **Clear history** keeps pinned entries. To remove everything, quit the app and delete the
folder.

## Limitations

- Formatting is kept as HTML and RTF. Some app-specific formats are not kept: Excel cells, for
  example, paste back as a formatted table rather than as live cells.
- Windows does not let it work over programs that run as administrator.
- The preview shows formatting for HTML. Copies that only carry RTF are previewed as plain text.

## Tests

```powershell
py -3.12 -m unittest -v
```

The Windows tests replace your clipboard content. The end-to-end tests click and type like a user
and only run with `CLIPHIST_E2E=1`; GitHub Actions runs them on every push.

## License

MIT
