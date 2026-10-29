#!/usr/bin/env python3
"""Build the AccelMPC RA-L supplementary/demo video.

The source media are never modified.  Pillow creates reusable cards/overlays;
FFmpeg performs all scaling, timing, compositing, encoding and concatenation.
Edit the CONFIG block below to configure the video.
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
    "cover": 7, "system": 12, "hardware": 6,
    "nominal": 10, "star": 26, "dynamic": 38, "closing": 16.5,
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
    "star_lateral": ROOT / "constrainedStarLateralView.MOV",
    "star_top": STAR_TOP_SOURCE,
    "dynamic": ROOT / "dynObstacleAvoidance.mp4",
}

# Star-camera alignment and manual crop/marker controls. Coordinates are
# source-pixel coordinates. The top-view square is relative to the cropped
# top-view image, so it remains attached when the crop is changed.
STAR_LATERAL_START = 13.0
STAR_TOP_START = 20.5
STAR_LATERAL_CROP = (80, 180, 1120, 500)      # x, y, width, height; crop starts near curtain bottom
STAR_TOP_CROP = (249, 85, 1420, 888)        # reference 1920x1080 coordinates
STAR_CONSTRAINT_SQUARE = (419, 199, 497, 497) # reference cropped-image coordinates
STAR_SAFE_DURATION = 26.0
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

def cover(path):
    src = Image.open(SOURCES["drone"]).convert("RGB")
    # cover crop: preserve the drone and deck while filling 16:9.
    scale = max(W / src.width, H / src.height)
    src = src.resize((round(src.width * scale), round(src.height * scale)), Image.Resampling.LANCZOS)
    left, top = (src.width - W) // 2, (src.height - H) // 2
    im = src.crop((left, top, left + W, top + H)).convert("RGBA")
    shade = Image.new("RGBA", (W, H), (4, 10, 18, 110))
    im.alpha_composite(shade)
    im.save(WORK/'cover_background.png')
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((110, 120, 122, 590), fill=AMBER)
    text(d, (175, 270), "AccelMPC", 92, WHITE, True)
    text(d, (180, 400), "High-Rate, Low-Power FPGA-Accelerated MPC", 36, WHITE)
    text(d, (180, 452), "for Tiny Drones", 36, WHITE)
    im.save(path)

def render_cover(out, duration):
    frames = round(duration * FPS)
    # Enlarge the photograph by 8% over the slide, keeping the title fixed.
    # Supersampling avoids visible pixel stepping during the slow zoom.
    vf = (f"[0:v]scale={W*2}:{H*2},"
          f"zoompan=z='1+0.08*min(on/{max(frames-1, 1)},1)':d={frames}:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
          "format=rgba[photo];[photo][1:v]overlay=0:0:format=auto,format=yuv420p[out]")
    run([FFMPEG, '-y', '-loglevel', 'error', '-loop', '1', '-i', str(WORK/'cover_background.png'),
         '-loop', '1', '-i', str(WORK/'cover.png'), '-filter_complex', vf,
         '-map', '[out]', '-t', str(duration), '-an', '-c:v', 'libx264', '-preset', 'medium',
         '-crf', '18', '-pix_fmt', 'yuv420p', str(out)])


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

def run(args):
    print("Rendering:", args[-1], flush=True)
    subprocess.run(args, check=True)

def still_segment(image, duration, out):
    run([FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-i", str(image), "-t", str(duration), "-r", str(FPS),
         "-vf", "format=yuv420p", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])

def video_segment(source, start, duration, out, vf=None, overlay_img=None, loop=False):
    args = [FFMPEG, "-y", "-loglevel", "error"]
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


# The video uses fixed, readable panels. Plots summarize recorded runs;
# they are deliberately not animated against footage with unverified log sync.
BLUE = (83, 197, 244, 255)
GREEN = (112, 211, 159, 255)

def lines(draw, x, y, values, size=32, color=WHITE, step=48):
    for i, value in enumerate(values):
        text(draw, (x, y + i * step), value, size, color)

def explanation(path, title, values):
    im = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(im)
    text(d, (100, 100), title, 58, AMBER, True)
    lines(d, 105, 285, values, 37, step=85)
    im.save(path)

def system_card(path):
    from PIL import ImageOps
    im = Image.new('RGBA', (W,H), BG); d = ImageDraw.Draw(im)
    text(d,(90,55),'How the flight experiment works',58,WHITE,True)
    text(d,(90,155),'External sensing',32,AMBER,True)
    text(d,(710,155),'Onboard the drone',32,BLUE,True)
    d.rounded_rectangle((680,205,1830,855),24,outline=BLUE,width=3)
    arena=WORK/'system_arena.jpg'
    run([FFMPEG,'-y','-loglevel','error','-ss','3','-i',str(SOURCES['star_lateral']),'-frames:v','1',str(arena)])
    for source,box in [(arena,(110,225,480,415)),(SOURCES['drone'],(735,225,1115,415)),(SOURCES['board_front'],(1460,225,1740,415))]:
        photo=ImageOps.contain(Image.open(source).convert('RGB'),(box[2]-box[0],box[3]-box[1]))
        im.paste(photo,(box[0]+(box[2]-box[0]-photo.width)//2,box[1]+(box[3]-box[1]-photo.height)//2))
    boxes=[(90,435,500,610),(710,435,1140,610),(1450,435,1790,610),(710,720,1140,815)]
    labels=[('Motion capture','Drone / obstacle poses'),('Microcontroller','State estimation + actuation'),('FPGA accelerator','MPC optimization'),('Drone','Motors → motion')]
    for box,label in zip(boxes,labels):
        d.rounded_rectangle(box,18,fill=(25,42,60),outline=MUTED,width=2)
        cx=(box[0]+box[2])/2; cy=(box[1]+box[3])/2
        text(d,(cx,cy-34),label[0],29,WHITE,True,anchor='mt')
        text(d,(cx,cy+10),label[1],25,anchor='mt')
    def arrow(points,color=AMBER):
        import math
        d.line(points,fill=color,width=5,joint='curve')
        x,y=points[-1]; px,py=points[-2]; a=math.atan2(y-py,x-px)
        d.polygon([(x,y),(x-17*math.cos(a)+9*math.sin(a),y-17*math.sin(a)-9*math.cos(a)),(x-17*math.cos(a)-9*math.sin(a),y-17*math.sin(a)+9*math.cos(a))],fill=color)
    arrow([(510,515),(700,515)])
    text(d,(605,470),'Poses',25,AMBER,anchor='mt')
    arrow([(1150,480),(1440,480)])
    text(d,(1295,425),'State / constraints',24,AMBER,anchor='mt')
    arrow([(1440,570),(1150,570)],GREEN)
    text(d,(1295,590),'Optimized trajectory',23,GREEN,anchor='mt')
    text(d,(1295,620),'/ control plan',23,GREEN,anchor='mt')
    arrow([(925,620),(925,710)])
    text(d,(950,662),'Motor commands',26,AMBER,anchor='lm')
    arrow([(700,770),(295,770),(295,620)],GREEN)
    text(d,(490,790),'Drone motion',27,GREEN,anchor='mt')
    lines(d,95,900,['MPC predicts motion and optimizes motor commands.','Obstacle motion updates the position limits used by the optimizer.'],32,step=55)
    im.save(path)

def trajectory_panel(path, curves, limits, bounds=None):
    """Raster plot with metre axes and consistent colors, sized for video."""
    im = Image.new("RGBA", (800, 800), BG); d = ImageDraw.Draw(im)
    lo, hi = limits
    def xy(p):
        return (135+(float(p[0])-lo)/(hi-lo)*570, 680-(float(p[1])-lo)/(hi-lo)*570)
    if bounds:
        a, b = bounds
        d.rectangle((*xy((a,b)), *xy((b,a))), fill=(35,65,58), outline=GREEN, width=3)
    for j in range(5):
        v = lo+(hi-lo)*j/4
        x,y = xy((v,v))
        d.line((x,110,x,680), fill=(54,67,79), width=1)
        d.line((135,y,705,y), fill=(54,67,79), width=1)
        text(d,(x,700),f"{v:.1f}",23,anchor="mt")
        text(d,(95,y),f"{v:.1f}",23,anchor="rm")
    text(d,(420,755),"x [m]",27,anchor="mt")
    text(d,(20,65),"y [m]",27)
    for i,(label, points, color) in enumerate(curves):
        pts=[xy(p) for p in points]
        d.line(pts,fill=color,width=3)
        d.line((110,25+i*35,155,25+i*35),fill=color,width=4)
        text(d,(170,10+i*35),label,25,color)
    im.save(path)

def evidence_assets():
    import csv
    import hashlib
    import numpy as np
    sys.path.insert(0, str(ROOT.parent / "evaluation"))
    from flight_metrics import analyze, STAR_FLIGHT, STAR_REFERENCE, DYNAMIC_FLIGHT
    data = ROOT.parent / "evaluation" / "data"
    def read(name):
        with (data/name).open() as stream:
            return list(csv.DictReader(stream))
    ref = np.array([[float(r['x0']),float(r['x1'])] for r in read('figure8_ref_trajectory.csv')])
    rows = read('figure8_fpga_trajectory.csv')[500:1300]
    measured = np.array([[float(r['state_x'])-.383558,float(r['state_y'])+.598284] for r in rows])
    # Point-to-segment distance measures spatial path deviation, not temporal error.
    a, delta = ref[:-1], np.diff(ref,axis=0)
    denom = np.sum(delta*delta,axis=1)
    distances=[]
    for point in measured:
        u=np.divide(np.sum((point-a)*delta,axis=1),denom,out=np.zeros_like(denom),where=denom>0)
        closest=a+np.clip(u,0,1)[:,None]*delta
        distances.append(float(np.min(np.linalg.norm(point-closest,axis=1))))
    rms=100*float(np.sqrt(np.mean(np.square(distances))))
    p95=100*float(np.percentile(distances,95))
    trajectory_panel(WORK/'nominal_plot.png', [('Reference',ref,AMBER),('Measured FPGA state',measured,BLUE)],(-.7,.7))
    # The author identified 18:52:11 as the run shown in the footage.
    results=[analyze(STAR_FLIGHT, 'star', STAR_REFERENCE)]
    results[0]['spec'] = {'id': 'star_185211'}
    r=results[0]
    dynamic = analyze(DYNAMIC_FLIGHT, 'dynamic')['metrics']['x']
    star_bounds = (-1.3535533905932737, .6464466094067263)
    star_center = sum(star_bounds)/2
    # Recenter the viewport, preserving reference, measurements and bound coordinates.
    trajectory_panel(WORK/'star_plot.png', [('Reference',r['reference'][:,1:3],AMBER),('Run 18:52:11',r['positions'][:,:2],BLUE)],
                     (star_center-2.4, star_center+2.4), star_bounds)
    report={
        'figure8': {'rms_path_deviation_cm':rms,'p95_path_deviation_cm':p95,'samples':len(measured),
                    'method':'Nearest reference polyline segment in XY; state_x/y; rows [500:1300]; historical plot translation (-0.383558,+0.598284) m; not time-synchronized tracking error.',
                    'sources':{name:hashlib.sha256((data/name).read_bytes()).hexdigest() for name in ['figure8_ref_trajectory.csv','figure8_fpga_trajectory.csv']}},
        'dynamic': dynamic,
        'benchmark': {'speedup': 15.6, 'edp_improvement': 231.5, 'source': 'paper/tex/5_exp_eval.tex'},
        'star':[{ 'id':v['spec']['id'],'tracking':v['tracking'],'constraint':v['metrics']['xy_any']} for v in results]}
    (WORK/'video_metrics.json').write_text(json.dumps(report,indent=2)+'\n')
    return rms,p95,results,dynamic

def demo_overlay(path, title, captions, plot=None, plot_notes=()):
    im=Image.new('RGBA',(W,H),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.rectangle((0,0,W,115),fill=BG)
    text(d,(60,32),title,42,WHITE,True)
    d.rectangle((0,880,W,H),fill=BG)
    lines(d,60,905,captions,31,step=49)
    if plot:
        text(d,(25,125),'SIDE CAMERA',23,MUTED,True)
        text(d,(25,505),'TOP CAMERA',23,MUTED,True)
        im.alpha_composite(Image.open(plot).convert('RGBA'),(1120,105))
        d=ImageDraw.Draw(im)
        # Notes occupy the dedicated strip under the plot, above captions.
        for i,note in enumerate(plot_notes):
            text(d,(1150,810+i*32),note,24,MUTED)
    im.save(path)

def render_demo(kind,out,duration):
    """Two aspect-preserving camera panels plus one legible evidence panel."""
    if kind=='nominal':
        inputs=['-stream_loop','-1','-i',str(SOURCES['figure8']),'-stream_loop','-1','-i',str(SOURCES['figure8_top'])]
        transforms=['null','null']
    else:
        lx,ly,lw,lh=STAR_LATERAL_CROP; tx,ty,tw,th=STAR_TOP_CROP
        inputs=['-ss',str(STAR_LATERAL_START),'-i',str(SOURCES['star_lateral']),'-ss',str(STAR_TOP_START),'-i',str(SOURCES['star_top'])]
        sx, sy, sw, sh = STAR_CONSTRAINT_SQUARE
        transforms=[f'crop={lw}:{lh}:{lx}:{ly}',
                    f'crop={tw}:{th}:{tx}:{ty},hflip,vflip,'
                    f'drawbox=x={tw-sx-sw}:y={th-sy-sh}:w={sw}:h={sh}:color=0xf7b12c@0.65:t=5']
    filters=[]
    for i,transform in enumerate(transforms):
        if kind == 'star':
            # Stop before the descent seen near the end of the recording.
            transform += f',trim=duration={STAR_SAFE_DURATION},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={duration}'
        filters.append(f'[{i}:v]{transform},scale=1120:375:force_original_aspect_ratio=decrease,pad=1120:375:(ow-iw)/2:(oh-ih)/2:color=#09121f,setsar=1[v{i}]')
    filters += ['[v0][v1]vstack=inputs=2,pad=1920:1080:0:120:color=#09121f[base]', '[base][2:v]overlay=0:0:format=auto,format=yuv420p[out]']
    run([FFMPEG,'-y','-loglevel','error',*inputs,'-loop','1','-i',str(WORK/f'{kind}_ov.png'),'-filter_complex',';'.join(filters),'-map','[out]','-t',str(duration),'-an','-r',str(FPS),'-c:v','libx264','-preset','medium','-crf','18',str(out)])

def closing(path):
    im = Image.new('RGBA', (W, H), BG)
    d = ImageDraw.Draw(im)
    text(d, (160, 190), 'AccelMPC', 88, WHITE, True)
    text(d, (165, 325), 'Thank you for watching', 44, AMBER)
    lines(d, 165, 510, [
        'Solver benchmarks vs TinyMPC on MCU',
        'Up to 15.6× faster',
        'Up to 231.5× lower energy-delay product',
    ], 34, step=65)
    lines(d, 165, 745, [#'FPGA power: measured; post-route estimates where needed',
                       'Solve-only comparison'# · excludes communication and support circuitry'
                       ], 25, MUTED, step=42)
    # Reserve the right side for a repository QR code after deanonymization.
    im.save(path)


def media_duration(path):
    return float(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(path)
    ], text=True).strip())


def subtitle_phrase_start(path, phrase):
    """Use the TTS sentence cue to align a visual cut with spoken words."""
    import re
    for block in re.split(r'\n\s*\n', path.read_text().strip()):
        rows = block.splitlines()
        if len(rows) >= 3 and ' '.join(rows[2:]).startswith(phrase):
            stamp = rows[1].split(' --> ')[0]
            hours, minutes, seconds = stamp.replace(',', '.').split(':')
            return int(hours)*3600 + int(minutes)*60 + float(seconds)
    raise ValueError(f'{phrase!r} must begin a cue in {path}; regenerate narration.')


def main():
    import argparse
    import math
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--nominal-only', action='store_true')
    mode.add_argument('--star-only', action='store_true')
    parser.add_argument('--top-trail', action='store_true')
    parser.add_argument('--assets-only', action='store_true')
    parser.add_argument('--narration-dir', type=Path, default=ROOT/'narration',
                        help='Directory containing chapter WAV files (default: video/narration)')
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    load_manual_star_config()
    WORK.mkdir(exist_ok=True)
    if args.top_trail:
        tx,ty,tw,th=STAR_TOP_CROP
        motion_trail(SOURCES['star_top'], TOP_TRAIL_RAW)
        motion_trail(SOURCES['star_top'], TOP_TRAIL_CROPPED, f'crop={tw}:{th}:{tx}:{ty},hflip,vflip')
        return
    rms, p95, star, dynamic = evidence_assets()
    cover(WORK/'cover.png')
    hardware(WORK/'hardware.png')
    system_card(WORK/'system.png')
    closing(WORK/'closing.png')
    tr, cv = star[0]['tracking'], star[0]['metrics']['xy_any']
    demo_overlay(WORK/'nominal_ov.png', 'Figure-eight / onboard MPC', [
        f'XY path deviation: {rms:.2f} cm RMS', # | P95 {p95:.2f} cm',
        'FPGA: 20 step horizon, 28 ADMM iterations'
    ], WORK/'nominal_plot.png')
    demo_overlay(WORK/'star_ov.png', 'Constrained tracking / 1 kHz onboard MPC', [
        f'3D tracking {tr["rmse_cm"]:.2f} cm RMSE over feasible section of the reference', # | Feasible reference: {tr["coverage_percent"]:.2f}% of samples; fitted phase',
        f'Bound violation: RMS {cv["rms_violation_cm"]:.3f} cm | Maximum {cv["max_violation_cm"]:.2f} cm per axis',
        '27 step horizon , 9 ADMM iterations | Square: allowed region.'
    ], WORK/'star_plot.png')
    demo_overlay(WORK/'dynamic_ov.png', 'Moving obstacles / changing position limits', [
        'Motion capture: 120 Hz | Onboard MPC: 1 kHz',
        f'Bound violation: RMS {dynamic["rms_violation_cm"]:.3f} cm | Maximum {dynamic["max_violation_cm"]:.2f} cm', # | Inside: {100-dynamic["outside_percent"]:.2f}%',
        #'Full recording; position bounds are the last transmitted bounds.'
    ])
    if args.assets_only:
        print(f'Wrote assets to {WORK}')
        return
    names = ['nominal'] if args.nominal_only else ['star'] if args.star_only else list(TIMINGS)
    durations = {}
    audio_offsets = {name: (-1.0 if name == 'system' and 'cover' in names else 0.0) for name in names}
    if args.narration_dir and 'nominal' in names and 'star' in names:
        audio_offsets['star'] = -2.5
    if args.narration_dir and 'dynamic' in names and 'closing' in names:
        audio_offsets['closing'] = -subtitle_phrase_start(args.narration_dir/'closing.srt', 'Solver benchmarks')
    for name in names:
        duration = TIMINGS[name]
        if args.narration_dir:
            audio = args.narration_dir/f'{name}.wav'
            if not audio.is_file():
                raise FileNotFoundError(audio)
            tail = 0.4 if name in ('cover', 'system', 'hardware', 'star') else 1.0
            duration = max(duration, math.ceil((media_duration(audio)+audio_offsets[name]+tail)*FPS)/FPS)
        durations[name] = duration
    if len(names) > 1 and not 120 <= sum(durations.values()) <= 180:
        raise ValueError('Full cut must be 2–3 minutes; shorten narration or adjust TIMINGS.')
    segments = []
    for name in names:
        duration = durations[name]
        out = WORK/f'narrated_{name}.mp4'
        if name == 'cover':
            render_cover(out, duration)
        elif name in ('hardware', 'system', 'closing'):
            still_segment(WORK/f'{name}.png', duration, out)
        elif name == 'dynamic':
            # Play the experiment once. Any extra narration holds the final frame.
            video_segment(SOURCES['dynamic'], DYNAMIC_START, duration, out,
                f'trim=duration=38,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={duration},'
                'scale=1920:720:force_original_aspect_ratio=decrease,'
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#09121f', WORK/'dynamic_ov.png')
        else:
            render_demo(name, out, duration)
        segments.append(out)
    # Build one continuous PCM soundtrack, allowing speech to lead slide cuts.
    import wave
    sample_rate, frame_bytes = 48000, 4  # stereo, signed 16-bit
    total_duration = sum(durations.values())
    soundtrack = bytearray(round(total_duration*sample_rate)*frame_bytes)
    cursor, previous_end = 0.0, 0
    for name in names:
        if args.narration_dir:
            with wave.open(str(args.narration_dir/f'{name}.wav'), 'rb') as source:
                if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (sample_rate, 2, 2):
                    raise ValueError('Narration must be 48 kHz stereo 16-bit WAV; run generate_narration.py.')
                pcm = source.readframes(source.getnframes())
            start = round((cursor+audio_offsets[name])*sample_rate)*frame_bytes
            end = start+len(pcm)
            if start < previous_end or end > len(soundtrack):
                raise ValueError(f'Narration overlaps or exceeds the cut: {name}')
            soundtrack[start:end] = pcm
            previous_end = end
        cursor += durations[name]
    mix = WORK/'narration_mix.wav'
    with wave.open(str(mix), 'wb') as target:
        target.setparams((2, 2, sample_rate, 0, 'NONE', 'not compressed'))
        target.writeframes(soundtrack)
    destination = NOMINAL_OUT if args.nominal_only else STAR_OUT if args.star_only else args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    concat = WORK/'concat.txt'
    concat.write_text(''.join("file '"+str(p.resolve()).replace("'", "'\\''")+"'\n" for p in segments))
    run([FFMPEG, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(concat),
         '-i', str(mix), '-map', '0:v:0', '-map', '1:a:0',
         '-c:v', 'copy', '-c:a', 'aac', '-t', str(total_duration), '-movflags', '+faststart', str(destination)])
    (WORK/'audio_offsets.json').write_text(json.dumps(audio_offsets, indent=2)+'\n')
    (WORK/'timeline.json').write_text(json.dumps(durations, indent=2)+'\n')
    print(f'Wrote {destination} ({sum(durations.values())} seconds)')


if __name__ == '__main__':
    main()
