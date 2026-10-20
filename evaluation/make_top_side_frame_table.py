#!/usr/bin/env python3
"""Generate the top/side three-frame paper table.

The default path composes the paper figure from tracked panel PNGs, so raw
videos are not needed for normal regeneration. Use --extract-panels on a
machine with the original videos to refresh those panel PNGs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from bisect import bisect_right
from pathlib import Path

from PIL import Image


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DATA_DIR = SCRIPT_DIR / "data" / "top_side_frame_table"
PANEL_NAMES = (
    ("top_t09.png", "side_t09.png"),
    ("top_t36_25.png", "side_t36_25.png"),
    ("top_t37.png", "side_t37.png"),
)

# Approximate head redaction circles in local top-panel pixel coordinates:
# (x, y, radius). These are intentionally easy to tune by hand.
HEAD_COVERS = {
    "top_t09.png": [(-5, 565, 115), (2235, 825, 130)],
    "top_t36_25.png": [(500, 750, 125), (1870, 740, 125)],
    "top_t37.png": [(520, 750, 125), (1860, 725, 125)],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compose or refresh the top/side three-frame paper figure."
    )
    parser.add_argument(
        "--extract-panels",
        action="store_true",
        help="Refresh the tracked panel PNGs from the local raw videos before composing the figure.",
    )
    parser.add_argument("--video", default=str(REPO_ROOT / "VideoICRA" / "output.mp4"), help="Input top-view video.")
    parser.add_argument(
        "--side-video",
        default=str(REPO_ROOT / "VideoICRA" / "IMG_1630 (1).MOV"),
        help="Input side-view video.",
    )
    parser.add_argument(
        "--log",
        default=str(DATA_DIR / "TAKE1fpga_bridge_log_20260522_153539.csv"),
        help="CSV log with mocap data.",
    )
    parser.add_argument(
        "--calibration-clicks",
        default=str(DATA_DIR / "trajectory_clicks.json"),
        help="Calibration clicks generated for the 960x720 composite top panel.",
    )
    parser.add_argument(
        "--panel-dir",
        default=str(DATA_DIR / "panels"),
        help="Directory containing or receiving the six panel PNGs.",
    )
    parser.add_argument(
        "--no-flip-x",
        dest="flip_x",
        action="store_false",
        help="Disable the default mocap x flip.",
    )
    parser.add_argument("--flip-y", action="store_true", help="Flip mocap y direction in the overlay.")
    parser.set_defaults(flip_x=True)
    parser.add_argument(
        "--no-flip-top-vertical",
        dest="flip_top_vertical",
        action="store_false",
        help="Disable the default vertical flip applied to top-view panels.",
    )
    parser.set_defaults(flip_top_vertical=True)
    parser.add_argument(
        "--times",
        nargs="+",
        type=float,
        default=[9.0, 36.25, 37.0],
        help="Frame times in seconds relative to --top-start.",
    )
    parser.add_argument(
        "--top-start",
        type=float,
        default=104.0,
        help="Start time in seconds within the top-view video.",
    )
    parser.add_argument(
        "--side-start",
        type=float,
        default=16.5,
        help="Start time in seconds within the side-view video.",
    )
    parser.add_argument(
        "--trajectory-delay",
        type=float,
        default=-1.5,
        help="Delay mocap trajectory overlay relative to video.",
    )
    parser.add_argument("--trail-seconds", type=float, default=3.0, help="Bright recent trail length.")
    parser.add_argument(
        "--output",
        default=str(SCRIPT_DIR / "output" / "top_side_three_frame_table.png"),
        help="Output PNG path.",
    )
    parser.add_argument(
        "--pdf-output",
        default=str(SCRIPT_DIR / "output" / "top_side_three_frame_table.pdf"),
        help="Optional output PDF path. Use an empty string to skip PDF export.",
    )
    parser.add_argument("--gutter", type=int, default=14, help="White spacing between columns in pixels.")
    parser.add_argument("--row-gutter", type=int, default=14, help="White spacing between top and side rows in pixels.")
    parser.add_argument("--crop-x0", type=int, default=0, help="Left crop coordinate in source-video pixels.")
    parser.add_argument("--crop-x1", type=int, help="Right crop coordinate in source-video pixels.")
    parser.add_argument("--crop-y0", type=int, default=0, help="Top crop coordinate in source-video pixels.")
    parser.add_argument("--crop-y1", type=int, help="Bottom crop coordinate in source-video pixels.")
    parser.add_argument(
        "--max-panel-width",
        type=int,
        help="Optional width to resize each panel after cropping. Omit to keep source resolution.",
    )
    return parser.parse_args()


def read_log(log_path: Path) -> tuple[list[dict[str, float]], object | None]:
    rows = []
    with log_path.open(newline="") as fobj:
        reader = csv.DictReader(fobj)
        for row in reader:
            if row.get("event") != "sample" or row.get("mocap_valid") != "1":
                continue
            try:
                rows.append(
                    {
                        "elapsed": float(row["elapsed_s"]),
                        "x": float(row["mocap_x"]),
                        "y": float(row["mocap_y"]),
                        "z": float(row["mocap_z"]),
                        "target_x": float(row["target_x"]) if row.get("target_x") else math.nan,
                        "target_y": float(row["target_y"]) if row.get("target_y") else math.nan,
                    }
                )
            except (KeyError, ValueError):
                continue

    if not rows:
        raise RuntimeError(f"No valid mocap samples found in {log_path}")

    first_elapsed = rows[0]["elapsed"]
    for row in rows:
        row["t"] = row["elapsed"] - first_elapsed

    return rows, None


def rows_for_video_window(rows: list[dict[str, float]], duration: float, trajectory_delay: float) -> list[dict[str, float]]:
    mocap_start = max(0.0, -trajectory_delay)
    mocap_end = duration - trajectory_delay
    if mocap_end < mocap_start:
        raise RuntimeError(
            "Trajectory delay leaves no mocap samples in the rendered video window. "
            f"duration={duration:.3f}s trajectory_delay={trajectory_delay:.3f}s"
        )
    selected = [row for row in rows if mocap_start <= row["t"] <= mocap_end]
    return selected or rows


def mocap_calibration_points(rows: list[dict[str, float]], duration: float, trajectory_delay: float):
    import numpy as np

    selected = rows_for_video_window(rows, duration, trajectory_delay)
    coords = np.array([[row["x"], row["y"]] for row in selected], dtype=np.float32)
    center = np.mean(coords, axis=0)
    left = coords[int(np.argmin(coords[:, 0]))]
    right = coords[int(np.argmax(coords[:, 0]))]
    return np.array([center, left, right], dtype=np.float32)


def read_calibration_clicks(path: Path):
    import numpy as np

    with path.open() as fobj:
        data = json.load(fobj)
    try:
        dest = np.array(
            [
                data["center_px"],
                data["left_px"],
                data["right_px"],
            ],
            dtype=np.float32,
        )
    except KeyError as exc:
        raise RuntimeError(f"Calibration clicks file is missing {exc.args[0]!r}: {path}") from exc

    if dest.shape != (3, 2):
        raise RuntimeError(f"Calibration clicks file has invalid point shape: {path}")
    return dest, data.get("metadata", {})


def make_calibrated_mapper(
    rows: list[dict[str, float]],
    duration: float,
    trajectory_delay: float,
    clicks_path: Path,
    flip_x: bool,
    flip_y: bool,
):
    dest, metadata = read_calibration_clicks(clicks_path)
    reference_duration = float(metadata.get("duration_s", duration))
    source = mocap_calibration_points(rows, reference_duration, trajectory_delay)
    center_src, left_src, right_src = source
    center_dst, left_dst, right_dst = dest
    mocap_width = right_src[0] - left_src[0]
    pixel_width = right_dst[0] - left_dst[0]
    if abs(mocap_width) < 1e-9 or abs(pixel_width) < 1e-9:
        raise RuntimeError("Calibration left/right points do not define a usable horizontal scale")

    scale_x = pixel_width / mocap_width
    if flip_x:
        scale_x *= -1.0
    scale_y = abs(scale_x) if flip_y else -abs(scale_x)

    def map_xy(x: float, y: float):
        import numpy as np

        if not np.isfinite(x) or not np.isfinite(y):
            return None
        px = center_dst[0] + (x - center_src[0]) * scale_x
        py = center_dst[1] + (y - center_src[1]) * scale_y
        return int(round(px)), int(round(py))

    print(f"using calibration clicks: {clicks_path}")
    print(
        "mocap calibration window "
        f"{max(0.0, -trajectory_delay):.3f}s..{reference_duration - trajectory_delay:.3f}s "
        f"from click-file duration {reference_duration:.3f}s"
    )
    print(
        "mocap reference points "
        f"center={source[0].tolist()} left={source[1].tolist()} right={source[2].tolist()}"
    )
    print(f"pixel reference points center={dest[0].tolist()} left={dest[1].tolist()} right={dest[2].tolist()}")
    print(f"calibrated axis-aligned scale scale_x={scale_x:.6f} scale_y={scale_y:.6f}")
    return map_xy, metadata


def scaled_mapper(base_mapper, source_width: int, source_height: int, calibration_panel_width=960, calibration_panel_height=720):
    scale = min(calibration_panel_width / source_width, calibration_panel_height / source_height)
    fitted_width = int(round(source_width * scale))
    fitted_height = int(round(source_height * scale))
    x_offset = (calibration_panel_width - fitted_width) // 2
    y_offset = (calibration_panel_height - fitted_height) // 2

    def map_xy(x: float, y: float):
        point = base_mapper(x, y)
        if point is None:
            return None
        px, py = point
        return int(round((px - x_offset) / scale)), int(round((py - y_offset) / scale))

    return map_xy, 1.0 / scale


def draw_trajectory_scaled(frame, rows, times, frame_t, map_xy, trail_seconds, scale):
    import cv2
    import numpy as np

    line_outer = max(1, int(round(7 * scale)))
    line_inner = max(1, int(round(2 * scale)))
    dot_outer = max(1, int(round(9 * scale)))
    dot_inner = max(1, int(round(7 * scale)))

    upto = bisect_right(times, frame_t)
    if upto <= 0:
        return

    pts = [map_xy(row["x"], row["y"]) for row in rows[:upto]]
    pts = [point for point in pts if point is not None]
    if not pts:
        return

    trail_start = max(0.0, frame_t - trail_seconds)
    first = bisect_right(times, trail_start)
    trail_pts = [map_xy(row["x"], row["y"]) for row in rows[first:upto]]
    trail_pts = [point for point in trail_pts if point is not None]
    if len(trail_pts) >= 2:
        cv2.polylines(frame, [np.array(trail_pts, dtype=np.int32)], False, (0, 140, 255), line_outer, cv2.LINE_AA)
        cv2.polylines(frame, [np.array(trail_pts, dtype=np.int32)], False, (255, 255, 255), line_inner, cv2.LINE_AA)

    current = pts[-1]
    cv2.circle(frame, current, dot_outer, (0, 0, 0), -1, cv2.LINE_AA)
    cv2.circle(frame, current, dot_inner, (0, 230, 255), -1, cv2.LINE_AA)


def read_top_panel(
    cap,
    video_path: Path,
    source_time_s: float,
    trajectory_t: float,
    rows,
    mocap_times,
    map_xy,
    draw_scale: float,
    args: argparse.Namespace,
):
    import cv2

    cap.set(cv2.CAP_PROP_POS_MSEC, source_time_s * 1000.0)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f"Could not read frame at {source_time_s:.3f} s from {video_path}")

    height, width = frame.shape[:2]
    overlay = frame.copy()
    draw_trajectory_scaled(overlay, rows, mocap_times, trajectory_t, map_xy, args.trail_seconds, draw_scale)

    x1_default = width if args.crop_x1 is None else args.crop_x1
    y1_default = height if args.crop_y1 is None else args.crop_y1
    x0 = max(0, min(args.crop_x0, width))
    x1 = max(x0 + 1, min(x1_default, width))
    y0 = max(0, min(args.crop_y0, height))
    y1 = max(y0 + 1, min(y1_default, height))
    panel = overlay[y0:y1, x0:x1]
    if args.flip_top_vertical:
        panel = cv2.flip(panel, 0)

    if args.max_panel_width and panel.shape[1] > args.max_panel_width:
        scale = args.max_panel_width / panel.shape[1]
        panel = cv2.resize(
            panel,
            (args.max_panel_width, int(round(panel.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )

    return panel


def read_side_panel(cap, video_path: Path, source_time_s: float, target_size: tuple[int, int]):
    import cv2

    cap.set(cv2.CAP_PROP_POS_MSEC, source_time_s * 1000.0)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f"Could not read side frame at {source_time_s:.3f} s from {video_path}")
    return cv2.resize(frame, target_size, interpolation=cv2.INTER_CUBIC)


def save_cv2_panel(panel, output: Path) -> None:
    import cv2

    output.parent.mkdir(parents=True, exist_ok=True)
    rgb = cv2.cvtColor(panel, cv2.COLOR_BGR2RGB)
    Image.fromarray(rgb).save(output, optimize=True)
    print(f"wrote {output}")


def extract_panels(args: argparse.Namespace) -> None:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Panel extraction requires OpenCV with a NumPy-compatible build. "
            "The default panel-only mode does not require OpenCV."
        ) from exc

    if len(args.times) != len(PANEL_NAMES):
        raise RuntimeError(f"Expected exactly {len(PANEL_NAMES)} frame times for the tracked panel names")

    video_path = Path(args.video)
    side_video_path = Path(args.side_video)
    log_path = Path(args.log)
    clicks_path = Path(args.calibration_clicks)
    panel_dir = Path(args.panel_dir)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    side_cap = cv2.VideoCapture(str(side_video_path))
    if not side_cap.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open side video: {side_video_path}")

    source_width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
    source_height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    rows, _ = read_log(log_path)
    base_mapper, _ = make_calibrated_mapper(
        rows,
        duration=max(args.times),
        trajectory_delay=args.trajectory_delay,
        clicks_path=clicks_path,
        flip_x=args.flip_x,
        flip_y=args.flip_y,
    )
    map_xy, draw_scale = scaled_mapper(base_mapper, source_width, source_height)
    mocap_times = [row["t"] for row in rows]

    try:
        top_panels = [
            read_top_panel(
                cap,
                video_path,
                args.top_start + time_s,
                time_s - args.trajectory_delay,
                rows,
                mocap_times,
                map_xy,
                draw_scale,
                args,
            )
            for time_s in args.times
        ]
    finally:
        cap.release()

    try:
        side_panels = [
            read_side_panel(
                side_cap,
                side_video_path,
                args.side_start + time_s,
                (top_panels[idx].shape[1], top_panels[idx].shape[0]),
            )
            for idx, time_s in enumerate(args.times)
        ]
    finally:
        side_cap.release()

    for (top_name, side_name), top_panel, side_panel in zip(PANEL_NAMES, top_panels, side_panels):
        save_cv2_panel(top_panel, panel_dir / top_name)
        save_cv2_panel(side_panel, panel_dir / side_name)


def load_panel(path: Path) -> Image.Image:
    if not path.exists():
        raise RuntimeError(f"Missing tracked panel PNG: {path}")
    return Image.open(path).convert("RGB")


def apply_head_covers(panel: Image.Image, panel_name: str) -> Image.Image:
    from PIL import ImageDraw

    covers = HEAD_COVERS.get(panel_name, [])
    if not covers:
        return panel

    redacted = panel.copy()
    draw = ImageDraw.Draw(redacted)
    for x, y, radius in covers:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="black")
    return redacted


def compose_from_panels(panel_dir: Path, gutter: int, row_gutter: int) -> Image.Image:
    top_panels = [
        apply_head_covers(load_panel(panel_dir / top_name), top_name)
        for top_name, _side_name in PANEL_NAMES
    ]
    side_panels = [load_panel(panel_dir / side_name) for _top_name, side_name in PANEL_NAMES]

    row_height = max(max(top.height, side.height) for top, side in zip(top_panels, side_panels))
    column_widths = [max(top.width, side.width) for top, side in zip(top_panels, side_panels)]
    width = sum(column_widths) + gutter * (len(column_widths) - 1)
    height = row_height * 2 + row_gutter
    figure = Image.new("RGB", (width, height), "white")

    x = 0
    for column_width, top_panel, side_panel in zip(column_widths, top_panels, side_panels):
        top_x = x + (column_width - top_panel.width) // 2
        side_x = x + (column_width - side_panel.width) // 2
        figure.paste(top_panel, (top_x, 0))
        figure.paste(side_panel, (side_x, row_height + row_gutter))
        x += column_width + gutter

    return figure


def write_outputs(figure: Image.Image, output_path: Path, pdf_output: Path | None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.save(output_path)
    print(f"wrote {output_path} ({figure.width}x{figure.height})")

    if pdf_output is not None:
        pdf_output.parent.mkdir(parents=True, exist_ok=True)
        figure.save(pdf_output, resolution=300.0)
        print(f"wrote {pdf_output}")


def main() -> None:
    args = parse_args()
    if args.extract_panels:
        extract_panels(args)

    figure = compose_from_panels(Path(args.panel_dir), args.gutter, args.row_gutter)
    pdf_output = Path(args.pdf_output) if args.pdf_output else None
    write_outputs(figure, Path(args.output), pdf_output)


if __name__ == "__main__":
    main()
