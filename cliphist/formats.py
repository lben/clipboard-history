"""Pure helpers for clipboard data formats. No Windows APIs in this module."""
import html.parser
import re
import struct

# ---------------------------------------------------------------- CF_HDROP

# DROPFILES: pFiles, pt.x, pt.y, fNC, fWide
_DROPFILES = struct.Struct("<IiiII")


def parse_dropfiles(data):
    """Return the list of paths stored in a CF_HDROP (DROPFILES) block."""
    offset, _x, _y, _nc, wide = _DROPFILES.unpack_from(data)
    body = data[offset:]
    if wide:
        text = body[: len(body) // 2 * 2].decode("utf-16-le", errors="replace")
    else:
        text = body.decode("mbcs", errors="replace")
    paths = []
    for path in text.split("\0"):
        if not path:
            break
        paths.append(path)
    return paths


def build_dropfiles(paths):
    """Build a CF_HDROP block with wide-character paths."""
    header = _DROPFILES.pack(_DROPFILES.size, 0, 0, 0, 1)
    return header + ("\0".join(paths) + "\0\0").encode("utf-16-le")


# ---------------------------------------------------------------- CF_HTML


def html_fragment(data):
    """Return the HTML fragment of a CF_HTML block as text."""
    header = data.split(b"<", 1)[0]

    def offset(name):
        match = re.search(rb"%s:(-?\d+)" % name, header)
        return int(match.group(1)) if match else -1

    for start_name, end_name in ((b"StartFragment", b"EndFragment"), (b"StartHTML", b"EndHTML")):
        start, end = offset(start_name), offset(end_name)
        if 0 <= start < end <= len(data):
            return data[start:end].decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- HTML -> styled runs

_SKIP = {"script", "style", "head", "title"}
_VOID = {"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "source", "wbr"}
_BLOCK = {"address", "article", "blockquote", "div", "dl", "dt", "dd", "footer", "h1", "h2", "h3",
          "h4", "h5", "h6", "header", "hr", "li", "ol", "p", "pre", "section", "table", "tr", "ul"}
_TAG_STYLE = {
    "b": {"b": True}, "strong": {"b": True}, "th": {"b": True},
    "i": {"i": True}, "em": {"i": True}, "cite": {"i": True}, "var": {"i": True},
    "u": {"u": True}, "ins": {"u": True},
    "s": {"s": True}, "strike": {"s": True}, "del": {"s": True},
    "code": {"mono": True}, "kbd": {"mono": True}, "pre": {"mono": True}, "samp": {"mono": True},
    "tt": {"mono": True},
    "h1": {"h": True}, "h2": {"h": True}, "h3": {"b": True}, "h4": {"b": True}, "h5": {"b": True},
    "h6": {"b": True},
    "a": {"link": True},
}


def _parse_color(value):
    """Return '#rrggbb' for hex or rgb() colors, or None. Near-white colors are dropped so text
    stays readable on the white preview background."""
    value = value.strip().lower()
    match = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", value)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        rgb = [int(digits[i:i + 2], 16) for i in (0, 2, 4)]
    else:
        match = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", value)
        if not match or (match.group(4) is not None and float(match.group(4)) == 0):
            return None
        rgb = [min(int(match.group(i)), 255) for i in (1, 2, 3)]
    if min(rgb) > 220:
        return None
    return "#%02x%02x%02x" % tuple(rgb)


def _css_style(css):
    style = {}
    for declaration in css.split(";"):
        name, _, value = declaration.partition(":")
        name, value = name.strip().lower(), value.strip().lower()
        if name == "font-weight":
            style["b"] = value in ("bold", "bolder") or (value.isdigit() and int(value) >= 600)
        elif name == "font-style":
            style["i"] = value in ("italic", "oblique")
        elif name in ("text-decoration", "text-decoration-line"):
            style["u"] = "underline" in value
            style["s"] = "line-through" in value
        elif name == "color":
            style["color"] = _parse_color(value)
        elif name == "font-family" and any(m in value for m in ("mono", "consolas", "courier")):
            style["mono"] = True
    return style


class _RunParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.runs = []
        self._stack = []  # (tag, style overrides)
        self._skip = 0
        self._line_start = True

    def _style(self):
        merged = {}
        for _tag, overrides in self._stack:
            merged.update(overrides)
        keys = [key for key, value in merged.items() if value is True]
        if merged.get("color"):
            keys.append("color=" + merged["color"])
        return tuple(sorted(keys))

    def _emit(self, text):
        style = self._style()
        if self.runs and self.runs[-1][1] == style:
            self.runs[-1][0] += text
        else:
            self.runs.append([text, style])
        self._line_start = text.endswith("\n")

    def _newline(self, force=False):
        if force or not self._line_start:
            self._emit("\n")

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in ("br", "hr"):
            self._newline(force=tag == "br")
            return
        if tag in _BLOCK:
            self._newline()
        if tag in ("td", "th") and not self._line_start:
            self._emit("\t")
        if tag in _VOID:
            return
        overrides = dict(_TAG_STYLE.get(tag, {}))
        attrs = dict(attrs)
        if tag == "font" and attrs.get("color"):
            overrides["color"] = _parse_color(attrs["color"])
        if attrs.get("style"):
            overrides.update(_css_style(attrs["style"]))
        self._stack.append((tag, overrides))
        if tag == "li":
            self._emit("• ")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        if tag in _BLOCK:
            self._newline()

    def handle_data(self, data):
        if self._skip:
            return
        if not any(tag == "pre" for tag, _ in self._stack):
            data = re.sub(r"\s+", " ", data)
            if self._line_start:
                data = data.lstrip(" ")
        if data:
            self._emit(data)


def html_runs(fragment, limit=20000):
    """Convert an HTML fragment to [(text, style)] runs, where style is a sorted tuple of
    'b', 'i', 'u', 's', 'mono', 'h', 'link' and 'color=#rrggbb'."""
    parser = _RunParser()
    parser.feed(fragment[: limit * 10])
    parser.close()
    runs, total = [], 0
    for text, style in parser.runs:
        if total >= limit:
            break
        text = text[: limit - total]
        total += len(text)
        runs.append((text, style))
    while runs and not runs[-1][0].strip():
        runs.pop()
    if runs:
        runs[-1] = (runs[-1][0].rstrip(), runs[-1][1])
    return runs


# ---------------------------------------------------------------- CF_DIB

_BI_RGB, _BI_BITFIELDS = 0, 3
_STANDARD_MASKS = (0x00FF0000, 0x0000FF00, 0x000000FF)


def dib_size(dib):
    """Return (width, height) of a CF_DIB block."""
    _header_size, width, height = struct.unpack_from("<Iii", dib)
    return width, abs(height)


def dib_thumbnail(dib, max_w, max_h):
    """Return (ppm_bytes, width, height) of a scaled-down copy of a 24/32-bit CF_DIB, or None when
    the pixel layout is not supported."""
    header_size, width, height, _planes, bpp, compression = struct.unpack_from("<IiiHHI", dib)
    colors_used = struct.unpack_from("<I", dib, 32)[0]
    if width <= 0 or height == 0 or bpp not in (24, 32):
        return None
    if compression == _BI_BITFIELDS:
        if bpp != 32:
            return None
        # The masks follow the 40-byte BITMAPINFOHEADER fields in every header version.
        if struct.unpack_from("<III", dib, 40) != _STANDARD_MASKS:
            return None
    elif compression != _BI_RGB:
        return None
    pixels_at = header_size + colors_used * 4
    if compression == _BI_BITFIELDS and header_size == 40:
        pixels_at += 12
    top_down = height < 0
    height = abs(height)
    step = bpp // 8
    stride = (width * step + 3) // 4 * 4
    if pixels_at + stride * height > len(dib):
        return None

    k = max(1, -(-width // max_w), -(-height // max_h))  # integer subsampling factor
    out_w, out_h = -(-width // k), -(-height // k)
    out = bytearray(out_w * out_h * 3)
    for row in range(out_h):
        y = row * k
        start = pixels_at + (y if top_down else height - 1 - y) * stride
        line = dib[start:start + width * step]
        base = row * out_w * 3
        end = base + out_w * 3
        out[base:end:3] = line[2::step * k]      # R
        out[base + 1:end:3] = line[1::step * k]  # G
        out[base + 2:end:3] = line[0::step * k]  # B
    return b"P6\n%d %d\n255\n" % (out_w, out_h) + bytes(out), out_w, out_h
