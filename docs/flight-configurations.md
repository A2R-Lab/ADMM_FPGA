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
| `staged_a`, H27, k9 | 85,666 | 856.66 | 956.66 |
| `full_sparse`, H25, k9 | 84,757 | 847.57 | 947.57 |

Both fit the 900 µs compute budget of a 1 ms control period.