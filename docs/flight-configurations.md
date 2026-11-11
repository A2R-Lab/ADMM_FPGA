# Flight configurations

| Experiment | Controller / FPGA mapping | Horizon H | ADMM iterations k | Control rate |
| --- | --- | --- | --- | --- |
| Unconstrained figure-eight | TinyMPC on MCU | 15 | 2 | 500 Hz |
| Unconstrained figure-eight | `full_sparse` | 20 | 28 | 500 Hz |
| Static constrained star | `staged_a` | 27 | 9 | 1 kHz |
| Dynamic obstacle avoidance | `full_sparse` | 25 | 9 | 1 kHz |

## Timing

Solver latencies at 100 MHz:

| Configuration | HLS cycles | Solve time (µs) | With 100 µs SPI reserve (µs) |
| --- | --- | --- | --- |
| `full_sparse` (March 2026 revision), H20, k28 | 169,900 | 1,699.00 | 1,799.00 |
| `staged_a`, H27, k9 | 85,666 | 856.66 | 956.66 |
| `full_sparse`, H25, k9 | 84,757 | 847.57 | 947.57 |

The figure-eight configuration fits the 1,900 µs compute budget of its 2 ms control period. The star and obstacle configurations both fit the 900 µs compute budget of a 1 ms control period.
