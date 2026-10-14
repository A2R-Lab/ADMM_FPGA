#!/usr/bin/env python3
"""Build the AccelMPC RA-L supplementary/demo video.

The source media are never modified.  Pillow creates reusable cards/overlays;
FFmpeg performs all scaling, timing, compositing, encoding and concatenation.
Edit the CONFIG block below to revise the cut.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys
from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "generated_accelmpc_assets"
OUT = ROOT / "AccelMPC_supplementary_demo.mp4"
NOMINAL_OUT = ROOT / "AccelMPC_nominal_figure8_iteration.mp4"
STAR_OUT = ROOT / "AccelMPC_constrained_star_iteration.mp4"
TOP_TRAIL_RAW = ROOT / "topview_motion_trail_raw.png"
TOP_TRAIL_CROPPED = ROOT / "topview_motion_trail_cropped_flipped.png"
MANUAL_STAR_CONFIG = ROOT / "star_crop_selection.json"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

# ------------------------------- CONFIG ---------------------------------
W, H, FPS = 1920, 1080, 30
BG = (9, 18, 31, 255)
AMBER = (247, 177, 44, 255)
WHITE = (245, 247, 250, 255)
MUTED = (174, 187, 202, 255)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

TIMINGS = {
    "cover": 5.0,
    "hardware": 8.0,
    "nominal_card": 3.0,
    "nominal": 16.0,
    "star_card": 3.0,
    "star": 23.0,
    "dynamic_card": 3.0,
    "dynamic": 38.0,
    "results": 7.0,
}

STAR_TOP_ORIGINAL = ROOT / "constrainedStarTopView.MP4"
STAR_TOP_REDUCED = ROOT / "constrainedStarTopView_1080p.mp4"
STAR_TOP_SOURCE = STAR_TOP_ORIGINAL if STAR_TOP_ORIGINAL.exists() else STAR_TOP_REDUCED
STAR_REFERENCE_SIZE = (1920, 1080)
STAR_SOURCE_SIZE = (2704, 1520) if STAR_TOP_SOURCE == STAR_TOP_ORIGINAL else STAR_REFERENCE_SIZE

SOURCES = {
    "drone": ROOT / "drone.jpg",
    "board_front": ROOT / "board_front_crop.png",
    "board_back": ROOT / "board_back_crop.png",
    "figure8": ROOT / "figure8.gif",
    "figure8_top": ROOT / "figure8_topview.gif",
    "figure8_plot": ROOT / "figure8.jpg",
    "star_plot": ROOT / "constrainedStar.png",
    "star_lateral": ROOT / "constrainedStarLateralView.MOV",
    "star_top": STAR_TOP_SOURCE,
    "dynamic": ROOT / "dynObstacleAvoidance.mp4",
}

# Star-camera alignment and manual crop/marker controls. Coordinates are
# source-pixel coordinates. The top-view square is relative to the cropped
# top-view image, so it remains attached when the crop is changed.
STAR_LATERAL_START = 13.0
STAR_TOP_START = 20.5
STAR_DURATION = TIMINGS["star"]
STAR_LATERAL_CROP = (80, 180, 1120, 500)      # x, y, width, height; crop starts near curtain bottom
STAR_TOP_CROP = (249, 85, 1420, 888)        # reference 1920x1080 coordinates
STAR_CONSTRAINT_SQUARE = (419, 199, 497, 497) # reference cropped-image coordinates
STAR_SQUARE_COLOR = "#f7b12c"
STAR_SQUARE_ALPHA = 0.20
STAR_SQUARE_WIDTH = 5
STAR_PANEL_GAP = 12
DYNAMIC_START = 0.0

def font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)

def load_manual_star_config():
    """Use selections saved by manual_star_crop.py when present."""
    global STAR_TOP_CROP, STAR_CONSTRAINT_SQUARE
    sx = STAR_SOURCE_SIZE[0] / STAR_REFERENCE_SIZE[0]
    sy = STAR_SOURCE_SIZE[1] / STAR_REFERENCE_SIZE[1]
    STAR_TOP_CROP = tuple(round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate(STAR_TOP_CROP))
    STAR_CONSTRAINT_SQUARE = tuple(round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate(STAR_CONSTRAINT_SQUARE))
    if MANUAL_STAR_CONFIG.exists():
        data = json.loads(MANUAL_STAR_CONFIG.read_text())
        STAR_TOP_CROP = tuple(round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate(data["top_crop"]))
        STAR_CONSTRAINT_SQUARE = tuple(round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate(data["constraint_square"]))

def text(draw, xy, value, size, fill=WHITE, bold=False, anchor=None):
    draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)

def card(path, headline, subline=None, accent=True):
    im = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((120, 170, 132, 910), fill=AMBER if accent else MUTED)
    text(d, (190, 430), headline, 72, WHITE, True)
    if subline:
        text(d, (194, 550), subline, 32, WHITE, True)
    d.line((190, 640, 760, 640), fill=(48, 67, 88, 255), width=2)
    im.save(path)

def cover(path):
    src = Image.open(SOURCES["drone"]).convert("RGB")
    # cover crop: preserve the drone and deck while filling 16:9.
    scale = max(W / src.width, H / src.height)
    src = src.resize((round(src.width * scale), round(src.height * scale)), Image.Resampling.LANCZOS)
    left, top = (src.width - W) // 2, (src.height - H) // 2
    im = src.crop((left, top, left + W, top + H)).convert("RGBA")
    shade = Image.new("RGBA", (W, H), (4, 10, 18, 110))
    im.alpha_composite(shade)
    d = ImageDraw.Draw(im)
    d.rectangle((110, 120, 122, 590), fill=AMBER)
    text(d, (175, 270), "AccelMPC", 92, WHITE, True)
    text(d, (180, 400), "High-Rate, Low-Power FPGA-Accelerated MPC", 36, WHITE)
    text(d, (180, 452), "for Tiny Drones", 36, WHITE)
    im.save(path)

def hardware(path):
    left = Image.open(SOURCES["drone"]).convert("RGB")
    front = Image.open(SOURCES["board_front"]).convert("RGB")
    back = Image.open(SOURCES["board_back"]).convert("RGB")
    def fit(im, box):
        scale = min(box[0] / im.width, box[1] / im.height)
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", box, (22, 32, 46))
        canvas.paste(im, ((box[0]-im.width)//2, (box[1]-im.height)//2))
        return canvas
    im = Image.new("RGBA", (W, H), BG)
    im.alpha_composite(fit(left, (1100, 820)).convert("RGBA"), (70, 130))
    im.alpha_composite(fit(front, (330, 820)).convert("RGBA"), (1240, 130))
    im.alpha_composite(fit(back, (330, 820)).convert("RGBA"), (1590, 130))
    d = ImageDraw.Draw(im)
    text(d, (1260, 150), "PCB front", 24, WHITE, True)
    text(d, (1610, 150), "PCB back", 24, WHITE, True)
    d.rectangle((80, 890, 1850, 894), fill=AMBER)
    text(d, (90, 930), "Custom 6 g FPGA accelerator", 38, WHITE, True)
    text(d, (90, 986), "AMD Artix-7 100T · Fully onboard MPC", 28, WHITE, True)
    im.save(path)

def overlay(path, lines, top=70, right=False):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    widths = [d.textbbox((0, 0), s, font=font(26, True))[2] for s in lines]
    bw = max(widths) + 44
    bh = 38 + len(lines) * 36
    x = W - bw - 60 if right else 60
    d.rounded_rectangle((x, top, x+bw, top+bh), radius=12, fill=(7, 16, 28, 190), outline=(93, 112, 132, 180), width=2)
    for i, line in enumerate(lines):
        text(d, (x+22, top+18+i*36), line, 26, WHITE, True)
    im.save(path)

def run(args):
    subprocess.run(args, check=True)

def still_segment(image, duration, out):
    run([FFMPEG, "-y", "-loop", "1", "-i", str(image), "-t", str(duration), "-r", str(FPS),
         "-vf", "format=yuv420p", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])

def video_segment(source, start, duration, out, vf=None, overlay_img=None, loop=False):
    args = [FFMPEG, "-y"]
    if loop:
        args += ["-stream_loop", "-1"]
    args += ["-ss", str(start), "-i", str(source)]
    if overlay_img:
        args += ["-loop", "1", "-i", str(overlay_img)]
        filter_arg = f"[0:v]{vf or 'null'}[base];[base][1:v]overlay=0:0:format=auto"
        args += ["-filter_complex", filter_arg]
    else:
        args += ["-vf", vf or "null"]
    args += ["-t", str(duration), "-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(out)]
    run(args)

def render_star_base(out, duration):
    """Render the aligned/cropped star views on a padded 1920x1080 canvas."""
    lx, ly, lw, lh = STAR_LATERAL_CROP
    tx, ty, tw, th = STAR_TOP_CROP
    sx, sy, sw, sh = STAR_CONSTRAINT_SQUARE
    mirrored_sx = tw - sx - sw
    # The views are stacked in 1920x500 panels. force_original_aspect_ratio=
    # decrease preserves each crop's aspect ratio; pad supplies the background.
    video_w, video_h, plot_w = 1240, 480, 680
    vf = (
        f"[1:v]crop={tw}:{th}:{tx}:{ty},hflip,vflip,drawbox=x={mirrored_sx}:y={th - sy - sh}:w={sw}:h={sh}:"
        f"color={STAR_SQUARE_COLOR}@{STAR_SQUARE_ALPHA}:t={STAR_SQUARE_WIDTH},"
        f"scale={video_w}:{video_h}:force_original_aspect_ratio=decrease,"
        f"pad={video_w}:{video_h}:(ow-iw)/2:(oh-ih)/2:color=#09121f[top];"
        f"[0:v]crop={lw}:{lh}:{lx}:{ly},scale={video_w}:{video_h}:force_original_aspect_ratio=decrease,"
        f"pad={video_w}:{video_h}:(ow-iw)/2:(oh-ih)/2:color=#09121f[bottom];"
        f"color=c=#09121f:s={video_w}x{STAR_PANEL_GAP}:r={FPS}[gap];"
        f"[top][gap][bottom]vstack=inputs=3,pad={video_w}:1080:(ow-iw)/2:(oh-ih)/2:color=#09121f[video];"
        f"[2:v]scale={plot_w}:1080:force_original_aspect_ratio=decrease,"
        f"pad={plot_w}:1080:(ow-iw)/2:(oh-ih)/2:color=#09121f[plot];"
        f"[video][plot]hstack=inputs=2,setsar=1"
    )
    run([FFMPEG, "-y", "-ss", str(STAR_LATERAL_START), "-i", str(SOURCES["star_lateral"]),
         "-ss", str(STAR_TOP_START), "-i", str(SOURCES["star_top"]), "-loop", "1", "-i", str(SOURCES["star_plot"]), "-t", str(duration),
         "-an", "-filter_complex", vf, "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", "-frames:v", str(round(duration * FPS)), str(out)])

def motion_trail(source, out, vf=None):
    """Accumulate all decoded frames with a per-pixel lighten composite."""
    args = [FFMPEG, "-loglevel", "error", "-i", str(source), "-map", "0:v:0"]
    if vf:
        args += ["-vf", vf]
    args += ["-f", "image2pipe", "-vcodec", "png", "-"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    composite = None
    try:
        while True:
            try:
                frame = Image.open(proc.stdout)
                frame.load()
                frame = frame.convert("RGB")
            except Exception:
                break
            composite = frame if composite is None else ImageChops.lighter(composite, frame)
    finally:
        proc.stdout.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.read().decode(errors="replace"))
    if composite is None:
        raise RuntimeError(f"No frames decoded from {source}")
    composite.save(out)
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")

def main():
    load_manual_star_config()
    WORK.mkdir(exist_ok=True)
    cover(WORK / "cover.png")
    hardware(WORK / "hardware.png")
    card(WORK / "nominal_card.png", "Nominal trajectory tracking", "FPGA MPC preserves the baseline closed-loop behavior")
    card(WORK / "star_card.png", "1 kHz constrained MPC", "The reference leaves the admissible region; the drone does not.")
    card(WORK / "dynamic_card.png", "Dynamic obstacle avoidance", "Runtime constraints updated online while MPC continues at 1 kHz")
    card(WORK / "results.png", "AccelMPC", "1 kHz onboard constrained MPC · 35 g drone", accent=True)
    # Add the headline metrics to the final card, keeping it intentionally sparse.
    im = Image.open(WORK / "results.png").convert("RGBA"); d = ImageDraw.Draw(im)
    text(d, (194, 690), "Up to 15.6× faster", 34, WHITE, True)
    text(d, (194, 745), "Up to 195.4× lower energy-delay product", 34, WHITE, True)
    text(d, (194, 800), "Scales beyond 20,000 optimization variables", 34, WHITE, True)
    im.save(WORK / "results.png")
    overlay(WORK / "nominal_ov.png", ["Nominal figure-eight tracking"], right=True)
    overlay(WORK / "star_ov.png", ["Onboard MPC: 1 kHz", "H = 27, k = 9"], right=True)
    overlay(WORK / "dynamic_ov.png", ["Obstacle tracking: 120 Hz", "Onboard MPC: 1 kHz"], right=False)

    if "--top-trail" in sys.argv:
        tx, ty, tw, th = STAR_TOP_CROP
        top_vf = f"crop={tw}:{th}:{tx}:{ty},hflip,vflip"
        motion_trail(SOURCES["star_top"], TOP_TRAIL_RAW)
        motion_trail(SOURCES["star_top"], TOP_TRAIL_CROPPED, top_vf)
        return

    # Fast iteration mode: render only the nominal chapter card and the two
    # figure-eight GIFs.  Their native proportions are retained: the lateral
    # view fills the upper 550 px; the top view is centered in the lower 530 px.
    if "--nominal-only" in sys.argv:
        card_seg = WORK / "iteration_nominal_card.mp4"
        still_segment(WORK / "nominal_card.png", TIMINGS["nominal_card"], card_seg)
        nominal_vf = "[0:v]scale=1920:550,setsar=1[top];[1:v]scale=1240:530:force_original_aspect_ratio=decrease,setsar=1[small];[small]pad=1240:530:(ow-iw)/2:(oh-ih)/2:color=#09121f[bottom_left];[2:v]scale=680:530:force_original_aspect_ratio=decrease,pad=680:530:(ow-iw)/2:(oh-ih)/2:color=#09121f[bottom_right];[bottom_left][bottom_right]hstack=inputs=2[bottom];[top][bottom]vstack=inputs=2,setsar=1"
        nominal_seg = WORK / "iteration_nominal.mp4"
        run([FFMPEG, "-y", "-stream_loop", "-1", "-i", str(SOURCES["figure8"]), "-stream_loop", "-1", "-i", str(SOURCES["figure8_top"]), "-loop", "1", "-i", str(SOURCES["figure8_plot"]), "-t", str(TIMINGS["nominal"]), "-an", "-filter_complex", nominal_vf, "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(nominal_seg)])
        concat = WORK / "iteration_nominal_concat.txt"
        concat.write_text(f"file '{card_seg.as_posix()}'\nfile '{nominal_seg.as_posix()}'\n")
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(NOMINAL_OUT)])
        print(f"Wrote {NOMINAL_OUT} ({NOMINAL_OUT.stat().st_size/1e6:.1f} MB)")
        return

    # Fast iteration mode for the constrained-star experiment only.
    if "--star-only" in sys.argv:
        card_seg = WORK / "iteration_star_card.mp4"
        still_segment(WORK / "star_card.png", TIMINGS["star_card"], card_seg)
        star_base = WORK / "iteration_star.mp4"
        render_star_base(star_base, STAR_DURATION)
        star_seg = WORK / "iteration_star_overlay.mp4"
        video_segment(star_base, 0, STAR_DURATION, star_seg, "scale=1920:1080,setsar=1", WORK / "star_ov.png")
        concat = WORK / "iteration_star_concat.txt"
        concat.write_text(f"file '{card_seg.as_posix()}'\nfile '{star_seg.as_posix()}'\n")
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-an",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(STAR_OUT)])
        print(f"Wrote {STAR_OUT} ({STAR_OUT.stat().st_size/1e6:.1f} MB)")
        return

    segs = []
    def add(name, duration, fn):
        out = WORK / f"{len(segs):02d}_{name}.mp4"; fn(out); segs.append(out)
    add("cover", TIMINGS["cover"], lambda o: still_segment(WORK / "cover.png", TIMINGS["cover"], o))
    add("hardware", TIMINGS["hardware"], lambda o: still_segment(WORK / "hardware.png", TIMINGS["hardware"], o))
    add("nominal_card", TIMINGS["nominal_card"], lambda o: still_segment(WORK / "nominal_card.png", TIMINGS["nominal_card"], o))
    nominal_vf = "[0:v]scale=1920:550,setsar=1[top];[1:v]scale=1240:530:force_original_aspect_ratio=decrease,setsar=1[small];[small]pad=1240:530:(ow-iw)/2:(oh-ih)/2:color=#09121f[bottom_left];[2:v]scale=680:530:force_original_aspect_ratio=decrease,pad=680:530:(ow-iw)/2:(oh-ih)/2:color=#09121f[bottom_right];[bottom_left][bottom_right]hstack=inputs=2[bottom];[top][bottom]vstack=inputs=2,setsar=1"
    nominal_base = WORK / f"{len(segs):02d}_nominal_base.mp4"
    run([FFMPEG, "-y", "-stream_loop", "-1", "-i", str(SOURCES["figure8"]), "-stream_loop", "-1", "-i", str(SOURCES["figure8_top"]), "-loop", "1", "-i", str(SOURCES["figure8_plot"]), "-t", str(TIMINGS["nominal"]), "-an", "-filter_complex", nominal_vf, "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(nominal_base)])
    nominal_out = WORK / f"{len(segs):02d}_nominal.mp4"
    video_segment(nominal_base, 0, TIMINGS["nominal"], nominal_out, "scale=1920:1080,setsar=1")
    segs.append(nominal_out)
    add("star_card", TIMINGS["star_card"], lambda o: still_segment(WORK / "star_card.png", TIMINGS["star_card"], o))
    star_base = WORK / f"{len(segs):02d}_star_base.mp4"
    render_star_base(star_base, STAR_DURATION)
    star_out = WORK / f"{len(segs):02d}_star.mp4"
    video_segment(star_base, 0, STAR_DURATION, star_out, "scale=1920:1080", WORK / "star_ov.png"); segs.append(star_out)
    add("dynamic_card", TIMINGS["dynamic_card"], lambda o: still_segment(WORK / "dynamic_card.png", TIMINGS["dynamic_card"], o))
    add("dynamic", TIMINGS["dynamic"], lambda o: video_segment(SOURCES["dynamic"], DYNAMIC_START, TIMINGS["dynamic"], o, "scale=1920:720:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#09121f", WORK / "dynamic_ov.png"))
    add("results", TIMINGS["results"], lambda o: still_segment(WORK / "results.png", TIMINGS["results"], o))

    concat = WORK / "concat.txt"
    concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in segs) + "\n")
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT)])
    print(f"Wrote {OUT} ({OUT.stat().st_size/1e6:.1f} MB)")

if __name__ == "__main__":
    main()
