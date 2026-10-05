"""Clipboard history model and its encrypted file format."""
import base64
import hashlib
import json
import os
import time
import zlib

from . import formats

THUMB_SIZE = (96, 64)
TEXT_LIMIT = 100_000  # characters kept for display and filtering


class Entry:
    """One clipboard item. formats maps 'text' (UTF-16-LE), 'html', 'rtf', 'dib' or 'png' to
    zlib-compressed bytes; file entries keep their paths instead."""

    def __init__(self, kind, text, digest, formats=None, paths=None, dirs=None, size=None,
                 thumb=None, pinned=False, created=None, id=None):
        self.kind = kind  # 'text', 'image' or 'files'
        self.text = text
        self.digest = digest
        self.formats = formats or {}
        self.paths = paths or []
        self.dirs = dirs or []
        self.size = size
        self.thumb = thumb  # PPM bytes for image entries
        self.pinned = pinned
        self.created = created or time.time()
        self.id = id or os.urandom(8).hex()

    def data(self, name):
        packed = self.formats.get(name)
        return zlib.decompress(packed) if packed is not None else None


def build_entry(raw=None, paths=None, dirs=None):
    """Build an Entry from data read off the clipboard, or return None when nothing usable.

    raw maps format names to bytes; paths/dirs describe copied files and folders."""
    if paths:
        digest = hashlib.sha256("\0".join(["files"] + paths).encode("utf-8")).hexdigest()
        return Entry("files", "\n".join(paths), digest, paths=list(paths), dirs=list(dirs))
    raw = {name: data for name, data in (raw or {}).items() if data}
    text = raw.get("text", b"").decode("utf-16-le", errors="replace")
    if text.strip():
        kind, keep = "text", ("text", "html", "rtf")
    elif "dib" in raw:
        kind, keep = "image", ("dib", "png")
    else:
        return None
    kept = {name: raw[name] for name in keep if name in raw}
    digest = hashlib.sha256(kind.encode())
    for name in sorted(kept):
        digest.update(b"\0%s\0%d\0" % (name.encode(), len(kept[name])))
        digest.update(kept[name])
    size = thumb = None
    if kind == "image":
        size = formats.dib_size(kept["dib"])
        text = "Image %d × %d" % size
        small = formats.dib_thumbnail(kept["dib"], *THUMB_SIZE)
        thumb = small[0] if small else None
    packed = {name: zlib.compress(data, 1) for name, data in kept.items()}
    return Entry(kind, text[:TEXT_LIMIT], digest.hexdigest(), formats=packed, size=size,
                 thumb=thumb)


class History:
    """Most recent first. Pinned entries are shown first and never evicted."""

    def __init__(self, limit, entries=None):
        self.limit = limit
        self.entries = list(entries or [])
        self._trim()

    def _trim(self):
        unpinned = 0
        kept = []
        for entry in self.entries:
            if not entry.pinned:
                unpinned += 1
                if unpinned > self.limit:
                    continue
            kept.append(entry)
        self.entries = kept

    def add(self, entry):
        """Add a new copy; a copy identical to an existing entry moves that entry to the top."""
        for existing in self.entries:
            if existing.digest == entry.digest:
                self.use(existing)
                return existing
        self.entries.insert(0, entry)
        self._trim()
        return entry

    def use(self, entry):
        self.entries.remove(entry)
        self.entries.insert(0, entry)

    def remove(self, entry):
        self.entries.remove(entry)

    def toggle_pin(self, entry):
        entry.pinned = not entry.pinned
        self._trim()

    def clear_unpinned(self):
        self.entries = [entry for entry in self.entries if entry.pinned]

    def set_limit(self, limit):
        self.limit = limit
        self._trim()

    def visible(self, query=""):
        query = query.lower()
        matches = [e for e in self.entries if query in e.text.lower()]
        return [e for e in matches if e.pinned] + [e for e in matches if not e.pinned]


# ---------------------------------------------------------------- file format

def _b64(data):
    return base64.b64encode(data).decode("ascii") if data is not None else None


def _unb64(text):
    return base64.b64decode(text) if text is not None else None


def dumps(history):
    entries = [{
        "id": e.id, "kind": e.kind, "text": e.text, "digest": e.digest, "pinned": e.pinned,
        "created": e.created, "paths": e.paths, "dirs": e.dirs, "size": e.size,
        "thumb": _b64(e.thumb), "formats": {name: _b64(data) for name, data in e.formats.items()},
    } for e in history.entries]
    return json.dumps({"version": 1, "entries": entries}).encode("utf-8")


def loads(data, limit):
    document = json.loads(data.decode("utf-8"))
    entries = [Entry(
        d["kind"], d["text"], d["digest"],
        formats={name: _unb64(b) for name, b in d["formats"].items()},
        paths=d["paths"], dirs=d["dirs"], size=tuple(d["size"]) if d["size"] else None,
        thumb=_unb64(d["thumb"]), pinned=d["pinned"], created=d["created"], id=d["id"],
    ) for d in document["entries"]]
    return History(limit, entries)


def save(history, path, protect):
    """Encrypt with protect() and replace the file atomically."""
    blob = protect(dumps(history))
    temp = path + ".tmp"
    with open(temp, "wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def load(path, unprotect, limit):
    """Return the saved History, or an empty one when no file exists. Raises on unreadable files."""
    if not os.path.exists(path):
        return History(limit)
    with open(path, "rb") as f:
        blob = f.read()
    return loads(unprotect(blob), limit)
