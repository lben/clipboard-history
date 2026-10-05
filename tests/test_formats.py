import struct
import unittest

from cliphist import formats
from tests.helpers import cf_html, dib


RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)
IMAGE = [[RED, GREEN, BLUE], [WHITE, RED, GREEN]]  # rows top to bottom


def ppm_pixels(ppm, width, height):
    data = ppm[len(b"P6\n%d %d\n255\n" % (width, height)):]
    return [[tuple(data[(y * width + x) * 3:(y * width + x) * 3 + 3]) for x in range(width)]
            for y in range(height)]


class DropFilesTest(unittest.TestCase):
    def test_round_trip_keeps_unicode_paths(self):
        paths = [r"C:\Users\Zoë\Désktop\report.xlsx", r"\\server\share\folder"]
        self.assertEqual(formats.parse_dropfiles(formats.build_dropfiles(paths)), paths)


class HtmlTest(unittest.TestCase):
    def test_fragment_is_cut_by_byte_offsets(self):
        self.assertEqual(formats.html_fragment(cf_html("<b>café</b>")), "<b>café</b>")

    def test_runs_keep_formatting(self):
        runs = formats.html_runs(
            '<p>Plain <b>bold <i>both</i></b> <span style="color: rgb(200, 0, 0)">red</span></p>'
            '<ul><li>item</li></ul><a href="x">link</a>')
        self.assertEqual(runs, [
            ("Plain ", ()), ("bold ", ("b",)), ("both", ("b", "i")), (" ", ()),
            ("red", ("color=#c80000",)), ("\n\u2022 item\n", ()), ("link", ("link",))])

    def test_inline_style_can_switch_bold_off(self):
        # Google Docs wraps whole documents in <b style="font-weight:normal">.
        runs = formats.html_runs('<b style="font-weight:normal">not bold</b>')
        self.assertEqual(runs, [("not bold", ())])


class DibTest(unittest.TestCase):
    def test_bottom_up_and_top_down_images_give_the_same_pixels(self):
        for bpp in (24, 32):
            for top_down in (False, True):
                ppm, w, h = formats.dib_thumbnail(dib(3, 2, bpp, IMAGE, top_down), 10, 10)
                self.assertEqual((w, h), (3, 2))
                self.assertEqual(ppm_pixels(ppm, w, h), IMAGE, (bpp, top_down))

    def test_large_images_are_subsampled_to_fit(self):
        ppm, w, h = formats.dib_thumbnail(dib(3, 2, 32, IMAGE, bitfields=True), 2, 2)
        self.assertEqual((w, h), (2, 1))
        self.assertEqual(ppm_pixels(ppm, w, h), [[RED, BLUE]])

    def test_unsupported_layouts_give_no_thumbnail(self):
        self.assertIsNone(formats.dib_thumbnail(dib(3, 2, 24, IMAGE)[:50], 10, 10))
        palette = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 8, 0, 0, 0, 0, 0, 0)
        self.assertIsNone(formats.dib_thumbnail(palette + bytes(1024 + 8), 10, 10))


if __name__ == "__main__":
    unittest.main()
