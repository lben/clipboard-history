"""Settings file: defaults, loading and validation."""
import json
import os
import re

DEFAULTS = {
    "hotkey": "ctrl+shift+v",
    "history_size": 20,
    "auto_paste": True,
    # Apps that keep their own meaning of the hotkey. Empty the list to use the overlay everywhere.
    "excluded_apps": [
        "pycharm64.exe", "idea64.exe", "webstorm64.exe", "phpstorm64.exe", "clion64.exe",
        "goland64.exe", "rider64.exe", "rubymine64.exe", "datagrip64.exe", "dataspell64.exe",
        "rustrover64.exe", "studio64.exe",
    ],
}

_MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}


def parse_hotkey(text):
    """Return (modifiers, virtual_key) for text such as 'ctrl+shift+v' or 'alt+f9'."""
    parts = [part.strip().lower() for part in text.split("+")]
    modifiers = 0
    for part in parts[:-1]:
        if part not in _MODIFIERS:
            raise ValueError("unknown modifier %r" % part)
        modifiers |= _MODIFIERS[part]
    key = parts[-1]
    function_key = re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", key)
    if len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif function_key:
        vk = 0x6F + int(function_key.group(1))
    else:
        raise ValueError("unknown key %r" % key)
    if not modifiers:
        raise ValueError("the hotkey needs at least one of ctrl, alt, shift, win")
    return modifiers, vk


class Settings:
    def __init__(self, values):
        self.hotkey = values["hotkey"]
        self.hotkey_modifiers, self.hotkey_vk = parse_hotkey(self.hotkey)
        self.history_size = values["history_size"]
        self.auto_paste = values["auto_paste"]
        self.excluded_apps = frozenset(name.lower() for name in values["excluded_apps"])


def load(path):
    """Return (Settings, problems). Creates the file with defaults when it does not exist.
    Invalid values fall back to their defaults and are reported in problems."""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, indent=2)
        return Settings(DEFAULTS), []
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("expected a JSON object")
    except (OSError, ValueError) as error:
        return Settings(DEFAULTS), ["settings.json could not be read (%s); using defaults." % error]

    values, problems = dict(DEFAULTS), []
    checks = {
        "hotkey": lambda v: isinstance(v, str) and parse_hotkey(v),
        "history_size": lambda v: type(v) is int and 1 <= v <= 500,
        "auto_paste": lambda v: isinstance(v, bool),
        "excluded_apps": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    }
    for key, valid in checks.items():
        if key not in loaded:
            continue
        try:
            ok = valid(loaded[key])
        except ValueError:
            ok = False
        if ok:
            values[key] = loaded[key]
        else:
            problems.append("Invalid %s in settings.json; using %r." % (key, DEFAULTS[key]))
    return Settings(values), problems
