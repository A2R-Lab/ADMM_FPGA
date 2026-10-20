# Measured-power campaign

## Scope and agreed interpretation

Build all 42 timing-clean K=10 FPGA architecture/horizon pairs from
`paper_figures/data/benchmark_summary.csv`: 10 full-sparse and 32 staged.
Include points previously excluded only from presentation. Use the current
frozen solver sources, 100 MHz, fixed point, no compiled trajectory, no DDR3,
the 256-state synthetic ROM, and the existing 2,048-bin on-chip capture buffer.
This reproduces the configuration sweep, not historical source revisions.
Paper integration and figure updates are deferred.

For each active interval, report raw core/BRAM power and energy and separately:

```
corrected_power_W = 0.8 * (core_energy_J / active_seconds + 0.032)
corrected_energy_J_per_solve = 0.8 * (core_energy_J + 0.032 * active_seconds) / completed_solves
```

The 32 mW auxiliary allowance excludes VCCADC. The 20% instrumentation removal
is the agreed fixed assumption, informed by one design's Vivado analysis; these
are measurement-based corrected estimates, not direct solver-only measurements.
Preserve 5 V measurements as diagnostics, incremental core energy, temperature
drift, all raw captures, and the uncorrected values. Repetition spread describes
repeatability, not calibration or correction-model uncertainty. See
`POWER_MEASUREMENT_HANDOFF.md` for earlier measurements and limitations.

## Storage and isolation

`a2r-main-mount` is a local SSHFS mount of
`agrillo@a2r-main:/home/agrillo/power_measurements`.
The campaign is prepared in a new subdirectory; the server's existing repository
is never used or modified. Each attempt gets its own complete source snapshot,
generated headers, HLS output, Vivado output, logs, and checkpoints.
Source hashes and the campaign manifest are immutable. A source change requires
a new campaign. Keep results and failed attempts for diagnosis.

Only timing-clean bitstreams with a build manifest, C++ pilot reference, reports,
tool versions, and verified hashes enter `ready/<point-id>/`. Builds first use
the historical selected implementation variant, then retry `route_aggressive`
once if timing fails. Capacity or tool failures remain explicit failed points.
No selection is made using estimated power. Ready artifacts resume by hash;
failed points require `--retry-failed`.

## Commands

From the local repository, freeze a new campaign:

```bash
source ~/venv/bin/activate
python scripts/power_campaign.py prepare --campaign a2r-main-mount/arty-power-20261017-six
```

On **a2r-main**, start all 42 configurations with six parallel builds:

```bash
source /home/agrillo/amdfpga/2025.2/Vivado/settings64.sh
source /home/agrillo/amdfpga/2025.2/Vitis/settings64.sh
source ~/venv/bin/activate
cd /home/agrillo/power_measurements/arty-power-20261017-six
python source/scripts/power_campaign.py build --campaign "$PWD" --jobs 6 --threads 3 --memory-gib 16
```

The default budget is eight Vivado threads and 32 GiB RAM/40 GiB scratch per
worker, reserving four CPUs, 16 GiB RAM and 40 GiB disk for the host. Automatic
concurrency is capped at eight and respects available resources. The requested six-build configuration uses three threads and a 16 GiB planning
budget per build (`--jobs 6 --threads 3 --memory-gib 16`), fitting 24 CPUs and
125 GiB installed RAM. These are planning budgets, not enforced memory limits.
`--jobs`, `--threads`, `--memory-gib`, and `--scratch-gib` override the budgets.
Preflight rejects a launch if currently available resources cannot accommodate it. The runner does not manage SSH sessions or detachment.

Locally, with the Arty attached, collect finished designs while compilation continues:

```bash
source /media/andrea/48a1bd03-3653-4c55-8d37-cd7d804e2212/amdfpga/2025.2/Vivado/settings64.sh
source ~/venv/bin/activate
python scripts/power_campaign.py measure --campaign a2r-main-mount/arty-power-20261017-six --watch
python scripts/power_campaign.py aggregate --campaign a2r-main-mount/arty-power-20261017-six
```

This copies verified ready artifacts and frozen acquisition tools locally before
programming. JTAG programming is volatile; SPI flash is not written. Use `--port`
if the UART is not `/dev/ttyUSB1`. Local results default to `results/power-campaign`;
use the same `--local` directory for both measure and aggregate if overriding it.
An eight-solve pilot must match the C++ checksum and final output. Each of three
repetitions freshly programs the FPGA, settles 5 s, measures 3 s idle, runs a
multiple of 256 solves (at least 1,024 and approximately 2 s active), then measures
3 s idle. UART stays quiet during acquisition. One retry is permitted per
acquisition; failed captures and logs remain available. Per-port locks prevent
concurrent board measurements. The clock and solve latency must remain fixed,
all phase samples must be present, and flags/overruns must be zero.

The user waived preliminary smoke builds and the full-sweep gate. Per-artifact
timing/hash checks and per-design numerical pilots remain required.

Locally, collect available bitstreams sequentially and regenerate summaries:

```bash
python scripts/power_campaign.py measure --campaign a2r-main-mount/arty-power-20261017-six --watch
python scripts/power_campaign.py aggregate --campaign a2r-main-mount/arty-power-20261017-six
python scripts/power_campaign.py status --campaign a2r-main-mount/arty-power-20261017-six
```

`measure --watch` checks for new ready bundles every 30 seconds and measures
them while the server continues compiling. It exits once every selected build
has either been processed or failed. Ctrl-C stops watching; rerun to resume.
Without `--watch`, the command processes only currently available artifacts.
Validated repetitions resume without reprogramming. Run aggregation in another
local terminal for an interim summary, or after measurement finishes. `--ids full_sparse_h20_k10,staged_a_h20_k10` selects
specific points. Build status remains separate from local measurement status.
CSV and JSON summaries under `results/power-campaign/summaries/<campaign-id>`
include pending/failed points, resource counts, hashes, and mean/sample standard
deviation/min/max across valid repetitions. Consult state files and logs for
build failures; a completed runner process does not imply every design passed.
Largest designs may not fit with instrumentation and must not be replaced by
estimated measurements. No paper files are modified by the campaign.

## Validation

Run `python -m unittest discover -s tests/power -p 'test*.py'` for host checks.
Python tests do not validate routing, ADC calibration, or physical measurements.
Preliminary smoke builds are optional (`--smoke`), not a prerequisite for the
full sweep. Physical acceptance is recorded separately for every configuration.
