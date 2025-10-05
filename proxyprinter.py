#!/usr/bin/env python3

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

# ----------- SIMPLE DEFAULTS -----------
DEFAULT_CARD_W_MM = 62.0
DEFAULT_CARD_H_MM = 87.0
DEFAULT_DPI       = 300

THUMB_W = 180     # thumbnail max width (px)
THUMB_H = 260     # thumbnail max height (px)
TILE_PAD = 8      # space around each tile in the grid (px)
FRAME_PAD = 6     # inner padding of each tile frame (px)

# ----- Optional drag & drop support via tkinterdnd2 -----
DND_AVAILABLE = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False


# ------------- Core build logic -------------
def mm_to_px(mm, dpi):
    return int(round(mm * dpi / 25.4))

def load_image_safe(path):
    """
    Open image preserving transparency if present.
    (Do not convert to RGB until paste/flatten.)
    """
    im = Image.open(path)
    if im.mode in ("P", "LA"):
        im = im.convert("RGBA")
    return im

def make_pages_from_paths(image_paths, dpi, card_w_mm, card_h_mm):
    """Create pages from a list of image file paths. List may contain duplicates."""
    page_w = mm_to_px(210, dpi)  # A4
    page_h = mm_to_px(297, dpi)
    card_w = mm_to_px(card_w_mm, dpi)
    card_h = mm_to_px(card_h_mm, dpi)

    # Touching layout: gutter = 0, centered block
    m_h = int(round(max(0, (page_w - 3 * card_w) / 2)))
    m_v = int(round(max(0, (page_h - 3 * card_h) / 2)))

    x_origins = [m_h + i * card_w for i in range(3)]
    y_origins = [m_v + j * card_h for j in range(3)]

    pages = []
    idx = 0
    total = len(image_paths)
    while idx < total:
        page = Image.new("RGB", (page_w, page_h), (255, 255, 255))
        for row in range(3):
            for col in range(3):
                if idx >= total:
                    break
                path = image_paths[idx]
                try:
                    img = load_image_safe(path)
                except Exception as e:
                    print(f"Warning: couldn't open {path}: {e}")
                    idx += 1
                    continue

                img_resized = img.resize((card_w, card_h), Image.LANCZOS)

                # Paste with alpha mask if present (avoid black corners)
                if img_resized.mode in ("RGBA", "LA"):
                    alpha = img_resized.split()[-1]
                    page.paste(img_resized.convert("RGB"), (x_origins[col], y_origins[row]), mask=alpha)
                else:
                    page.paste(img_resized.convert("RGB"), (x_origins[col], y_origins[row]))
                idx += 1
            if idx >= total:
                break
        pages.append(page)
    return pages


# ------------- GUI -------------
class ProxyApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Proxy Card Printer — Gallery")
        self.root.minsize(700, 500)

        # Data
        self.items = []           # list of dicts: {path, qty}
        self.thumb_cache = {}     # path -> PhotoImage
        self.tiles = []           # per-item tile widgets (for fast qty updates)
        self._current_cols = None

        # Toolbar (tiny, simple)
        self._build_toolbar()

        # Scrollable gallery
        self._build_gallery()

        # Status
        self.status = tk.StringVar(value=("Drag & drop images or use Add Files/Folder"
                                          if DND_AVAILABLE else
                                          "Drag & drop not available (install tkinterdnd2)."))
        self._build_status()

        # Initial layout
        self._render_tiles_full()

    # ---- UI builders ----
    def _build_toolbar(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=10, pady=(8,4))

        ttk.Button(bar, text="Add Files", command=self.add_files).pack(side="left")
        ttk.Button(bar, text="Add Folder", command=self.add_folder).pack(side="left", padx=(6,12))
        ttk.Button(bar, text="Clear", command=self.clear_all).pack(side="left")

        ttk.Button(bar, text="Make PDF…", command=self.make_pdf).pack(side="right")

    def _build_gallery(self):
        wrap = ttk.Frame(self.root)
        wrap.pack(fill="both", expand=True, padx=10, pady=(0,10))

        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        self.vbar = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.inner = ttk.Frame(self.canvas)
        self.win = self.canvas.create_window((0,0), window=self.inner, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")

        # Resize behaviors
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Enable wheel/trackpad scrolling when pointer is over the canvas
        self.canvas.bind("<Enter>", self._activate_wheel)
        self.canvas.bind("<Leave>", self._deactivate_wheel)

        # Drag & drop onto the canvas
        if DND_AVAILABLE:
            self.canvas.drop_target_register("DND_Files")
            try:
                from tkinterdnd2 import DND_FILES
                self.canvas.drop_target_register(DND_FILES)
            except Exception:
                pass
            self.canvas.dnd_bind('<<Drop>>', self._on_drop_files)

    def _build_status(self):
        statusbar = ttk.Frame(self.root)
        statusbar.pack(fill="x")
        ttk.Label(statusbar, textvariable=self.status, anchor="w").pack(side="left", padx=10, pady=6)

    # ---- Wheel/trackpad scrolling ----
    def _activate_wheel(self, _evt=None):
        # Windows & macOS use <MouseWheel>
        if sys.platform == "darwin" or sys.platform.startswith("win"):
            self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        # Linux/X11 typically uses Button-4/5
        if sys.platform.startswith("linux"):
            self.canvas.bind("<Button-4>", self._on_linux_wheel)
            self.canvas.bind("<Button-5>", self._on_linux_wheel)

    def _deactivate_wheel(self, _evt=None):
        if sys.platform == "darwin" or sys.platform.startswith("win"):
            self.root.unbind_all("<MouseWheel>")
        if sys.platform.startswith("linux"):
            self.canvas.unbind("<Button-4>")
            self.canvas.unbind("<Button-5>")

    def _on_mousewheel(self, event):
        # Normalize delta across platforms
        if sys.platform == "darwin":
            # On macOS, delta is already in small steps; invert for natural scroll
            self.canvas.yview_scroll(-1 * int(event.delta), "units")
        else:
            # Windows: event.delta is multiples of 120
            self.canvas.yview_scroll(-1 * int(event.delta / 120), "units")

    def _on_linux_wheel(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    # ---- Reflow helper ----
    def _force_reflow_after_idle(self):
        """Measure the actual canvas width after Tk has settled, then re-grid."""
        def _do():
            self.inner.update_idletasks()
            w = self.canvas.winfo_width()
            if w <= 1:
                w = max(300, self.root.winfo_width() - 20)
            self._current_cols = None
            self._relayout_columns(w)
        self.root.after_idle(_do)

    # ---- DnD and adding files ----
    def _on_drop_files(self, event):
        paths = self._parse_dnd_paths(event.data)
        self._add_paths(paths)

    def _parse_dnd_paths(self, raw):
        out, cur, in_brace = [], [], False
        for ch in raw:
            if ch == "{":
                in_brace, cur = True, []
            elif ch == "}":
                in_brace = False
                p = "".join(cur).strip()
                if p:
                    out.append(p)
                cur = []
            elif ch == " " and not in_brace:
                if cur:
                    p = "".join(cur).strip()
                    if p:
                        out.append(p)
                    cur = []
            else:
                cur.append(ch)
        if cur:
            p = "".join(cur).strip()
            if p:
                out.append(p)
        return out

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select card images",
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg"), ("All files", "*.*")]
        )
        if paths:
            self._add_paths(paths)

    def add_folder(self):
        d = filedialog.askdirectory(title="Select folder containing images")
        if d:
            self._add_paths([d])

    def _add_paths(self, paths):
        added = 0
        for p in paths:
            if os.path.isdir(p):
                for f in sorted(os.listdir(p)):
                    fp = os.path.join(p, f)
                    if os.path.isfile(fp) and self._is_image(fp):
                        self.items.append({"path": fp, "qty": 1})
                        added += 1
            else:
                if self._is_image(p) and os.path.isfile(p):
                    self.items.append({"path": p, "qty": 1})
                    added += 1
        self._render_tiles_full()
        self._force_reflow_after_idle()
        if added:
            self.status.set(f"Added {added} image(s).")

    def _is_image(self, path):
        return os.path.splitext(path)[1].lower() in (".png", ".jpg", ".jpeg")

    # ---- Gallery / thumbnails ----
    def _thumb_for(self, path):
        if path in self.thumb_cache:
            return self.thumb_cache[path]
        try:
            img = Image.open(path)
            if img.mode in ("RGBA", "LA"):
                bg = Image.new("RGB", img.size, (255,255,255))
                alpha = img.split()[-1]
                bg.paste(img.convert("RGB"), mask=alpha)
                img = bg
            else:
                img = img.convert("RGB")
            img.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
            ph = ImageTk.PhotoImage(img)
            self.thumb_cache[path] = ph
            return ph
        except Exception:
            ph = ImageTk.PhotoImage(Image.new("RGB", (THUMB_W, THUMB_H), (240,240,240)))
            self.thumb_cache[path] = ph
            return ph

    def _on_inner_configure(self, _event=None):
        # Update scrollregion whenever inner content size changes
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # Stretch inner frame width to canvas width
        self.canvas.itemconfigure(self.win, width=event.width)

        # Debounce reflow so it only happens after resizing stops
        if hasattr(self, "_resize_after_id"):
            self.root.after_cancel(self._resize_after_id)

        def do_reflow():
            self._relayout_columns(event.width)

        self._resize_after_id = self.root.after(150, do_reflow)  # 150 ms delay

    def _tile_size_px(self):
        """Return approximate tile width used for column calculation."""
        # each tile frame has border+padding and we add TILE_PAD outside
        return THUMB_W + FRAME_PAD*2 + TILE_PAD*2

    def _relayout_columns(self, avail_width):
        """Re-grid tiles based on available width (adaptive columns)."""
        if not self.tiles:
            return
        tile_w = self._tile_size_px()
        cols = max(1, avail_width // tile_w)
        # avoid useless recompute if same cols
        if getattr(self, "_current_cols", None) == cols:
            return
        self._current_cols = cols
        pad = TILE_PAD
        # re-grid without recreating widgets
        for i, t in enumerate(self.tiles):
            r = i // cols
            c = i % cols
            t["frame"].grid(row=r, column=c, padx=pad, pady=pad, sticky="n")
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _clear_tiles(self):
        for t in self.tiles:
            t["frame"].destroy()
        self.tiles.clear()

    def _render_tiles_full(self):
        """Full rebuild (call when list size/order changes)."""
        self._clear_tiles()
        pad = TILE_PAD

        for idx, item in enumerate(self.items):
            frame = ttk.Frame(self.inner, padding=FRAME_PAD, borderwidth=1, relief="solid")
            # Position is finalized in _relayout_columns; grid with temp values first
            frame.grid(row=0, column=idx, padx=pad, pady=pad, sticky="n")

            ph = self._thumb_for(item["path"])
            img_lbl = ttk.Label(frame, image=ph)
            img_lbl.image = ph
            img_lbl.pack()

            name = os.path.basename(item["path"])
            ttk.Label(frame, text=name, width=24).pack(pady=(6,0))

            qrow = ttk.Frame(frame)
            qrow.pack(pady=(4,0))
            minus_btn = ttk.Button(qrow, text="−", width=2, command=lambda i=idx: self._adjust_qty_fast(i, -1))
            minus_btn.pack(side="left")
            qty_var = tk.StringVar(value=str(item["qty"]))
            qty_lbl = ttk.Label(qrow, textvariable=qty_var, width=3, anchor="center")
            qty_lbl.pack(side="left", padx=4)
            plus_btn = ttk.Button(qrow, text="+", width=2, command=lambda i=idx: self._adjust_qty_fast(i, +1))
            plus_btn.pack(side="left")

            self.tiles.append({
                "frame": frame,
                "qty_var": qty_var,
                "minus": minus_btn,
                "plus": plus_btn,
                "path": item["path"],
            })

        # Defer measuring width & reflow until Tk is idle (prevents one mega-row)
        self._force_reflow_after_idle()

    def _adjust_qty_fast(self, idx, delta):
        if 0 <= idx < len(self.items):
            new_q = int(self.items[idx]["qty"]) + delta
            if new_q <= 0:
                # remove the card completely
                self.items.pop(idx)
                self._render_tiles_full()
                self._force_reflow_after_idle()
            else:
                self.items[idx]["qty"] = new_q
                self.tiles[idx]["qty_var"].set(str(new_q))

    # ---- Clearing / PDF ----
    def clear_all(self):
        if not self.items:
            return
        if messagebox.askyesno("Clear", "Remove all images?"):
            self.items.clear()
            self.thumb_cache.clear()
            self._render_tiles_full()
            self._force_reflow_after_idle()
            self.status.set("Cleared list.")

    def make_pdf(self):
        if not self.items:
            messagebox.showerror("Error", "No images in the list.")
            return

        # Expand with quantities
        expanded = []
        for it in self.items:
            expanded.extend([it["path"]] * max(1, int(it["qty"])))

        out = filedialog.asksaveasfilename(
            title="Save PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")]
        )
        if not out:
            return

        self.status.set("Building pages…")
        self.root.update_idletasks()

        try:
            pages = make_pages_from_paths(expanded, DEFAULT_DPI, DEFAULT_CARD_W_MM, DEFAULT_CARD_H_MM)
            pages[0].save(out, save_all=True, append_images=pages[1:], resolution=DEFAULT_DPI)
            self.status.set(f"Saved {len(pages)} page(s) to: {out}")
            messagebox.showinfo("Done", f"Saved {len(pages)} page(s) to:\n{out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.status.set("Error.")

# ---- Entry point ----
def main():
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    try:
        root.tk.call("tk", "scaling", 1.15)  # mild HiDPI help
    except Exception:
        pass

    style = ttk.Style(root)
    try:
        style.theme_use('vista')
    except Exception:
        pass

    app = ProxyApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
