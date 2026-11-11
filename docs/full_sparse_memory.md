# Full-sparse memory mapping

The full_sparse implementation shares its Cholesky factor between forward and
backward solves and banks transpose indices to reduce memory replication. The
compact campaign option binds the RHS buffer to true-dual-port BRAM, trading
additional cycles for a smaller BRAM footprint.
The default full_sparse source retains the faster mapping; campaign preparation
applies the compact patch to its frozen source snapshot.

The publication's full_sparse results use this compact mapping. Valid completed
measurements are retained in [benchmarks.csv](../evaluation/data/benchmarks.csv),
including the solver source hash. H400 is the largest demonstrated horizon in
this dataset; H100 works without BRAM spillover into LUTRAM. Neither value is a
proof of an absolute capacity limit.

At H40, the matching uninstrumented solver builds use 7,628 LUTs, 9,911
registers, 80 DSPs and 26.5 BRAM tiles for full_sparse, versus 23,284 LUTs,
22,209 registers, 150 DSPs and 27 BRAM tiles for AccelMPC staged (recorded as `staged_fused`). Instrumented
Arty latency and energy are separate measurements; the radar combines these
clearly identified scopes. Full_sparse offers lower logic usage at the cost of
longer solve times.

## Reproduction

Use the [campaign workflow](arty_comparison.md) with
`--compact-full-sparse --horizons 10,40,100`. Preparation checks the expected
source before patching and records the resulting source hash. It does not modify
the checkout.

Raw build reports, bitstreams, traces and intermediate experiment outputs stay
outside Git. Regenerate publication plots from the consolidated CSV with
`evaluation/plot_benchmarks.py --skip-trajectory`.
