#!/usr/bin/env python3
"""
Automated FPGA benchmark sweep for ADMM per-iteration timing vs horizon.

For each horizon:
1) regenerate headers with selected horizon and ADMM_ITERS
2) build/program the FPGA (Arty/UART flow)
3) query FPGA over UART and read timer cycles (u3 replaced by timer in benchmark mode)
4) convert total cycles to per-iteration us and emit TinyMPC-compatible BENCH_CSV lines
"""

from __future__ import annotations

import argparse
import csv
import struct
import subprocess
from pathlib import Path

import serial


N_STATE = 12
N_WORDS_OUT = 4
FRAC_BITS = 22
DEFAULT_HORIZONS = [10, 20, 30, 40, 50, 60, 70, 80]


def float_to_fixed(val: float) -> int:
    return int(val * (2**FRAC_BITS)) & 0xFFFFFFFF


def run_cmd(cmd: list[str], cwd: Path) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def send_state(ser: serial.Serial, state: list[float]) -> None:
    ser.write(bytes([0xFF]))
    for val in state:
        ser.write(struct.pack("<I", float_to_fixed(val)))


def receive_words(ser: serial.Serial, n_words: int) -> list[int]:
    words: list[int] = []
    for idx in range(n_words):
        data = ser.read(4)
        if len(data) != 4:
            raise TimeoutError(f"UART timeout while reading output word {idx}")
        words.append(struct.unpack("<I", data)[0])
    return words


def measure_cycles(
    ser: serial.Serial,
    samples: int,
    state: list[float],
) -> list[int]:
    measured_cycles: list[int] = []
    for _ in range(samples):
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        send_state(ser, state)
        words = receive_words(ser, N_WORDS_OUT)
        measured_cycles.append(words[3])  # u3 replaced by cycle counter in benchmark mode
    return measured_cycles


def parse_horizons(text: str) -> list[int]:
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError("No horizons parsed from --horizons")
    if any(v <= 0 for v in vals):
        raise ValueError("All horizons must be > 0")
    return vals


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FPGA ADMM horizon timing sweep.")
    parser.add_argument("--port", default="/dev/ttyUSB1", help="UART serial port.")
    parser.add_argument("--baud", type=int, default=921600, help="UART baud rate.")
    parser.add_argument("--board", default="arty", help="Make BOARD target.")
    parser.add_argument("--admm-iters", type=int, default=10, help="ADMM iterations compiled in hardware.")
    parser.add_argument("--samples", type=int, default=1, help="Samples per horizon.")
    parser.add_argument(
        "--horizons",
        default=",".join(str(h) for h in DEFAULT_HORIZONS),
        help="Comma-separated horizon list (e.g. 10,20,30).",
    )
    parser.add_argument("--clk-hz", type=float, default=100_000_000.0, help="FPGA clock for cycle->time conversion.")
    parser.add_argument("--budget-us", type=float, default=2000.0, help="Timing budget used to count misses.")
    parser.add_argument("--uart-timeout", type=float, default=5.0, help="UART timeout in seconds.")
    parser.add_argument(
        "--output-log",
        default="plots/fpga_res.csv",
        help="Output text file with TinyMPC-compatible BENCH_CSV lines.",
    )
    parser.add_argument(
        "--output-raw",
        default="plots/fpga_raw_cycles.csv",
        help="Output CSV with raw cycles/us values per sample.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue with next horizon if one horizon fails.",
    )
    args = parser.parse_args()

    if args.admm_iters <= 0:
        raise ValueError("--admm-iters must be > 0")
    if args.samples <= 0:
        raise ValueError("--samples must be > 0")

    horizons = parse_horizons(args.horizons)

    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    output_log = repo_root / args.output_log
    output_raw = repo_root / args.output_raw
    output_log.parent.mkdir(parents=True, exist_ok=True)
    output_raw.parent.mkdir(parents=True, exist_ok=True)

    state = [0.0] * N_STATE
    state[0] = 2.0

    # Initialize output files once so progress is persisted incrementally.
    output_log.write_text("")
    with output_raw.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "horizon",
                "sample_idx",
                "admm_iters",
                "cycles_total",
                "total_us",
                "per_iter_us",
            ],
        )
        writer.writeheader()

    for horizon in horizons:
        print(f"\n=== Horizon {horizon} ===")
        try:
            run_cmd(
                [
                    "python3",
                    str(scripts_dir / "header_generator.py"),
                    "--horizon",
                    str(horizon),
                    "--admm-iters",
                    str(args.admm_iters),
                ],
                cwd=repo_root,
            )
            run_cmd(["make", f"BOARD={args.board}", "bit"], cwd=repo_root)
            run_cmd(["make", f"BOARD={args.board}", "program"], cwd=repo_root)

            with serial.Serial(
                port=args.port,
                baudrate=args.baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=args.uart_timeout,
            ) as ser:
                cycles_list = measure_cycles(ser=ser, samples=args.samples, state=state)
                total_us_list = [(cycles * 1e6) / args.clk_hz for cycles in cycles_list]
                per_iter_us_list = [total_us / args.admm_iters for total_us in total_us_list]

            with output_raw.open("a", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "horizon",
                        "sample_idx",
                        "admm_iters",
                        "cycles_total",
                        "total_us",
                        "per_iter_us",
                    ],
                )
                for idx, (cycles, total_us, per_iter_us) in enumerate(
                    zip(cycles_list, total_us_list, per_iter_us_list)
                ):
                    writer.writerow(
                        {
                            "horizon": horizon,
                            "sample_idx": idx,
                            "admm_iters": args.admm_iters,
                            "cycles_total": cycles,
                            "total_us": total_us,
                            "per_iter_us": per_iter_us,
                        }
                    )

            # BENCH_CSV must store total solve time for the configured iter count,
            # matching TinyMPC semantics. Per-iter values remain in raw CSV.
            min_us = min(total_us_list)
            avg_us = sum(total_us_list) / len(total_us_list)
            max_us = max(total_us_list)
            misses = sum(1 for t_us in total_us_list if t_us > args.budget_us)
            solved = args.samples - misses
            line = (
                f"FPGA-ADMM: BENCH_CSV,{horizon},{args.admm_iters},"
                f"{min_us:.3f},{avg_us:.3f},{max_us:.3f},"
                f"{misses},{args.samples},{solved},0,0,0"
            )
            with output_log.open("a") as f:
                f.write(line + "\n")
            print(line)
        except Exception as exc:
            print(f"ERROR at horizon {horizon}: {exc}")
            if not args.continue_on_error:
                raise

    print(f"\nSaved BENCH_CSV lines to {output_log}")
    print(f"Saved raw cycle samples to {output_raw}")


if __name__ == "__main__":
    main()
