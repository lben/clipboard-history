import os
import tempfile
import unittest

from cliphist import history
from tests.helpers import dib, text_entry


class HistoryTest(unittest.TestCase):
    def test_copying_the_same_content_again_moves_it_to_the_top(self):
        h = history.History(20)
        first = h.add(text_entry("one"))
        h.add(text_entry("two"))
        again = h.add(text_entry("one"))
        self.assertIs(again, first)
        self.assertEqual([e.text for e in h.visible()], ["one", "two"])

    def test_limit_evicts_oldest_unpinned_and_never_pinned(self):
        h = history.History(2)
        pinned = h.add(text_entry("keep me"))
        h.toggle_pin(pinned)
        for word in ("a", "b", "c"):
            h.add(text_entry(word))
        self.assertEqual([e.text for e in h.visible()], ["keep me", "c", "b"])

    def test_pinned_entries_are_listed_first_and_survive_clear(self):
        h = history.History(20)
        h.add(text_entry("old"))
        h.toggle_pin(h.entries[0])
        h.add(text_entry("new"))
        self.assertEqual([e.text for e in h.visible()], ["old", "new"])
        h.clear_unpinned()
        self.assertEqual([e.text for e in h.visible()], ["old"])

    def test_filter_matches_text_and_paths_case_insensitively(self):
        h = history.History(20)
        h.add(text_entry("Hello World"))
        h.add(history.build_entry(paths=[r"C:\Data\Report.xlsx"], dirs=[False]))
        self.assertEqual([e.kind for e in h.visible("world")], ["text"])
        self.assertEqual([e.kind for e in h.visible("report")], ["files"])

    def test_whitespace_text_with_an_image_is_an_image(self):
        entry = history.build_entry({"text": " ".encode("utf-16-le"), "dib": dib(4, 2)})
        self.assertEqual(entry.kind, "image")
        self.assertEqual(entry.text, "Image 4 \u00d7 2")
        self.assertTrue(entry.thumb.startswith(b"P6\n4 2\n"))

    def test_nothing_usable_gives_no_entry(self):
        self.assertIsNone(history.build_entry({"text": b"", "html": None}))


class PersistenceTest(unittest.TestCase):
    def test_save_and_load_round_trip_through_the_cipher(self):
        h = history.History(20)
        h.add(text_entry("plain"))
        h.add(text_entry("rich", html="<b>rich</b>"))
        h.add(history.build_entry({"dib": dib(3, 3)}))
        h.add(history.build_entry(paths=[r"C:\a", r"C:\b.txt"], dirs=[True, False]))
        h.toggle_pin(h.entries[1])
        protect = lambda data: bytes(b ^ 0x5A for b in data)  # stand-in for DPAPI
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "history.bin")
            history.save(h, path, protect)
            with open(path, "rb") as f:
                self.assertNotIn(b"plain", f.read())
            loaded = history.load(path, protect, 20)
        self.assertEqual([(e.id, e.kind, e.text, e.pinned) for e in loaded.entries],
                         [(e.id, e.kind, e.text, e.pinned) for e in h.entries])
        rich = next(e for e in loaded.entries if e.text == "rich")
        self.assertIn(b"<b>rich</b>", rich.data("html"))
        files = next(e for e in loaded.entries if e.kind == "files")
        self.assertEqual((files.paths, files.dirs), ([r"C:\a", r"C:\b.txt"], [True, False]))
        image = next(e for e in loaded.entries if e.kind == "image")
        self.assertEqual((image.text, image.data("dib")), ("Image 3 \u00d7 3", dib(3, 3)))

    def test_missing_file_gives_empty_history(self):
        self.assertEqual(history.load("/nonexistent/history.bin", None, 20).entries, [])


if __name__ == "__main__":
    unittest.main()
