#!/usr/bin/env python3
"""Refresh the results-page tables after regenerating analyses."""

import argparse

from plot_benchmarks import (
    HERE, OUTPUT_DIR, BENCHMARK_SUMMARY_CSV, LABELS, DEFAULT_TINYMPC_POWER_W,
    load_rows, best_rows, f, energy_mj, edp_uj_us, attach_measured_power, comparison_latency_us,
)

def table(headers, rows):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(map(str, row)) + " |" for row in rows),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmarks-only', action='store_true',
                        help='Refresh only benchmark tables, leaving flight/numerical analyses untouched.')
    args = parser.parse_args()
    required = [OUTPUT_DIR / "flight_metrics.csv", OUTPUT_DIR / "numerical_accuracy.txt"]
    missing = [str(p) for p in required if not p.is_file()]
    if missing and not args.benchmarks_only:
        raise SystemExit("Regenerate the analyses first; missing:\n" + "\n".join(missing))

    rows = attach_measured_power(best_rows(load_rows(BENCHMARK_SUMMARY_CSV), 10))
    common = [r for r in rows if int(f(r, "horizon")) == 40]
    benchmark = table(
        ["H40 / 10 iterations", "Solve (ms)", "Energy (mJ)", "EDP (mJ·ms)"],
        [(LABELS[r["arch"]], f'{comparison_latency_us(r) / 1000:.3f}',
          f'{energy_mj(r, DEFAULT_TINYMPC_POWER_W):.3f}',
          f'{edp_uj_us(r, DEFAULT_TINYMPC_POWER_W) / 1e6:.3f}') for r in common],
    )
    benchmark += "\n\n" + table(
        ["H40 FPGA resources", "LUTs", "FFs", "BRAM tiles", "DSPs"],
        [(LABELS[r["arch"]], *(r[k] for k in (
            "route_slice_luts_used", "route_slice_registers_used",
            "route_bram_tile_used", "route_dsps_used")))
         for r in common if r["arch"] != "tinympc_e"],
    )
    largest = [max((r for r in rows if r["arch"] == arch), key=lambda r: f(r, "horizon"))
               for arch in ("full_sparse", "staged_a")]
    benchmark += "\n\n" + table(
        ["Largest recorded timing-clean horizon", "Horizon", "Variables", "Constraints", "Solve (ms)"],
        [(LABELS[r["arch"]], r["horizon"], r["gen_n_var"], r["gen_n_constr"],
          f'{f(r, "solve_us_cfg_clk") / 1000:.3f}') for r in largest],
    )
    if args.benchmarks_only:
        page = HERE / "README.md"
        start, end = "<!-- BEGIN GENERATED BENCHMARKS -->", "<!-- END GENERATED BENCHMARKS -->"
        before, rest = page.read_text().split(start)
        _, after = rest.split(end)
        page.write_text(before + start + "\n\n" + benchmark + "\n\n" + end + after)
        print(f"Updated benchmark tables in {page}.")
        return
    flight = [r for r in load_rows(OUTPUT_DIR / "flight_metrics.csv")
              if (r["experiment"], r["axis"]) in {("dynamic", "x"), ("star", "xy_any")}]
    flights = table(
        ["Recording", "Samples", "Max violation (cm)", "RMS violation (cm)", "Outside (%)"],
        [(r["recording"], r["samples"], f'{float(r["max_violation_cm"]):.4f}',
          f'{float(r["rms_violation_cm"]):.4f}', f'{float(r["outside_percent"]):.3f}')
         for r in flight],
    )
    flights += "\n\n" + table(
        ["Recording", "Inside bounds (%)", "Violation ≤1 cm (%)", "Mean (cm)", "Std (cm)", "P95 (cm)", "P99 (cm)"],
        [(r["recording"], f'{100 - float(r["outside_percent"]):.2f}',
          f'{float(r["within_1cm_percent"]):.2f}',
          *(f'{float(r[key]):.4f}' for key in (
              "mean_violation_cm", "std_violation_cm", "p95_violation_cm", "p99_violation_cm")))
         for r in flight],
    )
    tracking = [r for r in load_rows(OUTPUT_DIR / "flight_metrics.csv")
                if r["experiment"] == "star" and r["axis"] == "xy_any"
                and r.get("tracking_rmse_cm", "")]
    tracking_table = table(
        ["Recording", "Fixed phase / period (s)", "Feasible samples (%)", "RMSE 3D (cm)", "RMSE XY (cm)", "P95 3D (cm)", "Max 3D (cm)"],
        [(r["recording"], f'{float(r["tracking_phase_offset_s"]):.3f} / {float(r["tracking_period_s"]):g}',
          f'{float(r["tracking_coverage_percent"]):.2f}',
          f'{float(r["tracking_rmse_cm"]):.3f}',
          f'{float(r["tracking_xy_rmse_cm"]):.3f}',
          f'{float(r["tracking_p95_cm"]):.3f}',
          f'{float(r["tracking_max_cm"]):.3f}') for r in tracking],
    )
    numerical = (OUTPUT_DIR / "numerical_accuracy.txt").read_text().split("\nPlot:", 1)[0].strip()
    sections = {"BENCHMARKS": benchmark, "FLIGHTS": flights,
                "TRACKING": tracking_table,
                "NUMERICS": "```text\n" + numerical + "\n```"}
    page = HERE / "README.md"
    text = page.read_text()
    for name, body in sections.items():
        start, end = f"<!-- BEGIN GENERATED {name} -->", f"<!-- END GENERATED {name} -->"
        before, rest = text.split(start)
        _, after = rest.split(end)
        text = before + start + "\n\n" + body + "\n\n" + end + after
    page.write_text(text)
    print(f"Updated {page}.")


if __name__ == "__main__":
    main()
