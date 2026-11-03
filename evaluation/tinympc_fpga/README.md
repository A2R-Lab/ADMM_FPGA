# TinyMPC FPGA comparison (Wu et al.)

This adapter uses the operator-fused FPGA generator in the upstream submodule,
pinned to `bd1a6bd2348d2659652d0ae315f9eea8fea40c95`. Initialize it with:

```sh
git submodule update --init --recursive evaluation/tinympc_fpga/upstream
```

[model.json](model.json) is generation input (the quadrotor model and constraints),
not archived benchmark output. TinyMPC retains its native float32 arithmetic,
steady-state Riccati terminal matrix and rho/reference weighting. The benchmarks
share dimensions, constraints and ten iterations, but are not identical numerical
formulations and do not establish equal solution accuracy.

## Reproduce

Follow the [Arty campaign guide](../../docs/arty_comparison.md) for source
snapshots, build bundles, output validation and incremental power measurement.
The single publication dataset is [benchmarks.csv](../data/benchmarks.csv).
TinyMPC FPGA points in it use Arty measurements; standalone post-route power
estimates must not be substituted for these measurements.

For an independent generation and host diagnostic:

```sh
python evaluation/tinympc_fpga/prepare.py --horizon 5 --iterations 10 --output /path/to/run/h5
python evaluation/tinympc_fpga/prepare.py --horizon 10 --iterations 10 --output /path/to/run/h10
```

Preparation requires NumPy, SciPy, OSQP and autograd. For generation without
host validation, pass `--generate-only --model-report evaluation/tinympc_fpga/model.json`.
The campaign invokes this generator through `scripts/power_tiny.py`, which
adapts its local-memory interface to the Arty measurement shell. Building,
programming, output validation and acquisition use `scripts/power_campaign.py`;
there is no separate TinyMPC build workflow.

Generated sources, raw reports, logs, validation outputs and intermediate plots
are ignored. Only accepted publication measurements are consolidated in the CSV.
Keep upstream copyright and license notices when generating or distributing code.
