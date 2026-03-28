#!/usr/bin/env python3
"""
Parallel fixed-point tuning via Vitis HLS csim.

Searches:
- full diagonal Q (12 independent values)
- scalar R (R = r_scale * I4)
- outer frequency sweep for model linearization frequency
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


Q_DIM = 12
DEFAULT_FREQ_VALUES = [50.0, 100.0, 200.0]
DEFAULT_STAGE1_FACTORS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
DEFAULT_STAGE2_FACTORS = [0.67, 1.0, 1.5]
DEFAULT_MAX_WORKERS = 8

# Matches scripts/header_generator.py defaults.
BASE_MAX_DEV_X = [0.075, 0.075, 0.075, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.7, 0.7, 0.2]
BASE_Q_DIAG = [1.0 / (v * v) for v in BASE_MAX_DEV_X]
BASE_R_SCALE = 1.0 / (0.5 * 0.5)


@dataclass(frozen=True)
class CandidateEval:
    candidate_hash: str
    freq_hz: float
    rho: int
    horizon: int
    admm_iters: int
    q_diag: tuple[float, ...]
    r_scale: float
    sim_freq: float
    sim_duration_s: float
    step_x: float
    step_y: float
    step_z: float
    step_yaw: float
    rise_lo: float
    rise_hi: float
    settle_pct: float
    candidate_timeout_s: float
    heartbeat_s: float
    enable_heartbeat: bool


@dataclass(frozen=True)
class StageCandidate:
    stage: str
    candidate_hash: str
    freq_hz: float
    r_scale: float
    q_diag: tuple[float, ...]
    sweep_kind: str
    dim_idx: int
    factor: float


def parse_float_list(text: str, what: str) -> list[float]:
    vals = [float(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError(f"No values parsed from {what}")
    return vals


def parse_json_qdiag(text: str) -> tuple[float, ...]:
    arr = json.loads(text)
    if not isinstance(arr, list) or len(arr) != Q_DIM:
        raise ValueError("Invalid q_diag in cache row")
    out = tuple(float(v) for v in arr)
    if any(v <= 0 for v in out):
        raise ValueError("Invalid q_diag values in cache row")
    return out


def float_or_nan(v: Any) -> float:
    if v is None:
        return math.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def normalize(v: float, lo: float, hi: float) -> float:
    if not math.isfinite(v):
        return math.nan
    if not math.isfinite(lo) or not math.isfinite(hi):
        return math.nan
    if hi <= lo:
        return 0.0
    return (v - lo) / (hi - lo)


def compute_scores(rows: list[dict[str, Any]]) -> None:
    ok_rows = [r for r in rows if r.get("status") == "ok"]
    if not ok_rows:
        return

    rise_vals = [float_or_nan(r.get("rise_time_s")) for r in ok_rows]
    settle_vals = [float_or_nan(r.get("settling_time_s")) for r in ok_rows]
    over_vals = [float_or_nan(r.get("overshoot_pct")) for r in ok_rows]
    effort_vals = [float_or_nan(r.get("control_effort_l1")) for r in ok_rows]

    def finite_minmax(vals: list[float]) -> tuple[float, float]:
        finite = [v for v in vals if math.isfinite(v)]
        if not finite:
            return (math.nan, math.nan)
        return (min(finite), max(finite))

    rise_lo, rise_hi = finite_minmax(rise_vals)
    settle_lo, settle_hi = finite_minmax(settle_vals)
    over_lo, over_hi = finite_minmax(over_vals)
    eff_lo, eff_hi = finite_minmax(effort_vals)

    for row in ok_rows:
        n_rise = normalize(float_or_nan(row.get("rise_time_s")), rise_lo, rise_hi)
        n_settle = normalize(float_or_nan(row.get("settling_time_s")), settle_lo, settle_hi)
        n_over = normalize(float_or_nan(row.get("overshoot_pct")), over_lo, over_hi)
        n_eff = normalize(float_or_nan(row.get("control_effort_l1")), eff_lo, eff_hi)
        if not all(math.isfinite(v) for v in [n_rise, n_settle, n_over, n_eff]):
            row["score"] = math.nan
            row["rank"] = ""
            continue
        row["score"] = 0.45 * n_settle + 0.25 * n_rise + 0.20 * n_over + 0.10 * n_eff
        row["rank"] = ""

    ranked = sorted(
        [r for r in ok_rows if math.isfinite(float_or_nan(r.get("score")))],
        key=lambda r: float(r["score"]),
    )
    for idx, row in enumerate(ranked, start=1):
        row["rank"] = idx


def candidate_hash(
    *,
    freq_hz: float,
    rho: int,
    horizon: int,
    admm_iters: int,
    q_diag: tuple[float, ...],
    r_scale: float,
    sim_freq: float,
    sim_duration_s: float,
    step_x: float,
    step_y: float,
    step_z: float,
    step_yaw: float,
    rise_lo: float,
    rise_hi: float,
    settle_pct: float,
) -> str:
    payload = {
        "freq_hz": round(freq_hz, 12),
        "rho": rho,
        "horizon": horizon,
        "admm_iters": admm_iters,
        "q_diag": [round(v, 12) for v in q_diag],
        "r_scale": round(r_scale, 12),
        "sim_freq": round(sim_freq, 12),
        "sim_duration_s": round(sim_duration_s, 12),
        "step_x": round(step_x, 12),
        "step_y": round(step_y, 12),
        "step_z": round(step_z, 12),
        "step_yaw": round(step_yaw, 12),
        "rise_lo": round(rise_lo, 12),
        "rise_hi": round(rise_hi, 12),
        "settle_pct": round(settle_pct, 12),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_cmd(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def parse_u_hover(data_h_path: Path) -> float:
    text = data_h_path.read_text()
    m = re.search(r"^\s*#define\s+U_HOVER\s+([^\s]+)\s*$", text, re.MULTILINE)
    if m is None:
        raise ValueError("U_HOVER not found in data.h")
    return float(m.group(1))


def read_last_controls(csv_path: Path) -> list[float]:
    last_row: dict[str, str] | None = None
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            last_row = row
    if last_row is None:
        raise ValueError("trajectory.csv is empty")
    return [
        float(last_row["u0"]),
        float(last_row["u1"]),
        float(last_row["u2"]),
        float(last_row["u3"]),
    ]


def generate_trajectory_plot(csv_path: Path, png_path: Path, title: str, param_lines: list[str] | None = None) -> float:
    t_vals: list[float] = []
    x = [[] for _ in range(12)]
    u0: list[float] = []
    u1: list[float] = []
    u2: list[float] = []
    u3: list[float] = []

    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t_vals.append(float(row["t"]))
            for i in range(12):
                x[i].append(float(row[f"x{i}"]))
            u0.append(float(row["u0"]))
            u1.append(float(row["u1"]))
            u2.append(float(row["u2"]))
            u3.append(float(row["u3"]))

    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 0.7], hspace=0.3)
    ax_pos = fig.add_subplot(gs[0, 0])
    ax_att = fig.add_subplot(gs[0, 1])
    ax_vel = fig.add_subplot(gs[1, 0])
    ax_angvel = fig.add_subplot(gs[1, 1])
    ax_u = fig.add_subplot(gs[2, :])

    ax_pos.plot(t_vals, x[0], label="x")
    ax_pos.plot(t_vals, x[1], label="y")
    ax_pos.plot(t_vals, x[2], label="z")
    ax_pos.set_title("Position [x y z]")
    ax_pos.set_ylabel("m")
    ax_pos.grid(True)
    ax_pos.legend()

    ax_att.plot(t_vals, x[3], label="roll")
    ax_att.plot(t_vals, x[4], label="pitch")
    ax_att.plot(t_vals, x[5], label="yaw")
    ax_att.set_title("Orientation [roll pitch yaw]")
    ax_att.set_ylabel("rad")
    ax_att.grid(True)
    ax_att.legend()

    ax_vel.plot(t_vals, x[6], label="vx")
    ax_vel.plot(t_vals, x[7], label="vy")
    ax_vel.plot(t_vals, x[8], label="vz")
    ax_vel.set_title("Linear Velocity")
    ax_vel.set_ylabel("m/s")
    ax_vel.grid(True)
    ax_vel.legend()

    ax_angvel.plot(t_vals, x[9], label="wx")
    ax_angvel.plot(t_vals, x[10], label="wy")
    ax_angvel.plot(t_vals, x[11], label="wz")
    ax_angvel.set_title("Angular Velocity")
    ax_angvel.set_ylabel("rad/s")
    ax_angvel.grid(True)
    ax_angvel.legend()

    ax_u.plot(t_vals, u0, label="u0")
    ax_u.plot(t_vals, u1, label="u1")
    ax_u.plot(t_vals, u2, label="u2")
    ax_u.plot(t_vals, u3, label="u3")
    ax_u.set_xlabel("Time [s]")
    ax_u.set_ylabel("Control")
    ax_u.grid(True)
    ax_u.legend()

    if title:
        fig.suptitle(title)
        top = 0.90
    else:
        top = 0.98

    if param_lines:
        fig.text(
            0.01,
            top,
            "\n".join(param_lines),
            ha="left",
            va="top",
            fontsize=8,
            family="monospace",
        )
        fig.tight_layout(rect=[0, 0, 1, top - 0.02])
    else:
        fig.tight_layout(rect=[0, 0, 1, top])
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=140)
    plt.close(fig)
    return x[0][-1] if x[0] else math.nan


def evaluate_candidate(task: tuple[CandidateEval, str, str]) -> dict[str, Any]:
    cand, repo_root_str, run_root_str = task
    repo_root = Path(repo_root_str)
    run_root = Path(run_root_str)
    job_root = run_root / "jobs" / f"{cand.candidate_hash[:16]}"
    scripts_dir = job_root / "scripts"
    src_dir = job_root / "vitis_projects" / "ADMM"
    rtl_dir = job_root / "vivado_project" / "vivado_project.srcs" / "sources_1" / "new"
    out_dir = job_root / "outputs"
    hls_work_dir = job_root / "hls_work"
    logs_dir = job_root / "logs"
    for d in [scripts_dir, src_dir, rtl_dir, out_dir, logs_dir]:
        d.mkdir(parents=True, exist_ok=True)
    
    print(
                f"[start {cand.candidate_hash[:12]} "
                f"f={cand.freq_hz:g}Hz r={cand.r_scale:.6g} q_diag={[f'{v:.3g}' for v in cand.q_diag]}]",
            )

    src_admm_dir = repo_root / "vitis_projects" / "ADMM"
    for filename in [
        "ADMM.cpp",
        "ADMM.h",
        "data_types.h",
        "ADMM_closed_loop_tb.cpp",
        "hls_eval_config.cfg",
        "traj_data.h",
        "traj_data_raw.h",
    ]:
        shutil.copy2(src_admm_dir / filename, src_dir / filename)

    src_scripts_dir = repo_root / "scripts"
    for filename in ["header_generator.py", "parameters.py", "crazyloihimodel.py"]:
        shutil.copy2(src_scripts_dir / filename, scripts_dir / filename)

    qdiag_str = ",".join(f"{v:.12g}" for v in cand.q_diag)
    data_out = src_dir / "data.h"
    header_env = os.environ.copy()
    header_env["ADMM_HORIZON_LENGTH"] = str(cand.horizon)
    header_env["ADMM_ITERATIONS"] = str(cand.admm_iters)
    header_env["ADMM_RHO_EQ_PARAM"] = str(cand.rho)
    header_env["ADMM_RHO_INEQ_PARAM"] = str(cand.rho)
    header_env["ADMM_MODEL_FREQ"] = f"{cand.freq_hz:.12g}"
    header_env["ADMM_Q_DIAG"] = qdiag_str
    header_env["ADMM_R_SCALE"] = f"{cand.r_scale:.12g}"
    header_cmd = ["python3", str(scripts_dir / "header_generator.py")]
    header_proc = run_cmd(header_cmd, cwd=job_root, env=header_env)
    (logs_dir / "header.stdout.log").write_text(header_proc.stdout)
    (logs_dir / "header.stderr.log").write_text(header_proc.stderr)
    if header_proc.returncode != 0:
        return {
            "candidate_hash": cand.candidate_hash,
            "status": "error",
            "error": f"header_generator failed ({header_proc.returncode})",
            "job_dir": str(job_root),
        }

    traj_path = out_dir / "trajectory.csv"
    plot_path = out_dir / "trajectory.png"
    env = header_env.copy()
    env["ADMM_CSIM_TRAJ_PATH"] = str(traj_path)
    env["ADMM_SIM_FREQ"] = f"{cand.sim_freq:.12g}"
    env["ADMM_SIM_DURATION_S"] = f"{cand.sim_duration_s:.12g}"
    env["ADMM_STEP_X"] = f"{cand.step_x:.12g}"
    env["ADMM_STEP_Y"] = f"{cand.step_y:.12g}"
    env["ADMM_STEP_Z"] = f"{cand.step_z:.12g}"
    env["ADMM_STEP_YAW"] = f"{cand.step_yaw:.12g}"

    csim_cmd = [
        "vitis-run",
        "--mode",
        "hls",
        "--csim",
        "--config",
        "./hls_eval_config.cfg",
        "--work_dir",
        str(hls_work_dir),
    ]
    proc = subprocess.Popen(
        csim_cmd,
        cwd=src_dir,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    start = time.monotonic()
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    while True:
        try:
            out, err = proc.communicate(timeout=max(1.0, cand.heartbeat_s))
            stdout_chunks.append(out)
            stderr_chunks.append(err)
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            if cand.candidate_timeout_s > 0 and elapsed > cand.candidate_timeout_s:
                proc.kill()
                out, err = proc.communicate()
                stdout_chunks.append(out)
                stderr_chunks.append(err)
                (logs_dir / "csim.stdout.log").write_text("".join(stdout_chunks))
                (logs_dir / "csim.stderr.log").write_text("".join(stderr_chunks))
                return {
                    "candidate_hash": cand.candidate_hash,
                    "status": "error",
                    "error": f"csim timeout after {elapsed:.1f}s",
                    "job_dir": str(job_root),
                }
            if cand.enable_heartbeat:
                print(
                    f"[heartbeat] {cand.candidate_hash[:12]} csim running "
                    f"for {elapsed:.1f}s (f={cand.freq_hz:g}Hz)",
                    flush=True,
                )

    csim_stdout = "".join(stdout_chunks)
    csim_stderr = "".join(stderr_chunks)
    (logs_dir / "csim.stdout.log").write_text(csim_stdout)
    (logs_dir / "csim.stderr.log").write_text(csim_stderr)
    if proc.returncode != 0:
        return {
            "candidate_hash": cand.candidate_hash,
            "status": "error",
            "error": f"csim failed ({proc.returncode})",
            "job_dir": str(job_root),
        }

    # Closed-loop TB reports explicit early-stop status.
    # Failed/unstable candidates should be marked as error and should not generate plots.
    early_stop_reason = ""
    early_stop_step = ""
    early_re = re.search(r"EARLY_STOP\s+step=([^\s]+)\s+reason=([^\s]+)", csim_stdout + "\n" + csim_stderr)
    if early_re is not None:
        early_stop_step = early_re.group(1)
        early_stop_reason = early_re.group(2)
        if early_stop_reason != "completed":
            return {
                "candidate_hash": cand.candidate_hash,
                "status": "error",
                "error": f"early_stop step={early_stop_step} reason={early_stop_reason}",
                "job_dir": str(job_root),
                "traj_csv_path": str(traj_path) if traj_path.exists() else "",
                "plot_png_path": "",
            }

    if not traj_path.exists():
        return {
            "candidate_hash": cand.candidate_hash,
            "status": "error",
            "error": "csim trajectory file missing",
            "job_dir": str(job_root),
        }

    try:
        u_hover = parse_u_hover(data_out)
        final_u = read_last_controls(traj_path)
        for idx, ui in enumerate(final_u):
            if abs(ui - u_hover) > 0.03:
                return {
                    "candidate_hash": cand.candidate_hash,
                    "status": "error",
                    "error": f"final_control_not_hover u{idx}={ui:.6g} u_hover={u_hover:.6g}",
                    "job_dir": str(job_root),
                    "traj_csv_path": str(traj_path),
                    "plot_png_path": "",
                }

        q_line = "Qdiag=[" + ", ".join(f"{v:.3g}" for v in cand.q_diag) + "]"
        params = [
            f"f_model={cand.freq_hz:g}Hz, rho={cand.rho}, horizon={cand.horizon}, admm_iters={cand.admm_iters}",
            f"r_scale={cand.r_scale:.6g}, sim_freq={cand.sim_freq:g}Hz, sim_T={cand.sim_duration_s:g}s",
            f"step=[{cand.step_x:.3g}, {cand.step_y:.3g}, {cand.step_z:.3g}, yaw={cand.step_yaw:.3g}]",
            q_line,
        ]
        final_x0 = generate_trajectory_plot(
            csv_path=traj_path,
            png_path=plot_path,
            title=f"f={cand.freq_hz:g}Hz, rho={cand.rho}, hash={cand.candidate_hash[:10]}",
            param_lines=params,
        )
        return {
            "candidate_hash": cand.candidate_hash,
            "status": "ok",
            "error": "",
            "job_dir": str(job_root),
            "traj_csv_path": str(traj_path),
            "plot_png_path": str(plot_path),
            "rise_time_s": math.nan,
            "settling_time_s": math.nan,
            "overshoot_pct": math.nan,
            "iae": math.nan,
            "control_effort_l1": math.nan,
            "final_x0": final_x0,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "candidate_hash": cand.candidate_hash,
            "status": "error",
            "error": f"trajectory/plot parse failed: {exc}",
            "job_dir": str(job_root),
        }


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    out: dict[str, dict[str, Any]] = {}
    with path.open("r", newline="") as f:
        for row in csv.DictReader(f):
            h = row.get("candidate_hash", "")
            if not h:
                continue
            out[h] = {
                "candidate_hash": h,
                "status": row.get("status", ""),
                "error": row.get("error", ""),
                "job_dir": row.get("job_dir", ""),
                "rise_time_s": float_or_nan(row.get("rise_time_s")),
                "settling_time_s": float_or_nan(row.get("settling_time_s")),
                "overshoot_pct": float_or_nan(row.get("overshoot_pct")),
                "iae": float_or_nan(row.get("iae")),
                "control_effort_l1": float_or_nan(row.get("control_effort_l1")),
                "final_x0": float_or_nan(row.get("final_x0")),
                "traj_csv_path": row.get("traj_csv_path", ""),
                "plot_png_path": row.get("plot_png_path", ""),
                "freq_hz": float_or_nan(row.get("freq_hz")),
                "rho": int(float(row.get("rho", "0") or 0)),
                "horizon": int(float(row.get("horizon", "0") or 0)),
                "admm_iters": int(float(row.get("admm_iters", "0") or 0)),
                "r_scale": float_or_nan(row.get("r_scale")),
                "q_diag_json": row.get("q_diag_json", ""),
            }
    return out


def write_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    fieldnames = [
        "candidate_hash",
        "status",
        "error",
        "job_dir",
        "freq_hz",
        "rho",
        "horizon",
        "admm_iters",
        "q_diag_json",
        "r_scale",
        "rise_time_s",
        "settling_time_s",
        "overshoot_pct",
        "iae",
        "control_effort_l1",
        "final_x0",
        "traj_csv_path",
        "plot_png_path",
    ]
    rows = sorted(cache.values(), key=lambda r: r["candidate_hash"])
    write_csv(path, rows, fieldnames)


def evaluate_candidates_parallel(
    *,
    candidates: list[CandidateEval],
    cache: dict[str, dict[str, Any]],
    repo_root: Path,
    run_root: Path,
    jobs: int,
    retry_errors: bool,
    continue_on_error: bool,
    on_result: Callable[[CandidateEval, dict[str, Any]], None] | None = None,
) -> dict[str, dict[str, Any]]:
    unique: dict[str, CandidateEval] = {c.candidate_hash: c for c in candidates}
    to_run: list[CandidateEval] = []

    for h, c in unique.items():
        cached = cache.get(h)
        if cached is None:
            to_run.append(c)
            continue
        if cached.get("status") == "ok":
            continue
        if cached.get("status") == "error" and retry_errors:
            to_run.append(c)

    total_requested = len(candidates)
    total_unique = len(unique)
    if to_run:
        print(
            f"Evaluating {len(to_run)} unique candidates with {jobs} workers "
            f"(requested={total_requested}, unique={total_unique})..."
        )
    else:
        print(
            f"No new candidates to evaluate "
            f"(requested={total_requested}, unique={total_unique}, all cached)."
        )

    tasks = [(c, str(repo_root), str(run_root)) for c in to_run]
    def store_result(result: dict[str, Any], source: CandidateEval, elapsed_s: float) -> None:
        h = result["candidate_hash"]
        cache[h] = {
            "candidate_hash": h,
            "status": result.get("status", "error"),
            "error": result.get("error", ""),
            "job_dir": result.get("job_dir", ""),
            "freq_hz": source.freq_hz,
            "rho": source.rho,
            "horizon": source.horizon,
            "admm_iters": source.admm_iters,
            "q_diag_json": json.dumps(list(source.q_diag)),
            "r_scale": source.r_scale,
            "rise_time_s": float_or_nan(result.get("rise_time_s")),
            "settling_time_s": float_or_nan(result.get("settling_time_s")),
            "overshoot_pct": float_or_nan(result.get("overshoot_pct")),
            "iae": float_or_nan(result.get("iae")),
            "control_effort_l1": float_or_nan(result.get("control_effort_l1")),
            "final_x0": float_or_nan(result.get("final_x0")),
            "traj_csv_path": result.get("traj_csv_path", ""),
            "plot_png_path": result.get("plot_png_path", ""),
        }
        status = cache[h]["status"]
        if status == "ok":
            print(f"[ok] {h[:12]} f={source.freq_hz:g}Hz ({elapsed_s:.1f}s)")
        else:
            print(f"[error] {h[:12]} ({elapsed_s:.1f}s): {cache[h]['error']}")
            if not continue_on_error:
                raise RuntimeError(f"Candidate {h} failed: {cache[h]['error']}")
        if on_result is not None:
            on_result(source, cache[h])

    if jobs == 1:
        for idx, task in enumerate(tasks, start=1):
            source = task[0]
            print(
                f"[start {idx}/{len(tasks)}] {source.candidate_hash[:12]} "
                f"f={source.freq_hz:g}Hz r={source.r_scale:.6g}"
            )
            t0 = time.monotonic()
            result = evaluate_candidate(task)
            store_result(result, source, time.monotonic() - t0)
    else:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            future_to_source: dict[Any, tuple[CandidateEval, float]] = {}
            for task in tasks:
                fut = ex.submit(evaluate_candidate, task)
                future_to_source[fut] = (task[0], time.monotonic())
            for fut in as_completed(future_to_source):
                source, started = future_to_source[fut]
                result = fut.result()
                store_result(result, source, time.monotonic() - started)

    return cache


def build_stage1_candidates(
    *,
    freq_hz: float,
    base_q: tuple[float, ...],
    base_r: float,
    factors: list[float],
    eval_template: dict[str, Any],
) -> tuple[list[StageCandidate], list[CandidateEval]]:
    stage_rows: list[StageCandidate] = []
    evals: list[CandidateEval] = []

    for dim_idx in range(Q_DIM):
        for factor in factors:
            q = list(base_q)
            q[dim_idx] = base_q[dim_idx] * factor
            q_t = tuple(q)
            h = candidate_hash(
                freq_hz=freq_hz,
                rho=eval_template["rho"],
                horizon=eval_template["horizon"],
                admm_iters=eval_template["admm_iters"],
                q_diag=q_t,
                r_scale=base_r,
                sim_freq=eval_template["sim_freq"],
                sim_duration_s=eval_template["sim_duration_s"],
                step_x=eval_template["step_x"],
                step_y=eval_template["step_y"],
                step_z=eval_template["step_z"],
                step_yaw=eval_template["step_yaw"],
                rise_lo=eval_template["rise_lo"],
                rise_hi=eval_template["rise_hi"],
                settle_pct=eval_template["settle_pct"],
            )
            stage_rows.append(
                StageCandidate(
                    stage="stage1",
                    candidate_hash=h,
                    freq_hz=freq_hz,
                    r_scale=base_r,
                    q_diag=q_t,
                    sweep_kind="q_dim",
                    dim_idx=dim_idx,
                    factor=factor,
                )
            )
            evals.append(
                CandidateEval(
                    candidate_hash=h,
                    freq_hz=freq_hz,
                    rho=eval_template["rho"],
                    horizon=eval_template["horizon"],
                    admm_iters=eval_template["admm_iters"],
                    q_diag=q_t,
                    r_scale=base_r,
                    sim_freq=eval_template["sim_freq"],
                    sim_duration_s=eval_template["sim_duration_s"],
                    step_x=eval_template["step_x"],
                    step_y=eval_template["step_y"],
                    step_z=eval_template["step_z"],
                    step_yaw=eval_template["step_yaw"],
                    rise_lo=eval_template["rise_lo"],
                    rise_hi=eval_template["rise_hi"],
                    settle_pct=eval_template["settle_pct"],
                    candidate_timeout_s=eval_template["candidate_timeout_s"],
                    heartbeat_s=eval_template["heartbeat_s"],
                    enable_heartbeat=bool(eval_template["enable_heartbeat"]),
                )
            )

    for factor in factors:
        r_val = base_r * factor
        h = candidate_hash(
            freq_hz=freq_hz,
            rho=eval_template["rho"],
            horizon=eval_template["horizon"],
            admm_iters=eval_template["admm_iters"],
            q_diag=base_q,
            r_scale=r_val,
            sim_freq=eval_template["sim_freq"],
            sim_duration_s=eval_template["sim_duration_s"],
            step_x=eval_template["step_x"],
            step_y=eval_template["step_y"],
            step_z=eval_template["step_z"],
            step_yaw=eval_template["step_yaw"],
            rise_lo=eval_template["rise_lo"],
            rise_hi=eval_template["rise_hi"],
            settle_pct=eval_template["settle_pct"],
        )
        stage_rows.append(
            StageCandidate(
                stage="stage1",
                candidate_hash=h,
                freq_hz=freq_hz,
                r_scale=r_val,
                q_diag=base_q,
                sweep_kind="r_scale",
                dim_idx=-1,
                factor=factor,
            )
        )
        evals.append(
            CandidateEval(
                candidate_hash=h,
                freq_hz=freq_hz,
                rho=eval_template["rho"],
                horizon=eval_template["horizon"],
                admm_iters=eval_template["admm_iters"],
                q_diag=base_q,
                r_scale=r_val,
                sim_freq=eval_template["sim_freq"],
                sim_duration_s=eval_template["sim_duration_s"],
                step_x=eval_template["step_x"],
                step_y=eval_template["step_y"],
                step_z=eval_template["step_z"],
                step_yaw=eval_template["step_yaw"],
                rise_lo=eval_template["rise_lo"],
                rise_hi=eval_template["rise_hi"],
                settle_pct=eval_template["settle_pct"],
                candidate_timeout_s=eval_template["candidate_timeout_s"],
                heartbeat_s=eval_template["heartbeat_s"],
                enable_heartbeat=bool(eval_template["enable_heartbeat"]),
            )
        )

    return stage_rows, evals


def stage_rows_to_csv_rows(
    stage_rows: list[StageCandidate],
    cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, sc in enumerate(stage_rows, start=1):
        cached = cache.get(sc.candidate_hash, {})
        out.append(
            {
                "run_idx": idx,
                "stage": sc.stage,
                "sweep_kind": sc.sweep_kind,
                "dim_idx": sc.dim_idx,
                "factor": sc.factor,
                "candidate_hash": sc.candidate_hash,
                "freq_hz": sc.freq_hz,
                "r_scale": sc.r_scale,
                "q_diag_json": json.dumps(list(sc.q_diag)),
                "rise_time_s": float_or_nan(cached.get("rise_time_s")),
                "settling_time_s": float_or_nan(cached.get("settling_time_s")),
                "overshoot_pct": float_or_nan(cached.get("overshoot_pct")),
                "iae": float_or_nan(cached.get("iae")),
                "control_effort_l1": float_or_nan(cached.get("control_effort_l1")),
                "traj_csv_path": cached.get("traj_csv_path", ""),
                "plot_png_path": cached.get("plot_png_path", ""),
                "score": math.nan,
                "rank": "",
                "status": cached.get("status", "error"),
                "error": cached.get("error", "missing cache row"),
                "job_dir": cached.get("job_dir", ""),
            }
        )
    compute_scores(out)
    return out


def choose_stage2_seed(stage1_csv_rows: list[dict[str, Any]], base_q: tuple[float, ...], base_r: float) -> tuple[tuple[float, ...], float, list[int]]:
    best_factor_by_dim: dict[int, float] = {i: 1.0 for i in range(Q_DIM)}
    sensitivity_by_dim: dict[int, float] = {i: 0.0 for i in range(Q_DIM)}

    for i in range(Q_DIM):
        rows = [r for r in stage1_csv_rows if r["status"] == "ok" and r["sweep_kind"] == "q_dim" and int(r["dim_idx"]) == i]
        finite_rows = [r for r in rows if math.isfinite(float_or_nan(r.get("score")))]
        if not finite_rows:
            continue
        best = min(finite_rows, key=lambda r: float(r["score"]))
        best_factor_by_dim[i] = float(best["factor"])
        scores = [float(r["score"]) for r in finite_rows]
        sensitivity_by_dim[i] = max(scores) - min(scores)

    r_rows = [r for r in stage1_csv_rows if r["status"] == "ok" and r["sweep_kind"] == "r_scale"]
    finite_r_rows = [r for r in r_rows if math.isfinite(float_or_nan(r.get("score")))]
    best_r_factor = 1.0
    if finite_r_rows:
        best_r_factor = float(min(finite_r_rows, key=lambda r: float(r["score"]))["factor"])

    q_seed = list(base_q)
    for i in range(Q_DIM):
        q_seed[i] = base_q[i] * best_factor_by_dim[i]
    r_seed = base_r * best_r_factor

    ranked_dims = sorted(range(Q_DIM), key=lambda i: sensitivity_by_dim[i], reverse=True)
    return tuple(q_seed), r_seed, ranked_dims


def build_stage2_candidates(
    *,
    freq_hz: float,
    q_seed: tuple[float, ...],
    r_seed: float,
    ranked_dims: list[int],
    top_dims: int,
    stage2_factors: list[float],
    eval_template: dict[str, Any],
) -> tuple[list[StageCandidate], list[CandidateEval]]:
    active_dims = ranked_dims[:top_dims]
    stage_rows: list[StageCandidate] = []
    evals: list[CandidateEval] = []

    for combo in itertools.product(stage2_factors, repeat=top_dims + 1):
        q_factors = combo[:top_dims]
        r_factor = combo[-1]
        q = list(q_seed)
        for dim_idx, factor in zip(active_dims, q_factors):
            q[dim_idx] = q_seed[dim_idx] * factor
        q_t = tuple(q)
        r_val = r_seed * r_factor

        h = candidate_hash(
            freq_hz=freq_hz,
            rho=eval_template["rho"],
            horizon=eval_template["horizon"],
            admm_iters=eval_template["admm_iters"],
            q_diag=q_t,
            r_scale=r_val,
            sim_freq=eval_template["sim_freq"],
            sim_duration_s=eval_template["sim_duration_s"],
            step_x=eval_template["step_x"],
            step_y=eval_template["step_y"],
            step_z=eval_template["step_z"],
            step_yaw=eval_template["step_yaw"],
            rise_lo=eval_template["rise_lo"],
            rise_hi=eval_template["rise_hi"],
            settle_pct=eval_template["settle_pct"],
        )
        stage_rows.append(
            StageCandidate(
                stage="stage2",
                candidate_hash=h,
                freq_hz=freq_hz,
                r_scale=r_val,
                q_diag=q_t,
                sweep_kind="local_cartesian",
                dim_idx=-1,
                factor=1.0,
            )
        )
        evals.append(
            CandidateEval(
                candidate_hash=h,
                freq_hz=freq_hz,
                rho=eval_template["rho"],
                horizon=eval_template["horizon"],
                admm_iters=eval_template["admm_iters"],
                q_diag=q_t,
                r_scale=r_val,
                sim_freq=eval_template["sim_freq"],
                sim_duration_s=eval_template["sim_duration_s"],
                step_x=eval_template["step_x"],
                step_y=eval_template["step_y"],
                step_z=eval_template["step_z"],
                step_yaw=eval_template["step_yaw"],
                rise_lo=eval_template["rise_lo"],
                rise_hi=eval_template["rise_hi"],
                settle_pct=eval_template["settle_pct"],
                candidate_timeout_s=eval_template["candidate_timeout_s"],
                heartbeat_s=eval_template["heartbeat_s"],
                enable_heartbeat=bool(eval_template["enable_heartbeat"]),
            )
        )

    return stage_rows, evals


def main() -> None:
    parser = argparse.ArgumentParser(description="Parallel HLS csim sweep for Q diag + R scalar + frequency.")
    parser.add_argument("--freq-values", default=",".join(str(v) for v in DEFAULT_FREQ_VALUES))
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 1, DEFAULT_MAX_WORKERS))
    parser.add_argument("--jobs-per-freq", type=int, default=0, help="If >0, cap workers used per frequency.")
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--admm-iters", type=int, default=28)
    parser.add_argument("--rho", type=int, default=64)
    parser.add_argument("--sim-freq", type=float, default=200.0)
    parser.add_argument("--sim-duration-s", type=float, default=10.0)
    parser.add_argument("--step-x", type=float, default=2.0)
    parser.add_argument("--step-y", type=float, default=0.0)
    parser.add_argument("--step-z", type=float, default=0.0)
    parser.add_argument("--step-yaw", type=float, default=0.1)
    parser.add_argument("--rise-lo", type=float, default=0.1)
    parser.add_argument("--rise-hi", type=float, default=0.9)
    parser.add_argument("--settle-pct", type=float, default=0.02)
    parser.add_argument("--stage1-factors", default=",".join(str(v) for v in DEFAULT_STAGE1_FACTORS))
    parser.add_argument("--stage2-factors", default=",".join(str(v) for v in DEFAULT_STAGE2_FACTORS))
    parser.add_argument("--stage2-top-dims", type=int, default=4)
    parser.add_argument(
        "--candidate-timeout-s",
        type=float,
        default=1800.0,
        help="Timeout per csim candidate in seconds (<=0 disables).",
    )
    parser.add_argument(
        "--heartbeat-s",
        type=float,
        default=30.0,
        help="Heartbeat interval while csim candidate is running.",
    )
    parser.add_argument("--output-dir", default="plots/hls_csim_qr_freq")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    if args.jobs <= 0:
        raise ValueError("--jobs must be > 0")
    if args.jobs_per_freq < 0:
        raise ValueError("--jobs-per-freq must be >= 0")
    if args.stage2_top_dims <= 0 or args.stage2_top_dims > Q_DIM:
        raise ValueError(f"--stage2-top-dims must be in [1, {Q_DIM}]")
    if args.rho <= 0 or (args.rho & (args.rho - 1)):
        raise ValueError("--rho must be a power of 2 > 0")
    if args.horizon <= 0 or args.admm_iters <= 0:
        raise ValueError("--horizon and --admm-iters must be > 0")
    if args.sim_freq <= 0 or args.sim_duration_s <= 0:
        raise ValueError("--sim-freq and --sim-duration-s must be > 0")
    if not (0.0 < args.rise_lo < args.rise_hi < 1.0):
        raise ValueError("--rise-lo/--rise-hi must satisfy 0 < rise-lo < rise-hi < 1")
    if args.settle_pct <= 0:
        raise ValueError("--settle-pct must be > 0")
    if args.heartbeat_s <= 0:
        raise ValueError("--heartbeat-s must be > 0")

    freq_values = parse_float_list(args.freq_values, "--freq-values")
    stage1_factors = parse_float_list(args.stage1_factors, "--stage1-factors")
    stage2_factors = parse_float_list(args.stage2_factors, "--stage2-factors")
    if any(v <= 0 for v in freq_values + stage1_factors + stage2_factors):
        raise ValueError("All frequencies/factors must be > 0")
    if all(abs(v - 1.0) < 1e-12 for v in stage1_factors):
        print("WARNING: --stage1-factors are all 1, so Stage 1 explores no variation.")
    if all(abs(v - 1.0) < 1e-12 for v in stage2_factors):
        print("WARNING: --stage2-factors are all 1, so Stage 2 explores no variation.")

    est_steps = int(round(args.sim_freq * args.sim_duration_s))
    est_work = est_steps * args.admm_iters
    if est_work >= 50000:
        print(
            "WARNING: Heavy csim workload per candidate "
            f"(steps={est_steps}, admm_iters={args.admm_iters}, steps*iters={est_work}). "
            "Consider reducing --sim-duration-s and/or --sim-freq for grid search."
        )

    repo_root = Path(__file__).resolve().parents[1]
    out_root = (repo_root / args.output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    run_root = (repo_root / "build" / "tune_runs" / datetime.now().strftime("%Y%m%d_%H%M%S")).resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    cache_csv = out_root / "candidate_cache.csv"
    cache = load_cache(cache_csv)

    eval_template = {
        "rho": args.rho,
        "horizon": args.horizon,
        "admm_iters": args.admm_iters,
        "sim_freq": args.sim_freq,
        "sim_duration_s": args.sim_duration_s,
        "step_x": args.step_x,
        "step_y": args.step_y,
        "step_z": args.step_z,
        "step_yaw": args.step_yaw,
        "rise_lo": args.rise_lo,
        "rise_hi": args.rise_hi,
        "settle_pct": args.settle_pct,
        "candidate_timeout_s": args.candidate_timeout_s,
        "heartbeat_s": args.heartbeat_s,
        "enable_heartbeat": True,
    }

    stage_fieldnames = [
        "run_idx",
        "stage",
        "sweep_kind",
        "dim_idx",
        "factor",
        "candidate_hash",
        "freq_hz",
        "r_scale",
        "q_diag_json",
        "rise_time_s",
        "settling_time_s",
        "overshoot_pct",
        "iae",
        "control_effort_l1",
        "traj_csv_path",
        "plot_png_path",
        "score",
        "rank",
        "status",
        "error",
        "job_dir",
    ]

    freq_summary_rows: list[dict[str, Any]] = []
    all_stage2_rows: list[dict[str, Any]] = []

    for freq_hz in freq_values:
        freq_slug = f"f{freq_hz:.6g}".replace(".", "p")
        freq_dir = out_root / freq_slug
        freq_dir.mkdir(parents=True, exist_ok=True)
        stage1_csv = freq_dir / "stage1_metrics.csv"
        stage2_csv = freq_dir / "stage2_metrics.csv"

        jobs = args.jobs_per_freq if args.jobs_per_freq > 0 else args.jobs
        eval_template["enable_heartbeat"] = jobs == 1
        print(f"\n=== Frequency {freq_hz:.6g} Hz | workers={jobs} ===")

        base_q = tuple(BASE_Q_DIAG)
        base_r = BASE_R_SCALE

        stage1_specs, stage1_evals = build_stage1_candidates(
            freq_hz=freq_hz,
            base_q=base_q,
            base_r=base_r,
            factors=stage1_factors,
            eval_template=eval_template,
        )
        cache = evaluate_candidates_parallel(
            candidates=stage1_evals,
            cache=cache,
            repo_root=repo_root,
            run_root=run_root,
            jobs=jobs,
            retry_errors=args.retry_errors,
            continue_on_error=args.continue_on_error,
        )
        write_cache(cache_csv, cache)

        stage1_rows = stage_rows_to_csv_rows(stage1_specs, cache)
        write_csv(stage1_csv, stage1_rows, stage_fieldnames)

        q_seed, r_seed, ranked_dims = choose_stage2_seed(stage1_rows, base_q, base_r)
        stage2_specs, stage2_evals = build_stage2_candidates(
            freq_hz=freq_hz,
            q_seed=q_seed,
            r_seed=r_seed,
            ranked_dims=ranked_dims,
            top_dims=args.stage2_top_dims,
            stage2_factors=stage2_factors,
            eval_template=eval_template,
        )
        cache = evaluate_candidates_parallel(
            candidates=stage2_evals,
            cache=cache,
            repo_root=repo_root,
            run_root=run_root,
            jobs=jobs,
            retry_errors=args.retry_errors,
            continue_on_error=args.continue_on_error,
        )
        write_cache(cache_csv, cache)

        stage2_rows = stage_rows_to_csv_rows(stage2_specs, cache)
        write_csv(stage2_csv, stage2_rows, stage_fieldnames)
        all_stage2_rows.extend(stage2_rows)

        ok_ranked = [
            r for r in stage2_rows
            if r.get("status") == "ok" and math.isfinite(float_or_nan(r.get("score")))
        ]
        if ok_ranked:
            best = min(ok_ranked, key=lambda r: float(r["score"]))
            freq_summary_rows.append(
                {
                    "freq_hz": freq_hz,
                    "candidate_hash": best["candidate_hash"],
                    "score": best["score"],
                    "rise_time_s": best["rise_time_s"],
                    "settling_time_s": best["settling_time_s"],
                    "overshoot_pct": best["overshoot_pct"],
                    "iae": best["iae"],
                    "control_effort_l1": best["control_effort_l1"],
                    "r_scale": best["r_scale"],
                    "q_diag_json": best["q_diag_json"],
                    "stage2_csv": str(stage2_csv.relative_to(repo_root)),
                }
            )
            print(f"Best @ {freq_hz:.6g} Hz: score={float(best['score']):.6f}")
        else:
            freq_summary_rows.append(
                {
                    "freq_hz": freq_hz,
                    "candidate_hash": "",
                    "score": math.nan,
                    "rise_time_s": math.nan,
                    "settling_time_s": math.nan,
                    "overshoot_pct": math.nan,
                    "iae": math.nan,
                    "control_effort_l1": math.nan,
                    "r_scale": math.nan,
                    "q_diag_json": "",
                    "stage2_csv": str(stage2_csv.relative_to(repo_root)),
                }
            )
            print(f"No valid stage2 candidates for {freq_hz:.6g} Hz")

    freq_summary_csv = out_root / "frequency_summary.csv"
    freq_summary_fields = [
        "freq_hz",
        "candidate_hash",
        "score",
        "rise_time_s",
        "settling_time_s",
        "overshoot_pct",
        "iae",
        "control_effort_l1",
        "r_scale",
        "q_diag_json",
        "stage2_csv",
    ]
    write_csv(freq_summary_csv, freq_summary_rows, freq_summary_fields)

    best_candidates_csv = out_root / "best_candidates.csv"
    all_ok = [
        r for r in all_stage2_rows
        if r.get("status") == "ok" and math.isfinite(float_or_nan(r.get("score")))
    ]
    all_ok_sorted = sorted(all_ok, key=lambda r: float(r["score"]))
    best_fields = [
        "rank_global",
        "candidate_hash",
        "freq_hz",
        "score",
        "rise_time_s",
        "settling_time_s",
        "overshoot_pct",
        "iae",
        "control_effort_l1",
        "r_scale",
        "q_diag_json",
    ]
    best_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(all_ok_sorted[:50], start=1):
        best_rows.append(
            {
                "rank_global": idx,
                "candidate_hash": row["candidate_hash"],
                "freq_hz": row["freq_hz"],
                "score": row["score"],
                "rise_time_s": row["rise_time_s"],
                "settling_time_s": row["settling_time_s"],
                "overshoot_pct": row["overshoot_pct"],
                "iae": row["iae"],
                "control_effort_l1": row["control_effort_l1"],
                "r_scale": row["r_scale"],
                "q_diag_json": row["q_diag_json"],
            }
        )
    write_csv(best_candidates_csv, best_rows, best_fields)

    print("\nDone.")
    print(f"- run root: {run_root}")
    print(f"- cache: {cache_csv}")
    print(f"- frequency summary: {freq_summary_csv}")
    print(f"- best candidates: {best_candidates_csv}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print("FATAL:", exc)
        print(traceback.format_exc())
        raise
