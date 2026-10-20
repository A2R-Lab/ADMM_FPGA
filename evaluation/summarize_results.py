#!/usr/bin/env python3
"""Refresh the results-page tables and selected previews after regenerating analyses."""
import shutil

from plot_benchmarks import (
    HERE, OUTPUT_DIR, BENCHMARK_SUMMARY_CSV, LABELS, DEFAULT_TINYMPC_POWER_W,
    load_rows, best_rows, f, energy_mj, edp_uj_us,
)

PREVIEWS = (
    "benchmark_latency_energy.png", "benchmark_edp_bars.png",
    "figure8_trajectory_overlay.png", "dynamic_take1_bounds.png",
    "numerical_convergence.png",
)


def table(headers, rows):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(map(str, row)) + " |" for row in rows),
    ])


def main():
    required = [OUTPUT_DIR / name for name in PREVIEWS]
    required += [OUTPUT_DIR / "flight_metrics.csv", OUTPUT_DIR / "numerical_accuracy.txt"]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("Regenerate the analyses first; missing:\n" + "\n".join(missing))

    rows = best_rows(load_rows(BENCHMARK_SUMMARY_CSV), 10)
    common = [r for r in rows if int(f(r, "horizon")) == 40]
    benchmark = table(
        ["H40 / 10 iterations", "Solve (ms)", "Energy (mJ)", "EDP (mJ·ms)"],
        [(LABELS[r["arch"]], f'{f(r, "solve_us_cfg_clk") / 1000:.3f}',
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
    flight = [r for r in load_rows(OUTPUT_DIR / "flight_metrics.csv")
              if (r["experiment"], r["axis"]) in {("dynamic", "x"), ("star", "xy_any")}]
    flights = table(
        ["Recording", "Samples", "Max violation (cm)", "RMS violation (cm)", "Outside (%)"],
        [(r["recording"], r["samples"], f'{float(r["max_violation_cm"]):.4f}',
          f'{float(r["rms_violation_cm"]):.4f}', f'{float(r["outside_percent"]):.3f}')
         for r in flight],
    )
    numerical = (OUTPUT_DIR / "numerical_accuracy.txt").read_text().split("\nPlot:", 1)[0].strip()
    sections = {"BENCHMARKS": benchmark, "FLIGHTS": flights,
                "NUMERICS": "```text\n" + numerical + "\n```"}
    page = HERE / "README.md"
    text = page.read_text()
    for name, body in sections.items():
        start, end = f"<!-- BEGIN GENERATED {name} -->", f"<!-- END GENERATED {name} -->"
        before, rest = text.split(start)
        _, after = rest.split(end)
        text = before + start + "\n\n" + body + "\n\n" + end + after
    page.write_text(text)
    previews = HERE / "previews"
    previews.mkdir(exist_ok=True)
    for name in PREVIEWS:
        shutil.copyfile(OUTPUT_DIR / name, previews / name)
    print(f"Updated {page} and {len(PREVIEWS)} previews.")


if __name__ == "__main__":
    main()
