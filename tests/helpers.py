"""Builders for clipboard data used by several tests."""
import struct

from cliphist import history


def dib(width, height, bpp=32, pixels=None, top_down=False, bitfields=False):
    """A CF_DIB block. pixels: rows top to bottom of (r, g, b); black when omitted."""
    pixels = pixels or [[(0, 0, 0)] * width for _ in range(height)]
    stride = (width * bpp // 8 + 3) // 4 * 4
    header = struct.pack("<IiiHHIIiiII", 40, width, -height if top_down else height, 1, bpp,
                         3 if bitfields else 0, 0, 0, 0, 0, 0)
    masks = struct.pack("<III", 0xFF0000, 0xFF00, 0xFF) if bitfields else b""
    rows = []
    for y in range(height):
        line = b"".join(bytes((b, g, r) + ((0,) if bpp == 32 else ())) for r, g, b in pixels[y])
        rows.append(line + bytes(stride - len(line)))
    if not top_down:
        rows.reverse()  # bottom-up: last image row first
    return header + masks + b"".join(rows)


def cf_html(fragment):
    """A CF_HTML block whose header offsets point at fragment."""
    template = ("Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\n"
                "StartFragment:{:010d}\r\nEndFragment:{:010d}\r\n")
    size = len(template.format(0, 0, 0, 0))
    before = b"<html><body><!--StartFragment-->"
    body = before + fragment.encode("utf-8") + b"<!--EndFragment--></body></html>"
    start = size + len(before)
    end = start + len(fragment.encode("utf-8"))
    return template.format(size, size + len(body), start, end).encode("ascii") + body


def text_entry(text, html=None):
    raw = {"text": text.encode("utf-16-le")}
    if html is not None:
        raw["html"] = cf_html(html)
    return history.build_entry(raw)
