#!/usr/bin/env python3
"""Generate the matrix sparsity figure for the paper.

    python evaluation/plot_sparsity.py

Figure settings are embedded below, independent of ADMM environment overrides.
Dependencies: scripts/requirements.txt (including CHOLMOD/SuiteSparse).
"""

import os
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.transforms import Bbox
import numpy as np
from scipy import sparse

CONFIG = {
    "horizon": 40,
    "model_frequency_hz": 50.0,
    "drag_xy": 0.12,
    "drag_z": 0.12,
    "q_diag": [40, 40, 158, 0.4, 0.4, 40, 3.5, 3.5, 4, 0.2, 0.2, 25],
    "r_diag": [1, 1, 1, 1],
    "rho_eq": 128,
    "rho_ineq": 32,
}

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def build_matrices(config):
    # The generator reads its settings at import and writes its usual headers.
    os.environ.update({
        "ADMM_HORIZON_LENGTH": str(config["horizon"]),
        "ADMM_MODEL_FREQ": str(config["model_frequency_hz"]),
        "ADMM_MPC_LINEAR_DRAG_XY": str(config["drag_xy"]),
        "ADMM_MPC_LINEAR_DRAG_Z": str(config["drag_z"]),
        "ADMM_Q_DIAG": ",".join(map(str, config["q_diag"])),
        "ADMM_R_DIAG": ",".join(map(str, config["r_diag"])),
        "ADMM_R_SCALE": "1",
        "ADMM_RHO_EQ_PARAM": str(config["rho_eq"]),
        "ADMM_RHO_INEQ_PARAM": str(config["rho_ineq"]),
        "ADMM_ENABLE_TRAJECTORY": "0",
        "ADMM_ABQR_OVERRIDE_PATH": "",
    })
    import header_generator as generator

    coefficient, factor = generator.KKT.copy(), generator.L.copy()
    coefficient.eliminate_zeros()
    factor.eliminate_zeros()
    residual = sparse.linalg.norm(coefficient - factor @ factor.T) / sparse.linalg.norm(coefficient)
    if residual > 1e-12:
        raise RuntimeError(f"Cholesky reconstruction failed: {residual:g}")
    return coefficient, factor


def lower_bandwidth(factor):
    rows, cols = factor.nonzero()
    return int(np.max(rows - cols)) + 1


def render(coefficient, factor):
    output_dir = ROOT / "evaluation/output"
    plt.rcParams.update({
        "font.family": "serif",
        "mathtext.fontset": "stix",
        "pdf.fonttype": 42,
        "font.size": 8,
        "axes.linewidth": 0.5,
    })
    fig, axes = plt.subplots(1, 2, figsize=(2.04, 1.05))
    fig.subplots_adjust(left=0.13, right=0.97, bottom=0.19, top=0.95, wspace=0.16)
    # Plot actual nonzeros in natural stage-wise variable ordering.
    for ax, matrix in zip(axes, (coefficient, factor)):
        ax.spy(matrix, markersize=0.45, color="#1f77b4",
               marker="s", precision=0, rasterized=False)
        ax.xaxis.tick_bottom()
        ax.set_xticks([0, 300, 600])
        ax.set_yticks([0, 300, 600])
        ax.tick_params(labelsize=7, length=2, width=0.5, pad=1)
    # Both panels share the variable ordering and scale explained in the caption.
    axes[1].tick_params(axis="y", left=False, labelleft=False)
    # Use an actual row attaining the maximum lower bandwidth, including diagonal.
    bandwidth = lower_bandwidth(factor)
    rows, cols = factor.nonzero()
    candidates = rows[rows - cols + 1 == bandwidth]
    row = int(candidates[np.argmin(abs(candidates - factor.shape[0] * 0.55))])
    band_left, band_right = row - bandwidth + 0.5, row + 0.5
    band_y = row
    dimension_y = band_y + 65
    for x in (band_left, band_right):
        axes[1].plot([x, x], [band_y + 8, dimension_y + 12], color="0.35", lw=0.4)
    axes[1].annotate("", xy=(band_left, dimension_y), xytext=(band_right, dimension_y),
                     arrowprops=dict(arrowstyle="|-|,widthA=0.12,widthB=0.12",
                                     shrinkA=0, shrinkB=0, lw=0.6, color="black"))
    axes[1].annotate(r"$h$", xy=((band_left + band_right) / 2, dimension_y),
                     xytext=(band_left - 130, dimension_y + 55), fontsize=9,
                     ha="center", va="center",
                     arrowprops=dict(arrowstyle="-", lw=0.5, shrinkA=1, shrinkB=2))
    fig.canvas.draw()
    bottom = max(0, fig.get_tightbbox(fig.canvas.get_renderer()).y0 - 0.02)
    export_bounds = Bbox.from_extents(0, bottom, *fig.get_size_inches())
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_dir / "kkt-chol-sparsity.pdf", bbox_inches=export_bounds,
                metadata={"CreationDate": None, "ModDate": None})
    fig.savefig(output_dir / "kkt-chol-sparsity-preview.png", dpi=300,
                bbox_inches=export_bounds)
    plt.close(fig)


if __name__ == "__main__":
    coefficient, factor = build_matrices(CONFIG)
    render(coefficient, factor)
