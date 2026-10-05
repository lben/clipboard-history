"""The history picker window. Plain tkinter; Windows-specific actions are passed in as callbacks."""
import ntpath
import tkinter as tk
import tkinter.font as tkfont

from . import formats

BG = "#2b2d30"
SELECTED = "#2e436e"
FG = "#dfe1e5"
DIM = "#9a9da3"
ACCENT = "#e8b44c"
BORDER = "#5a5d63"
PREVIEW_BG = "#ffffff"
PREVIEW_FG = "#1f1f1f"
LINK = "#0b57d0"
UI_FONT = "Segoe UI"
MONO_FONT = "Consolas"
WIDTH, LIST_HEIGHT, PREVIEW_HEIGHT = 640, 360, 190  # pixels at 96 DPI
PREVIEW_IMAGE = (600, 170)
PREVIEW_CHARS = 20000
HINT = "Enter paste    Del remove    Ctrl+P pin    → open bundle    Esc close"
# Tk modifier bits on Windows
STATE_SHIFT, STATE_CONTROL, STATE_ALT = 0x1, 0x4, 0x20000


def _fit(text, font, width):
    """Cut text with an ellipsis so it fits in width pixels."""
    text = text[:400]
    if font.measure(text) <= width:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if font.measure(text[:middle] + "…") <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "…"


def _name(path):
    return ntpath.basename(path.rstrip("\\/")) or path


class Overlay:
    def __init__(self, root, history, on_choose, on_cancel, on_change, on_shown=None):
        """on_choose(entry, item_index_or_None, shift_held); on_cancel(restore_focus);
        on_change() after a delete or pin; on_shown(toplevel) after the window appears."""
        self.root = root
        self.history = history
        self.on_choose = on_choose
        self.on_cancel = on_cancel
        self.on_change = on_change
        self.on_shown = on_shown
        self.visible = False
        self.query = ""
        self.bundle = None  # files entry whose items are listed, or None
        self._outer = ("", 0)  # query and selection to restore when leaving a bundle
        self.items = []  # (entry, item index inside a bundle or None)
        self.index = 0
        self.rows = []
        self._painted = None
        self._cache = {}  # PhotoImages (must stay referenced) and parsed HTML, keyed by entry id
        self._tags = set()

        scale = root.winfo_fpixels("1i") / 96.0
        self.px = lambda value: int(round(value * scale))
        px = self.px
        self.font = tkfont.Font(root, family=UI_FONT, size=10)
        self.small = tkfont.Font(root, family=UI_FONT, size=9)
        self.folder_icon = self._icon(folder=True)
        self.file_icon = self._icon(folder=False)

        top = self.top = tk.Toplevel(root, bg=BORDER, padx=1, pady=1)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        self.header = tk.Label(top, bg=BG, fg=DIM, font=self.small, anchor="w", padx=px(10), pady=px(6))
        self.header.pack(fill="x")
        self.canvas = tk.Canvas(top, bg=BG, highlightthickness=0, width=px(WIDTH),
                                height=px(LIST_HEIGHT))
        self.canvas.pack(fill="x")
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.canvas.create_window(0, 0, window=self.inner, anchor="nw", width=px(WIDTH))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=(0, 0, px(WIDTH), max(e.height, px(LIST_HEIGHT)))))
        frame = tk.Frame(top, width=px(WIDTH), height=px(PREVIEW_HEIGHT), bg=PREVIEW_BG)
        frame.pack_propagate(False)
        frame.pack(fill="x")
        self.preview = tk.Text(frame, bg=PREVIEW_BG, fg=PREVIEW_FG, wrap="word", relief="flat",
                               padx=px(10), pady=px(8), font=(UI_FONT, 10), highlightthickness=0,
                               cursor="arrow", takefocus=0)
        self.preview.pack(fill="both", expand=True)
        self.preview.bind("<Button-1>", lambda e: "break")  # keep keyboard focus on the list
        tk.Label(top, text=HINT, bg=BG, fg=DIM, font=self.small, anchor="w", padx=px(10),
                 pady=px(5)).pack(fill="x")

        bindings = {
            "<Up>": lambda e: self._move(-1), "<Down>": lambda e: self._move(1),
            "<Return>": self._choose, "<KP_Enter>": self._choose,
            "<Escape>": lambda e: self.cancel(), "<Delete>": lambda e: self._delete(),
            "<Control-p>": lambda e: self._pin(), "<Control-P>": lambda e: self._pin(),
            "<Right>": lambda e: self._open_bundle(), "<Left>": lambda e: self._close_bundle(),
            "<BackSpace>": lambda e: self._set_query(self.query[:-1]),
            "<KeyPress>": self._type, "<FocusOut>": self._focus_out,
        }
        for sequence, handler in bindings.items():
            top.bind(sequence, handler)

    # ------------------------------------------------------------ public

    def show(self, target_rect, work_area):
        """Open centered over target_rect (left, top, right, bottom), kept inside work_area."""
        self.query, self.bundle, self.index = "", None, 0
        self._rebuild()
        self.canvas.yview_moveto(0)
        self.top.update_idletasks()
        width, height = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        box = target_rect or work_area or (0, 0, self.root.winfo_screenwidth(),
                                           self.root.winfo_screenheight())
        x = (box[0] + box[2] - width) // 2
        y = (box[1] + box[3] - height) // 2
        if work_area:
            x = max(work_area[0], min(x, work_area[2] - width))
            y = max(work_area[1], min(y, work_area[3] - height))
        self.top.geometry("+%d+%d" % (x, y))
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()
        self.top.update_idletasks()  # the window must exist before on_shown activates it
        self.visible = True
        if self.on_shown:
            self.on_shown(self.top)

    def hide(self):
        self.top.withdraw()
        self.visible = False

    def cancel(self, restore=True):
        if self.visible:
            self.on_cancel(restore)  # before hiding, while this app may still hand over focus
            self.hide()

    def refresh(self):
        if self.visible:
            self._rebuild()

    # ------------------------------------------------------------ list

    def _rebuild(self, select=None):
        if self.bundle is not None and self.bundle not in self.history.entries:
            self.bundle = None
        if self.bundle is not None:
            query = self.query.lower()
            self.items = [(self.bundle, i) for i, path in enumerate(self.bundle.paths)
                          if query in path.lower()]
        else:
            self.items = [(entry, None) for entry in self.history.visible(self.query)]
        if select is not None and (select, None) in self.items:
            self.index = self.items.index((select, None))
        self.index = max(0, min(self.index, len(self.items) - 1))

        for row in self.rows:
            row.destroy()
        self._painted = None
        self.rows = [self._make_row(n, entry, child) for n, (entry, child) in enumerate(self.items)]
        if not self.items:
            empty = tk.Label(self.inner, text="No matches." if self.query else "Nothing copied yet.",
                             bg=BG, fg=DIM, font=self.font, padx=self.px(10), pady=self.px(10))
            empty.pack(anchor="w")
            self.rows.append(empty)

        live = {entry.id for entry in self.history.entries}
        self._cache = {key: value for key, value in self._cache.items() if key[1] in live}
        if self.bundle is not None:
            title = "◂ %d items    (← back)" % len(self.bundle.paths)
        else:
            title = "Clipboard history"
        self.header.configure(text=title + ("     Filter: " + self.query if self.query
                                            else "     Type to filter"))
        self._select(self.index)

    def _make_row(self, n, entry, child):
        px = self.px
        row = tk.Frame(self.inner, bg=BG, padx=px(8), pady=px(4))
        row.pack(fill="x")
        row.columnconfigure(2, weight=1)
        star = "★" if entry.pinned and child is None else ""
        tk.Label(row, text=star, fg=ACCENT, bg=BG, font=self.font, width=2, anchor="w").grid(
            row=0, column=0, sticky="nw")
        width = px(WIDTH - 150)

        def text(value, line=0, font=None, color=FG):
            font = font or self.font
            tk.Label(row, text=_fit(value, font, width), fg=color, bg=BG, font=font,
                     anchor="w").grid(row=line, column=2, sticky="w")

        def icon(image):
            tk.Label(row, image=image, bg=BG).grid(row=0, column=1, sticky="w", padx=(0, px(6)))

        if entry.kind == "files" and (child is not None or len(entry.paths) == 1):
            i = child if child is not None else 0
            icon(self.folder_icon if entry.dirs[i] else self.file_icon)
            text(_name(entry.paths[i]))
            text(entry.paths[i], 1, self.small, DIM)
        elif entry.kind == "files":
            icon(self.folder_icon if all(entry.dirs) else self.file_icon)
            text("%d items: %s" % (len(entry.paths), ", ".join(_name(p) for p in entry.paths)))
            text(ntpath.dirname(entry.paths[0]), 1, self.small, DIM)
            tk.Label(row, text="▸", fg=FG, bg=BG, font=self.font).grid(
                row=0, column=3, rowspan=2, padx=(px(6), 0))
        elif entry.kind == "image":
            photo = self._photo("thumb", entry)
            if photo is not None:
                tk.Label(row, image=photo, bg=BG).grid(row=0, column=1, sticky="w",
                                                       padx=(0, px(8)))
            text(entry.text)
        else:
            first = next((line.strip() for line in entry.text.splitlines() if line.strip()), "")
            text(first.replace("\t", "    "))

        return row

    def _paint(self, widget, color):
        widget.configure(bg=color)
        for child in widget.winfo_children():
            self._paint(child, color)

    def _select(self, index):
        if not self.items:
            self._show_preview(None)
            return
        if self._painted is not None and self._painted < len(self.rows):
            self._paint(self.rows[self._painted], BG)
        self.index = index
        row = self.rows[index]
        self._paint(row, SELECTED)
        self._painted = index
        self.inner.update_idletasks()
        region = max(self.inner.winfo_height(), self.canvas.winfo_height(), 1)
        view = self.canvas.winfo_height()
        top = self.canvas.canvasy(0)
        if row.winfo_y() < top:
            self.canvas.yview_moveto(row.winfo_y() / region)
        elif row.winfo_y() + row.winfo_height() > top + view:
            self.canvas.yview_moveto((row.winfo_y() + row.winfo_height() - view) / region)
        self._show_preview(self.items[index])

    # ------------------------------------------------------------ preview

    def _show_preview(self, item):
        view = self.preview
        view.configure(state="normal")
        view.delete("1.0", "end")
        if item is None:
            view.insert("end", "No matches." if self.query else "Nothing copied yet.")
        else:
            entry, child = item
            if entry.kind == "files":
                paths = entry.paths if child is None else [entry.paths[child]]
                view.insert("end", "\n".join(paths), self._tag(("mono",)))
            elif entry.kind == "image":
                photo = self._photo("preview", entry)
                if photo is not None:
                    view.image_create("end", image=photo)
                else:
                    view.insert("end", entry.text)
            else:
                runs = self._runs(entry)
                if runs:
                    for text, style in runs:
                        view.insert("end", text, self._tag(style))
                else:
                    view.insert("end", entry.text[:PREVIEW_CHARS], self._tag(("mono",)))
        view.configure(state="disabled")
        view.yview_moveto(0)

    def _runs(self, entry):
        key = ("runs", entry.id)
        if key not in self._cache:
            html = entry.data("html")
            try:
                runs = formats.html_runs(formats.html_fragment(html), PREVIEW_CHARS) if html else None
            except Exception:  # malformed HTML: show plain text; never log it (it is clipboard content)
                runs = None
            self._cache[key] = runs
        return self._cache[key]

    def _photo(self, kind, entry):
        key = (kind, entry.id)
        if key not in self._cache:
            if kind == "thumb":
                ppm = entry.thumb
            else:
                small = formats.dib_thumbnail(entry.data("dib"), self.px(PREVIEW_IMAGE[0]),
                                              self.px(PREVIEW_IMAGE[1]))
                ppm = small[0] if small else None
            self._cache[key] = tk.PhotoImage(master=self.root, data=ppm, format="PPM") if ppm else None
        return self._cache[key]

    def _tag(self, style):
        name = "style:" + "|".join(style)
        if name not in self._tags:
            heading = "h" in style
            font = (MONO_FONT if "mono" in style else UI_FONT, 13 if heading else 10)
            if "b" in style or heading:
                font += ("bold",)
            if "i" in style:
                font += ("italic",)
            options = {"font": font, "underline": "u" in style or "link" in style,
                       "overstrike": "s" in style}
            color = next((item[6:] for item in style if item.startswith("color=")), None)
            if "link" in style:
                color = LINK
            if color:
                options["foreground"] = color
            self.preview.tag_configure(name, **options)
            self._tags.add(name)
        return name

    def _icon(self, folder):
        px = self.px
        image = tk.PhotoImage(master=self.root, width=px(16), height=px(16))
        if folder:
            image.put("#d39b2f", to=(px(1), px(2), px(7), px(4)))
            image.put("#e8b44c", to=(px(1), px(4), px(15), px(14)))
        else:
            image.put("#c9ccd1", to=(px(3), px(1), px(13), px(15)))
            for top, right in ((5, 11), (8, 11), (11, 9)):
                image.put("#7d8187", to=(px(5), px(top), px(right), px(top + 1)))
        return image

    # ------------------------------------------------------------ keys

    def _move(self, delta):
        if self.items:
            self._select(max(0, min(len(self.items) - 1, self.index + delta)))

    def _choose(self, event):
        if self.items:
            entry, child = self.items[self.index]
            shift = event is not None and bool(event.state & STATE_SHIFT)
            self.on_choose(entry, child, shift)
        return "break"

    def _delete(self):
        if self.bundle is None and self.items:
            self.history.remove(self.items[self.index][0])
            self.on_change()
            self._rebuild()

    def _pin(self):
        if self.bundle is None and self.items:
            entry = self.items[self.index][0]
            self.history.toggle_pin(entry)
            self.on_change()
            self._rebuild(select=entry)

    def _open_bundle(self):
        if self.bundle is None and self.items:
            entry = self.items[self.index][0]
            if entry.kind == "files" and len(entry.paths) > 1:
                self._outer = (self.query, self.index)
                self.bundle, self.query, self.index = entry, "", 0
                self._rebuild()

    def _close_bundle(self):
        if self.bundle is not None:
            entry, self.bundle = self.bundle, None
            self.query, self.index = self._outer
            self._rebuild(select=entry)

    def _set_query(self, query):
        self.query, self.index = query, 0
        self._rebuild()

    def _type(self, event):
        control, alt = bool(event.state & STATE_CONTROL), bool(event.state & STATE_ALT)
        if control != alt:  # a shortcut, not text (Ctrl+Alt is AltGr)
            return
        if event.char and event.char.isprintable():
            self._set_query(self.query + event.char)

    def _focus_out(self, event):
        if self.visible:
            self.top.after(100, self._check_focus)

    def _check_focus(self):
        try:
            focused = self.top.focus_get()
        except KeyError:
            return
        if self.visible and focused is None:
            self.cancel(restore=False)
