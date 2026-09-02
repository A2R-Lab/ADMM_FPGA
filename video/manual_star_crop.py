#!/usr/bin/env python3
"""Interactive crop and constraint-square picker for the constrained-star demo.

Usage:
    python3 manual_star_crop.py
    python3 manual_star_crop.py --time 20

Controls in the window:
    C  crop mode: click-drag a rectangle around the useful top-view area
    S  square mode: click-drag to move the square's top-left corner
    R  reload the frame at the time entered in the time box
    Save selection: writes star_crop_selection.json for build_accelmpc_video.py
"""
import argparse
import json
import subprocess
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

ROOT = Path(__file__).resolve().parent
ORIGINAL_SOURCE = ROOT / "constrainedStarTopView.MP4"
REDUCED_SOURCE = ROOT / "constrainedStarTopView_1080p.mp4"
SOURCE = ORIGINAL_SOURCE if ORIGINAL_SOURCE.exists() else REDUCED_SOURCE
CONFIG_OUT = ROOT / "star_crop_selection.json"
REFERENCE_W, REFERENCE_H = 1920, 1080
SRC_W, SRC_H = (2704, 1520) if SOURCE == ORIGINAL_SOURCE else (REFERENCE_W, REFERENCE_H)
DISPLAY_MAX_W, DISPLAY_MAX_H = 1200, 700

def extract_frame(seconds):
    tmp = Path(tempfile.mkstemp(suffix=".png")[1])
    try:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-ss", str(seconds),
            "-i", str(SOURCE), "-map", "0:v:0", "-frames:v", "1", str(tmp)
        ], check=True)
        return Image.open(tmp).convert("RGB")
    finally:
        tmp.unlink(missing_ok=True)

class Picker:
    def __init__(self, root, seconds):
        self.root = root
        self.seconds = seconds
        self.mode = "crop"
        self.original = None
        self.display_image = None
        self.photo = None
        self.scale = 1.0
        sx, sy = SRC_W / REFERENCE_W, SRC_H / REFERENCE_H
        self.crop = [round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate([249, 85, 1420, 888])]
        self.square = [round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate([249 + 1420 - 419 - 497, 85 + 888 - 199 - 497, 497, 497])]
        self.load_saved_selection()
        self.drag_start = None

        root.title("AccelMPC constrained-star crop / square picker")
        root.bind("c", lambda e: self.set_mode("crop"))
        root.bind("s", lambda e: self.set_mode("square"))
        root.bind("<Return>", lambda e: self.load_frame())

        bar = ttk.Frame(root, padding=8); bar.pack(fill="x")
        ttk.Label(bar, text="Frame time (s):").pack(side="left")
        self.time_var = tk.StringVar(value=str(seconds))
        ttk.Entry(bar, textvariable=self.time_var, width=8).pack(side="left", padx=5)
        ttk.Button(bar, text="Reload (R)", command=self.load_frame).pack(side="left", padx=4)
        self.mode_label = ttk.Label(bar, text="Mode: CROP")
        self.mode_label.pack(side="left", padx=18)
        ttk.Button(bar, text="Save selection", command=self.save).pack(side="right")
        ttk.Label(root, text="C: drag crop rectangle   S: drag square   R: reload frame   Esc: quit").pack()
        self.canvas = tk.Canvas(root, highlightthickness=0, bg="#09121f")
        self.canvas.pack(padx=8, pady=8)
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.motion)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.load_frame()

    def load_saved_selection(self):
        """Load source-coordinate selections and convert them to display space."""
        if not CONFIG_OUT.exists():
            return
        try:
            data = json.loads(CONFIG_OUT.read_text())
            x, y, w, h = [int(v) for v in data["top_crop"]]
            sx, sy, sw, sh = [int(v) for v in data["constraint_square"]]
            source_scale_x = SRC_W / REFERENCE_W
            source_scale_y = SRC_H / REFERENCE_H
            x, w = round(x * source_scale_x), round(w * source_scale_x)
            y, h = round(y * source_scale_y), round(h * source_scale_y)
            sx, sw = round(sx * source_scale_x), round(sw * source_scale_x)
            sy, sh = round(sy * source_scale_y), round(sh * source_scale_y)
            if not (w > 0 and h > 0 and sw > 0 and sh > 0):
                raise ValueError("selection dimensions must be positive")
            # Saved crop/square coordinates are before hflip+vflip. The canvas
            # shows the flipped image, so reflect both rectangles back.
            dx, dy = SRC_W - x - w, SRC_H - y - h
            self.crop = [dx, dy, w, h]
            display_sx = w - sx - sw
            display_sy = h - sy - sh
            self.square = [dx + display_sx, dy + display_sy, sw, sh]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"Ignoring invalid {CONFIG_OUT.name}: {exc}")

    def load_frame(self):
        try:
            self.seconds = float(self.time_var.get()) if hasattr(self, "time_var") else self.seconds
            self.original = ImageOps.flip(ImageOps.mirror(extract_frame(self.seconds)))
        except Exception as exc:
            print(f"Could not load frame: {exc}")
            return
        self.scale = min(DISPLAY_MAX_W / SRC_W, DISPLAY_MAX_H / SRC_H)
        self.display_image = self.original.resize((round(SRC_W*self.scale), round(SRC_H*self.scale)), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(self.display_image)
        self.canvas.config(width=self.display_image.width, height=self.display_image.height)
        self.canvas.delete("all"); self.canvas.create_image(0, 0, image=self.photo, anchor="nw", tags="image")
        self.draw()

    def set_mode(self, mode):
        self.mode = mode
        self.mode_label.config(text=f"Mode: {mode.upper()}")
        self.draw()

    def to_source(self, value):
        return max(0, min(int(round(value / self.scale)), SRC_W if value >= 0 else 0))

    def mouse_source(self, event):
        return (max(0, min(SRC_W, event.x / self.scale)), max(0, min(SRC_H, event.y / self.scale)))

    def press(self, event):
        self.drag_start = self.mouse_source(event)
        if self.mode == "square":
            # Clicking anywhere sets the square's top-left corner.
            self.square[0] = int(self.drag_start[0])
            self.square[1] = int(self.drag_start[1])
            self.clamp_square()
            self.draw()

    def motion(self, event):
        if not self.drag_start:
            return
        x, y = self.mouse_source(event)
        if self.mode == "crop":
            x0, y0 = self.drag_start
            self.crop = [int(min(x0, x)), int(min(y0, y)), int(abs(x-x0)), int(abs(y-y0))]
        else:
            self.square[0] = int(x); self.square[1] = int(y); self.clamp_square()
        self.draw()

    def release(self, event):
        self.motion(event); self.drag_start = None

    def clamp_square(self):
        cx, cy, cw, ch = self.crop
        self.square[2] = min(self.square[2], cw, ch)
        self.square[3] = self.square[2]
        self.square[0] = max(cx, min(cx+cw-self.square[2], self.square[0]))
        self.square[1] = max(cy, min(cy+ch-self.square[3], self.square[1]))

    def draw(self):
        self.canvas.delete("rect")
        x, y, w, h = [v*self.scale for v in self.crop]
        self.canvas.create_rectangle(x, y, x+w, y+h, outline="#36d17b", width=3, tags="rect")
        x, y, w, h = [v*self.scale for v in self.square]
        self.canvas.create_rectangle(x, y, x+w, y+h, outline="#f7b12c", width=4, tags="rect")
        self.canvas.create_text(12, 12, text="GREEN CROP   AMBER CONSTRAINT SQUARE", fill="white", anchor="nw", tags="rect")

    def save(self):
        # The displayed image is already hflip+vflip. Convert selections back
        # to source coordinates before crop/flip, matching the video builder.
        cx, cy, cw, ch = self.crop
        src_crop = [SRC_W-cx-cw, SRC_H-cy-ch, cw, ch]
        sx, sy, sw, sh = self.square
        crop_display_x, crop_display_y = sx-cx, sy-cy
        preflip_square = [cw-crop_display_x-sw, ch-crop_display_y-sh, sw, sh]
        sx, sy = REFERENCE_W / SRC_W, REFERENCE_H / SRC_H
        payload = {
            "_comments": {
                "top_crop": "[x, y, width, height] in original top-view source pixels; x/y are the top-left corner measured from the source image's left/top edges.",
                "constraint_square": "[x, y, width, height] in cropped top-view pixels before the video hflip/vflip; x/y are the square's top-left corner measured from the crop's left/top edges.",
                "preview_time": "Source-video time in seconds used for the displayed editing frame; it does not change video timing."
            },
            "top_crop": [round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate(src_crop)],
            "constraint_square": [round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate(preflip_square)],
            "preview_time": self.seconds,
        }
        CONFIG_OUT.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"Saved {CONFIG_OUT}")
        self.root.destroy()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--time", type=float, default=20.0, help="top-view frame time to display")
    args = parser.parse_args()
    root = tk.Tk()
    Picker(root, args.time)
    root.mainloop()

if __name__ == "__main__":
    main()
