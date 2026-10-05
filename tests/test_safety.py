"""Guards the promises made to users about what this program never does."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = {
    "keyboard hooks or key-state polling": r"SetWindowsHookEx|GetAsyncKeyState|GetKeyboardState",
    "network access": r"\bimport (socket|ssl|urllib|http|ftplib|smtplib|requests)\b|"
                      r"\bfrom (socket|ssl|urllib|http|ftplib|smtplib|requests)\b",
    "registry access": r"\bwinreg\b|RegSetValue|RegCreateKey|RegOpenKey",
    "code loading from data": r"\bpickle\b|\beval\(|\bexec\(",
}


class SafetyTest(unittest.TestCase):
    def test_program_source_has_no_forbidden_capabilities(self):
        sources = list((ROOT / "cliphist").glob("*.py")) + [ROOT / "clipboard_history.pyw"]
        for path in sources:
            text = path.read_text(encoding="utf-8")
            for what, pattern in FORBIDDEN.items():
                self.assertIsNone(re.search(pattern, text), "%s in %s" % (what, path.name))


if __name__ == "__main__":
    unittest.main()
