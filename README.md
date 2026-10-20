# AccelMPC — FPGA solver

FPGA implementation of the ADMM solver in [*AccelMPC: High-Rate, Low-Power
FPGA-Accelerated Model Predictive Control for Tiny Drones*](https://arxiv.org/abs/2609.09380),
by Andrea Grillo and Brian Plancher. The design targets an Artix-7 100T and runs
on the custom Crazyflie FPGA deck or an Arty A7 development board.

**[Results and figures](paper_figures/README.md)** ·
**[Build and program](docs/build.md)** ·
**[Design and interfaces](docs/architecture.md)** ·
**[Run benchmarks](docs/benchmarking.md)** ·
**[Measure power](docs/power.md)**

## Start here

To regenerate the benchmark and flight figures from bundled data, no FPGA is needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r paper_figures/requirements-flight.txt
python paper_figures/plot_benchmarks.py
python paper_figures/flight_metrics.py
```

For hardware builds, follow the [toolchain setup](docs/build.md). Python generates
the model matrices and reference trajectory; Vitis HLS compiles the C++ solver;
Vivado integrates its RTL with SPI/UART and produces the bitstream.

## Repository map

| Location | Contents |
|---|---|
| [vitis_projects/ADMM/](vitis_projects/ADMM/) | Solver C++, numerical types, HLS configurations and testbenches |
| [vivado_project/](vivado_project/) | FPGA top levels, SPI/UART, power instrumentation and board constraints |
| [scripts/](scripts/) | Model generation, build support and benchmark runners; see the [workflow guide](docs/benchmarking.md) |
| [paper_figures/](paper_figures/) | Recorded inputs, analysis, results and figure generation |
| [experiments/power/](experiments/power/) | Power workload and build dependencies |
| [tests/power/](tests/power/) | Host, RTL and HLS power-workflow checks |
| [video/](video/) | [Supplementary demo](video/AccelMPC_supplementary_demo.mp4), recordings and editing assets |

Generated builds live in `build/`; local experiment outputs live in `results/`;
full figure exports live in `paper_figures/output/`. These directories are ignored.

## Companion projects

- [FPGA deck PCB](https://github.com/A2R-Lab/Crazyflie_FPGA_Deck)
- [Crazyflie firmware](https://github.com/A2R-Lab/crazyflie_fpga_firmware)

The FPGA/firmware packet interface is described in [the design guide](docs/architecture.md).
This repository is released under the [MIT license](LICENSE).

## Citation

```bibtex
@article{grillo2026accelmpc,
  title={AccelMPC: High-Rate, Low-Power FPGA-Accelerated Model Predictive Control for Tiny Drones},
  author={Grillo, Andrea and Plancher, Brian},
  journal={arXiv preprint arXiv:2609.09380},
  year={2026}
}
```
