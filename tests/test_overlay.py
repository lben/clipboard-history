"""Drives the real overlay window with generated key events."""
import tkinter as tk
import unittest

from cliphist import history
from cliphist.overlay import Overlay
from tests.helpers import dib, text_entry


class OverlayTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("no display: %s" % error)
        self.root.withdraw()
        self.history = history.History(20)
        self.history.add(history.build_entry(paths=[r"C:\docs", r"C:\docs\a.txt"],
                                             dirs=[True, False]))
        self.history.add(history.build_entry(paths=[r"C:\docs\report.xlsx"], dirs=[False]))
        self.history.add(history.build_entry({"dib": dib(8, 4)}))
        self.history.add(text_entry("Rich text", html="Plain <b>bold</b> end"))
        self.history.add(text_entry("first line\nsecond line"))
        self.chosen, self.cancelled, self.changes = [], [], []
        self.overlay = Overlay(self.root, self.history,
                               on_choose=lambda *args: self.chosen.append(args),
                               on_cancel=self.cancelled.append,
                               on_change=lambda: self.changes.append(1))
        self.overlay.show((0, 0, 1200, 900), (0, 0, 1200, 900))
        self.overlay.top.focus_set()
        self.root.update()

    def tearDown(self):
        if hasattr(self, "root"):
            self.root.destroy()

    def key(self, sequence, **options):
        self.overlay.top.event_generate(sequence, **options)
        self.root.update()

    def type(self, text):
        for char in text:
            self.key("<KeyPress>", keysym=char)

    def texts(self):
        return [entry.text.splitlines()[0] if entry.kind != "image" else "image"
                for entry, _ in self.overlay.items]

    def test_arrows_and_enter_choose_an_entry(self):
        self.assertEqual(self.texts(), ["first line", "Rich text", "image",
                                        r"C:\docs\report.xlsx", r"C:\docs"])
        self.key("<Down>")
        self.key("<Return>")
        self.assertEqual(self.chosen, [(self.history.entries[1], None, False)])
        self.key("<Return>", state=0x1)  # Shift+Enter: no automatic paste
        self.assertEqual(self.chosen[-1][2], True)

    def test_typing_filters_and_backspace_edits_the_filter(self):
        self.type("rich")
        self.assertEqual(self.texts(), ["Rich text"])
        self.type("zz")
        self.assertEqual(self.texts(), [])
        self.key("<BackSpace>")
        self.key("<BackSpace>")
        self.assertEqual(self.texts(), ["Rich text"])
        self.assertEqual(len(self.history.entries), 5)  # Backspace never deletes entries

    def test_delete_removes_and_ctrl_p_pins_to_top(self):
        self.key("<Delete>")
        self.assertEqual(self.texts()[0], "Rich text")
        self.key("<Down>")
        self.key("<Down>")  # report.xlsx
        self.key("<Control-p>")
        self.assertEqual(self.texts()[0], r"C:\docs\report.xlsx")
        self.assertTrue(self.history.visible()[0].pinned)
        self.assertEqual(self.overlay.index, 0)  # the selection follows the pinned entry
        self.assertEqual(len(self.changes), 2)

    def test_bundle_opens_with_right_and_closes_with_left(self):
        for _ in range(4):
            self.key("<Down>")
        self.key("<Right>")
        self.assertEqual([child for _, child in self.overlay.items], [0, 1])
        self.key("<Down>")
        self.key("<Return>")
        bundle = self.history.entries[4]
        self.assertEqual(self.chosen, [(bundle, 1, False)])
        self.key("<Left>")
        self.assertIsNone(self.overlay.bundle)
        self.assertEqual(self.overlay.items[self.overlay.index], (bundle, None))

    def test_preview_shows_formatting_and_images(self):
        self.key("<Down>")
        preview = self.overlay.preview
        self.assertEqual(preview.get("1.0", "end-1c"), "Plain bold end")
        self.assertIn("style:b", preview.tag_names("1.7"))
        self.key("<Down>")
        self.assertEqual(len(preview.image_names()), 1)

    def test_malformed_html_falls_back_to_plain_text(self):
        self.overlay.hide()
        self.history.add(text_entry("secret pin 1234", html="<p><![ secret pin 1234</p>"))
        self.overlay.show((0, 0, 1200, 900), (0, 0, 1200, 900))
        self.root.update()
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.overlay.preview.get("1.0", "end-1c"), "secret pin 1234")

    def test_escape_closes_and_restores_focus(self):
        self.key("<Escape>")
        self.assertEqual(self.cancelled, [True])
        self.assertFalse(self.overlay.visible)


if __name__ == "__main__":
    unittest.main()
