#!/usr/bin/env python3
"""
UART hardware-in-the-loop closed-loop simulation for the ADMM controller.
"""

from __future__ import annotations

import argparse
import csv
import struct
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import serial

from crazyloihimodel import CrazyLoihiModel


N_STATE = 12
N_VAR = 4
FRAC_BITS = 22


def float_to_fixed(val: float) -> int:
    return int(val * (2**FRAC_BITS)) & 0xFFFFFFFF


def fixed_to_float(val: int) -> float:
    if val & 0x80000000:
        val -= 0x100000000
    return float(val) / (2**FRAC_BITS)


def send_vector(ser: serial.Serial, vector: np.ndarray) -> None:
    ser.write(bytes([0xFF]))
    for val in vector:
        ser.write(struct.pack("<I", float_to_fixed(float(val))))


def receive_vector(ser: serial.Serial, n_words: int) -> np.ndarray:
    out = np.zeros(n_words, dtype=float)
    for idx in range(n_words):
        data = ser.read(4)
        if len(data) != 4:
            raise TimeoutError(f"UART timeout while reading output word {idx}")
        out[idx] = fixed_to_float(struct.unpack("<I", data)[0])
    return out


def run_closed_loop(
    ser: serial.Serial,
    model: CrazyLoihiModel,
    state0: np.ndarray,
    sim_steps: int,
    verbose: bool,
    max_runtime_s: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t_start = time.monotonic()
    state = state0.copy()
    control = np.copy(model.hover_thrust)

    state_hist = [state.copy()]
    control_hist = [control.copy()]

    for step_idx in range(sim_steps):
        if max_runtime_s is not None and (time.monotonic() - t_start) > max_runtime_s:
            raise TimeoutError(f"Exceeded max runtime ({max_runtime_s:.1f}s) at step {step_idx}/{sim_steps}")
        send_vector(ser, state)
        # Hardware output already includes hover thrust offset (U_HOVER in ADMM.cpp).
        control = receive_vector(ser, N_VAR)
        state = model.step(state, control)
        state_hist.append(state.copy())
        control_hist.append(control.copy())
        if verbose:
            print(f"step={step_idx+1}/{sim_steps} pos={state[:3]} u={control}")

    dt = 1.0 / model.freq
    t_axis = np.arange(sim_steps + 1) * dt
    return t_axis, np.array(state_hist), np.array(control_hist)


def save_results_csv(path: Path, time: np.ndarray, state_hist: np.ndarray, control_hist: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["t"]
            + [f"x{i}" for i in range(state_hist.shape[1])]
            + [f"u{i}" for i in range(control_hist.shape[1])]
        )
        for idx in range(len(time)):
            writer.writerow([time[idx], *state_hist[idx].tolist(), *control_hist[idx].tolist()])


def plot_results(time: np.ndarray, state_hist: np.ndarray, control_hist: np.ndarray, title: str) -> plt.Figure:
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 0.7], hspace=0.3)

    ax_pos = fig.add_subplot(gs[0, 0])
    ax_pos.plot(time, state_hist[:, 0:3])
    ax_pos.set_title("Position [x y z]")
    ax_pos.set_ylabel("m")
    ax_pos.legend(["x", "y", "z"])
    ax_pos.grid(True)

    ax_att = fig.add_subplot(gs[0, 1])
    ax_att.plot(time, state_hist[:, 3:6])
    ax_att.set_title("Orientation [roll pitch yaw]")
    ax_att.set_ylabel("rad")
    ax_att.legend(["roll", "pitch", "yaw"])
    ax_att.grid(True)

    ax_vel = fig.add_subplot(gs[1, 0])
    ax_vel.plot(time, state_hist[:, 6:9])
    ax_vel.set_title("Linear Velocity")
    ax_vel.set_ylabel("m/s")
    ax_vel.legend(["vx", "vy", "vz"])
    ax_vel.grid(True)

    ax_angvel = fig.add_subplot(gs[1, 1])
    ax_angvel.plot(time, state_hist[:, 9:12])
    ax_angvel.set_title("Angular Velocity")
    ax_angvel.set_ylabel("rad/s")
    ax_angvel.legend(["wx", "wy", "wz"])
    ax_angvel.grid(True)

    ax_u = fig.add_subplot(gs[2, :])
    ax_u.plot(time, control_hist)
    ax_u.set_title("Control Inputs")
    ax_u.set_xlabel("Time [s]")
    ax_u.set_ylabel("Control")
    ax_u.legend([f"u{i}" for i in range(control_hist.shape[1])])
    ax_u.grid(True)

    if title:
        fig.suptitle(title)
        fig.tight_layout(rect=[0, 0, 1, 0.97])
    else:
        fig.tight_layout()
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FPGA hardware-in-the-loop simulation and plot trajectories.")
    parser.add_argument("--port", default="/dev/ttyUSB1", help="UART serial port.")
    parser.add_argument("--baud", type=int, default=921600, help="UART baud rate.")
    parser.add_argument("--uart-timeout", type=float, default=30.0, help="UART timeout in seconds.")
    parser.add_argument("--freq", type=float, default=200.0, help="Simulation frequency [Hz].")
    parser.add_argument("--duration-s", type=float, default=10.0, help="Simulation duration [s].")
    parser.add_argument("--step-x", type=float, default=2.0, help="Initial x displacement [m].")
    parser.add_argument("--step-y", type=float, default=0.0, help="Initial y displacement [m].")
    parser.add_argument("--step-z", type=float, default=0.0, help="Initial z displacement [m].")
    parser.add_argument("--save-plot", default=None, help="Optional output path for the figure (.png).")
    parser.add_argument("--save-csv", default=None, help="Optional output CSV path with trajectory data.")
    parser.add_argument("--title", default="", help="Optional plot title.")
    parser.add_argument(
        "--max-runtime-s",
        type=float,
        default=120.0,
        help="Hard wall-clock timeout for the whole HIL run [s]. Use <=0 to disable.",
    )
    parser.add_argument("--no-show", action="store_true", help="Do not display interactive plot window.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-step prints.")
    args = parser.parse_args()

    if args.freq <= 0:
        raise ValueError("--freq must be > 0")
    if args.duration_s <= 0:
        raise ValueError("--duration-s must be > 0")
    if args.max_runtime_s == 0:
        raise ValueError("--max-runtime-s must be > 0 or negative to disable")

    max_runtime_s = args.max_runtime_s if args.max_runtime_s > 0 else None

    model = CrazyLoihiModel(freq=args.freq)
    state0 = np.zeros(N_STATE, dtype=float)
    state0[0] = args.step_x
    state0[1] = args.step_y
    state0[2] = args.step_z
    sim_steps = int(round(args.duration_s * args.freq))

    with serial.Serial(
        port=args.port,
        baudrate=args.baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=args.uart_timeout,
    ) as ser:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time, state_hist, control_hist = run_closed_loop(
            ser=ser,
            model=model,
            state0=state0,
            sim_steps=sim_steps,
            verbose=not args.quiet,
            max_runtime_s=max_runtime_s,
        )

    fig = plot_results(time=time, state_hist=state_hist, control_hist=control_hist, title=args.title)

    if args.save_plot:
        out = Path(args.save_plot)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=150)
        print(f"Saved plot: {out}")

    if args.save_csv:
        save_results_csv(Path(args.save_csv), time=time, state_hist=state_hist, control_hist=control_hist)
        print(f"Saved csv: {args.save_csv}")

    if args.no_show:
        plt.close(fig)
    else:
        plt.show()


if __name__ == "__main__":
    main()
