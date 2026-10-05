"""A small window for the end-to-end tests to paste into. Usage: target_app.py OUTPUT_FOLDER"""
import os
import sys
import tkinter as tk

folder = sys.argv[1]
root = tk.Tk()
root.title("cliphist test target")
root.geometry("500x300+200+200")
text = tk.Text(root)
text.pack(fill="both", expand=True)
text.focus_set()


def save_text(event=None):
    with open(os.path.join(folder, "text.txt"), "w", encoding="utf-8") as f:
        f.write(text.get("1.0", "end-1c"))
    text.edit_modified(False)


def record_key(event):
    with open(os.path.join(folder, "keys.txt"), "a", encoding="utf-8") as f:
        f.write("%s %d\n" % (event.keysym, event.state))


def report_ready():
    with open(os.path.join(folder, "ready.txt"), "w", encoding="utf-8") as f:
        f.write("%d %d %d %d %d" % (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(),
                                    root.winfo_height(), int(root.wm_frame(), 16)))


text.bind("<<Modified>>", save_text)
text.bind("<Control-Key>", record_key, add=True)
root.after(500, report_ready)
root.mainloop()
