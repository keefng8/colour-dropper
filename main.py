"""Colour Dropper - read the colour of any pixel on screen, from anywhere.

This is the one thing a web page cannot do. A browser can only see its own
canvas; the EyeDropper API is Chromium-only and still confined to the
browser. Reading the colour of a pixel in Photoshop, in a game, in a PDF, or
on a video frame needs to talk to the desktop, which means a native window.

Everything here is ctypes against gdi32 and user32. No pip install, no
screenshot library, and nothing is ever captured or stored beyond the single
pixel values you ask for.

Standard library only.
"""
import ctypes
import tkinter as tk

import mavis_ui as ui

FEATURE = "colour-dropper"
ZOOM_CELLS = 15          # odd, so there is a true centre pixel
CELL_PX = 12
POLL_MS = 60

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# Without this, a display scaled above 100% reports coordinates in virtual
# pixels while GetPixel reads physical ones, so the colour comes from the
# wrong place - and it is wrong by more the further right you go, which looks
# like a mysterious offset rather than a scaling bug.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def cursor_position():
    point = POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def pixel(dc, x, y):
    """One pixel as (r, g, b).

    GetPixel returns a COLORREF, which is 0x00BBGGRR - blue in the HIGH byte,
    not the low one. Reading it as RGB silently swaps red and blue, which is
    subtle enough to survive testing on greys.
    """
    value = gdi32.GetPixel(dc, x, y)
    if value == 0xFFFFFFFF:          # CLR_INVALID - outside any display
        return None
    return (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)


def hexof(rgb):
    return "#%02X%02X%02X" % rgb


def to_hsl(rgb):
    r, g, b = [v / 255 for v in rgb]
    high, low = max(r, g, b), min(r, g, b)
    lightness = (high + low) / 2
    if high == low:
        return 0, 0, round(lightness * 100)
    delta = high - low
    sat = delta / (2 - high - low) if lightness > 0.5 else delta / (high + low)
    if high == r:
        hue = ((g - b) / delta) % 6
    elif high == g:
        hue = (b - r) / delta + 2
    else:
        hue = (r - g) / delta + 4
    return round(hue * 60), round(sat * 100), round(lightness * 100)


def luminance(rgb):
    """WCAG relative luminance. The same formula colour-lab uses, so the two
    features cannot disagree about whether text is readable."""
    channels = []
    for value in rgb:
        c = value / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    high, low = max(la, lb), min(la, lb)
    return (high + 0.05) / (low + 0.05)


class Dropper(ui.MavisWindow):
    def __init__(self):
        super().__init__(FEATURE, "Colour Dropper", width=420, height=560,
                         topmost=True)
        self.dc = user32.GetDC(0)
        self.picking = False
        self.current = (0, 0, 0)
        self.history = [tuple(c) for c in ui.load_state(FEATURE, {}).get("history", [])]
        self._was_down = False

        self._build()
        self._tick()

    def _build(self):
        # --- magnifier ---
        size = ZOOM_CELLS * CELL_PX
        wrap = tk.Frame(self.content, bg=ui.INK)
        wrap.pack(pady=(14, 6))
        self.zoom = tk.Canvas(wrap, width=size, height=size, bg=ui.PANEL,
                              highlightthickness=1, highlightbackground=ui.LINE)
        self.zoom.pack()
        self._cells = [[self.zoom.create_rectangle(
            c * CELL_PX, r * CELL_PX, (c + 1) * CELL_PX, (r + 1) * CELL_PX,
            outline="", width=0) for c in range(ZOOM_CELLS)]
            for r in range(ZOOM_CELLS)]
        mid = ZOOM_CELLS // 2
        self.crosshair = self.zoom.create_rectangle(
            mid * CELL_PX, mid * CELL_PX, (mid + 1) * CELL_PX, (mid + 1) * CELL_PX,
            outline=ui.GLOW, width=2)

        # --- readout ---
        self.swatch = tk.Frame(self.content, bg="#000000", height=54)
        self.swatch.pack(fill="x", padx=16, pady=(10, 0))

        self.hexlabel = tk.Label(self.content, text="#000000", bg=ui.INK,
                                 fg=ui.TEXT, font=("Consolas", 20, "bold"))
        self.hexlabel.pack(pady=(10, 0))
        self.detail = tk.Label(self.content, text="", bg=ui.INK, fg=ui.DIM,
                               font=("Consolas", 9))
        self.detail.pack()

        row = tk.Frame(self.content, bg=ui.INK)
        row.pack(pady=12)
        self.pickbtn = ui.button(row, "Pick from screen", self.toggle_pick, accent=True)
        self.pickbtn.pack(side="left", padx=4)
        ui.button(row, "Copy", self.copy_current).pack(side="left", padx=4)

        self.status = tk.Label(self.content, text="", bg=ui.INK, fg=ui.DIM,
                               font=("Segoe UI", 8), wraplength=360, justify="center")
        self.status.pack(padx=16)

        ui.heading(self.content, "PICKED").pack(fill="x", padx=16, pady=(14, 4))
        self.strip = tk.Frame(self.content, bg=ui.INK)
        self.strip.pack(fill="x", padx=16)

        self.contrast = tk.Label(self.content, text="", bg=ui.INK, fg=ui.DIM,
                                 font=("Segoe UI", 8), wraplength=360,
                                 justify="left")
        self.contrast.pack(fill="x", padx=16, pady=(10, 0))

        self._render_history()
        self._explain()

    def _explain(self):
        self.status.configure(text=(
            "Press Pick, then click anywhere on screen. Escape cancels.\n"
            "Nothing is captured or saved except the colours you pick."))

    # ------------------------------------------------------------------ loop
    def _tick(self):
        x, y = cursor_position()
        centre = pixel(self.dc, x, y)
        if centre:
            self.current = centre
            self._paint_zoom(x, y)
            self._paint_readout(centre, x, y)

        if self.picking:
            # Poll the physical button rather than binding <Button-1>: a Tk
            # binding only fires over our own window, and the whole point is
            # to pick a colour from somebody else's.
            down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
            if down and not self._was_down:
                self._capture(centre)
            self._was_down = down

        self.after(POLL_MS, self._tick)

    def _paint_zoom(self, cx, cy):
        half = ZOOM_CELLS // 2
        for row in range(ZOOM_CELLS):
            for col in range(ZOOM_CELLS):
                rgb = pixel(self.dc, cx - half + col, cy - half + row)
                self.zoom.itemconfigure(self._cells[row][col],
                                        fill=hexof(rgb) if rgb else ui.PANEL)
        self.zoom.tag_raise(self.crosshair)

    def _paint_readout(self, rgb, x, y):
        code = hexof(rgb)
        self.swatch.configure(bg=code)
        self.hexlabel.configure(text=code)
        h, s, light = to_hsl(rgb)
        self.detail.configure(
            text="rgb(%d, %d, %d)    hsl(%d, %d%%, %d%%)    at %d,%d"
                 % (rgb[0], rgb[1], rgb[2], h, s, light, x, y))
        # Keep the hex readable against the colour it is describing.
        self.hexlabel.configure(fg=ui.TEXT if luminance(rgb) < 0.4 else ui.TEXT)

    # ------------------------------------------------------------------ pick
    def toggle_pick(self):
        self.picking = not self.picking
        if self.picking:
            # Prime the edge detector so the click that pressed this button
            # is not itself read as a pick.
            self._was_down = True
            self.pickbtn.configure(text="Click anywhere…", bg=ui.WARN)
            self.status.configure(text="Move the pointer and click. Escape cancels.")
        else:
            self.pickbtn.configure(text="Pick from screen", bg=ui.GLOW)
            self._explain()

    def _capture(self, rgb):
        if not rgb:
            return
        self.history = [c for c in self.history if c != rgb]
        self.history.insert(0, rgb)
        del self.history[10:]
        self.copy_current(rgb)
        self._render_history()
        self.toggle_pick()

    def copy_current(self, rgb=None):
        code = hexof(rgb or self.current)
        self.clipboard_clear()
        self.clipboard_append(code)
        self.flash("copied " + code)

    def _render_history(self):
        for child in self.strip.winfo_children():
            child.destroy()
        if not self.history:
            tk.Label(self.strip, text="Nothing picked yet.", bg=ui.INK,
                     fg=ui.LINE, font=("Segoe UI", 8)).pack(anchor="w")
            self.contrast.configure(text="")
            return

        for rgb in self.history:
            chip = tk.Frame(self.strip, bg=hexof(rgb), width=30, height=30,
                            cursor="hand2", highlightthickness=1,
                            highlightbackground=ui.LINE)
            chip.pack(side="left", padx=(0, 5))
            chip.pack_propagate(False)
            chip.bind("<Button-1>", lambda e, c=rgb: self.copy_current(c))

        if len(self.history) >= 2:
            a, b = self.history[0], self.history[1]
            ratio = contrast(a, b)
            if ratio >= 7:
                verdict, colour = "passes AAA for body text", ui.GOOD
            elif ratio >= 4.5:
                verdict, colour = "passes AA for body text", ui.GOOD
            elif ratio >= 3:
                verdict, colour = "large text only", ui.WARN
            else:
                verdict, colour = "fails - not readable", ui.BAD
            self.contrast.configure(
                fg=colour,
                text="Last two: %s on %s is %.2f to 1 — %s."
                     % (hexof(a), hexof(b), ratio, verdict))

    def on_close(self):
        try:
            user32.ReleaseDC(0, self.dc)
        except Exception:
            pass
        return {"history": [list(c) for c in self.history]}


if __name__ == "__main__":
    Dropper().mainloop()
