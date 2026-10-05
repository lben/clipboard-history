import json
import os
import tempfile
import unittest

from cliphist import settings


class SettingsTest(unittest.TestCase):
    def test_hotkeys(self):
        self.assertEqual(settings.parse_hotkey("ctrl+shift+v"), (0x2 | 0x4, ord("V")))
        self.assertEqual(settings.parse_hotkey("Alt + F9"), (0x1, 0x78))
        for bad in ("v", "ctrl+", "hyper+v", "ctrl+enter"):
            with self.assertRaises(ValueError, msg=bad):
                settings.parse_hotkey(bad)

    def test_first_run_writes_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            loaded, problems = settings.load(path)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), settings.DEFAULTS)
        self.assertEqual(problems, [])
        self.assertEqual((loaded.hotkey, loaded.history_size, loaded.auto_paste),
                         ("ctrl+shift+v", 20, True))
        self.assertIn("pycharm64.exe", loaded.excluded_apps)

    def test_invalid_values_fall_back_and_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"hotkey": "nonsense", "history_size": 50, "auto_paste": False,
                           "excluded_apps": ["Code.exe"]}, f)
            loaded, problems = settings.load(path)
        self.assertEqual(loaded.hotkey, "ctrl+shift+v")
        self.assertEqual((loaded.history_size, loaded.auto_paste), (50, False))
        self.assertEqual(loaded.excluded_apps, frozenset({"code.exe"}))
        self.assertEqual(len(problems), 1)

    def test_broken_json_uses_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not json")
            loaded, problems = settings.load(path)
        self.assertEqual(loaded.history_size, 20)
        self.assertEqual(len(problems), 1)


if __name__ == "__main__":
    unittest.main()
