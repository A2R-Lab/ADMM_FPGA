# Paper Figures Notes

This directory contains scripts and data used to generate paper-ready figures.
When modifying figures, preserve these conventions:

- Keep fonts large and readable. These figures are intended for publication, so avoid small annotation text, cramped legends, or tiny tick labels.
- Maintain coherent colors across plots. Reuse the existing architecture colors and labels from `plot_benchmarks.py` instead of introducing new palettes for the same entities.
- Benchmark plots are generated from one script: `plot_benchmarks.py`. Make source changes there, then regenerate all benchmark outputs from the script rather than editing exported SVG/PDF/PNG files by hand.
- Committed plotting inputs live in `data/`; generated SVG, PNG, and PDF outputs live in `output/` and are ignored by git.
- Keep label sizing consistent within each plot. Axis labels and ticks may have their own sizes, but legends, annotations, and numeric callouts should look deliberate and balanced.
- For log-scale plots, place annotation labels using log-aware calculations or display-point offsets when visual spacing must be constant.
- Prefer small, explicit font-size variables near the plot code over repeated magic numbers.

To regenerate the benchmark figures:

```bash
cd paper_figures
source ~/venv/bin/activate
python plot_benchmarks.py
```

The script writes the benchmark latency/energy, EDP bar, solver radar, and figure-eight trajectory overlay figures to `output/` in SVG, PNG, and PDF formats.
