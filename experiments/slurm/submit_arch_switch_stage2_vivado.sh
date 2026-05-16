#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  experiments/slurm/submit_arch_switch_stage2_vivado.sh [--dry-run]

Submits the Stage 2 single-branch architecture-switch Vivado validation:

  - ADMM_SOLVER_ARCH=staged_a
  - ADMM_SOLVER_ARCH=full_sparse

Both jobs use the current f2fdd4e base plus
experiments/patches/f2fdd4e_arch_switch_stage2.patch, run a 5 s closed-loop
CSim smoke, then run the custom-board Vivado flow.

Environment:
  ADMM_REPO_ROOT       Default: inferred repo root from this script path.
  ADMM_WORKTREE_ROOT   Default: <repo-parent>/worktrees.
  ADMM_RESULTS_ROOT    Default: <repo-parent>/exp/2026-05-arch-switch-vivado.
  ADMM_BUILD_ROOT      Default: <repo-parent>/exp/build/2026-05-arch-switch-vivado.
  ADMM_BOARD           Default: custom.
  ADMM_RUN_CSIM        Default: 1.
  ADMM_RUN_BITSTREAM   Default: 0.

Optional Slurm environment:
  ADMM_SLURM_PARTITION
  ADMM_SLURM_ACCOUNT
  ADMM_SLURM_TIME              Default: 08:00:00
  ADMM_SLURM_CPUS_PER_TASK     Default: 20
  ADMM_SLURM_MEM               Default: 59000M
  ADMM_SLURM_EXTRA_ARGS        Extra sbatch arguments, split by shell whitespace.
  ADMM_PYTHON_VENV             Default: /home/agrillo/venv if it exists.
  ADMM_TOOLCHAIN_SETUP         Optional shell file sourced by each job.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFERRED_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ADMM_REPO_ROOT="${ADMM_REPO_ROOT:-$INFERRED_REPO_ROOT}"
ADMM_REPO_ROOT="$(cd "$ADMM_REPO_ROOT" && pwd)"
PROJECT_ROOT="$(dirname "$ADMM_REPO_ROOT")"

ADMM_WORKTREE_ROOT="${ADMM_WORKTREE_ROOT:-$PROJECT_ROOT/worktrees}"
ADMM_RESULTS_ROOT="${ADMM_RESULTS_ROOT:-$PROJECT_ROOT/exp/2026-05-arch-switch-vivado}"
ADMM_BUILD_ROOT="${ADMM_BUILD_ROOT:-$PROJECT_ROOT/exp/build/2026-05-arch-switch-vivado}"
ADMM_BOARD="${ADMM_BOARD:-custom}"
ADMM_RUN_CSIM="${ADMM_RUN_CSIM:-1}"
ADMM_RUN_BITSTREAM="${ADMM_RUN_BITSTREAM:-0}"
ADMM_COMPARISON_VIEW="${ADMM_COMPARISON_VIEW:-arch_switch_stage2}"
ADMM_CSIM_DURATION_S="${ADMM_CSIM_DURATION_S:-5}"
ADMM_CSIM_TIMEOUT_S="${ADMM_CSIM_TIMEOUT_S:-1800}"
SBATCH_CPUS_PER_TASK="${ADMM_SLURM_CPUS_PER_TASK:-20}"
VIVADO_MAX_THREADS="${VIVADO_MAX_THREADS:-$SBATCH_CPUS_PER_TASK}"
if [[ -z "${ADMM_PYTHON_VENV:-}" && -f /home/agrillo/venv/bin/activate ]]; then
  ADMM_PYTHON_VENV=/home/agrillo/venv
fi
DEFAULT_TOOLCHAIN_SETUP="$ADMM_REPO_ROOT/experiments/slurm/setup_xilinx_2025_2.sh"
if [[ -z "${ADMM_TOOLCHAIN_SETUP:-}" \
    && -x "$DEFAULT_TOOLCHAIN_SETUP" \
    && -r /home/agrillo/amdfpga/2025.2/Vivado/settings64.sh \
    && -r /home/agrillo/amdfpga/2025.2/Vitis/settings64.sh ]]; then
  ADMM_TOOLCHAIN_SETUP="$DEFAULT_TOOLCHAIN_SETUP"
fi

if [[ "$DRY_RUN" != "1" ]]; then
  mkdir -p "$ADMM_WORKTREE_ROOT" "$ADMM_RESULTS_ROOT/slurm" "$ADMM_BUILD_ROOT"
fi

RUNNER="$ADMM_REPO_ROOT/experiments/slurm/run_vivado_config.sh"
PATCH="$ADMM_REPO_ROOT/experiments/patches/f2fdd4e_arch_switch_stage2.patch"
if [[ ! -x "$RUNNER" ]]; then
  echo "error: runner is not executable: $RUNNER" >&2
  exit 1
fi
if [[ ! -f "$PATCH" ]]; then
  echo "error: missing patch: $PATCH" >&2
  exit 1
fi

SBATCH_BASE=()
if [[ -n "${ADMM_SLURM_PARTITION:-}" ]]; then
  SBATCH_BASE+=(--partition "$ADMM_SLURM_PARTITION")
fi
if [[ -n "${ADMM_SLURM_ACCOUNT:-}" ]]; then
  SBATCH_BASE+=(--account "$ADMM_SLURM_ACCOUNT")
fi
SBATCH_BASE+=(--time "${ADMM_SLURM_TIME:-08:00:00}")
SBATCH_BASE+=(--cpus-per-task "$SBATCH_CPUS_PER_TASK")
SBATCH_BASE+=(--mem "${ADMM_SLURM_MEM:-59000M}")

if [[ -n "${ADMM_SLURM_EXTRA_ARGS:-}" ]]; then
  read -r -a EXTRA_ARGS <<< "$ADMM_SLURM_EXTRA_ARGS"
  SBATCH_BASE+=("${EXTRA_ARGS[@]}")
fi

declare -a ARCHES=(
  "staged_a"
  "full_sparse"
)
declare -a CONFIG_IDS=(
  "vivado_arch_switch_staged_a"
  "vivado_arch_switch_full_sparse"
)
COMMIT="f2fdd4e81fb770805409799127642cd99ff34783"

echo "ADMM_REPO_ROOT=$ADMM_REPO_ROOT"
echo "ADMM_WORKTREE_ROOT=$ADMM_WORKTREE_ROOT"
echo "ADMM_RESULTS_ROOT=$ADMM_RESULTS_ROOT"
echo "ADMM_BUILD_ROOT=$ADMM_BUILD_ROOT"
echo "ADMM_BOARD=$ADMM_BOARD"
echo "ADMM_RUN_CSIM=$ADMM_RUN_CSIM"
echo "ADMM_RUN_BITSTREAM=$ADMM_RUN_BITSTREAM"
echo "ADMM_COMPARISON_VIEW=$ADMM_COMPARISON_VIEW"
echo "ADMM_TOOLCHAIN_SETUP=${ADMM_TOOLCHAIN_SETUP:-}"
echo "VIVADO_MAX_THREADS=$VIVADO_MAX_THREADS"
echo "candidates=${#CONFIG_IDS[@]}"

for idx in "${!CONFIG_IDS[@]}"; do
  CONFIG_ID="${CONFIG_IDS[$idx]}"
  ARCH="${ARCHES[$idx]}"
  JOB_NAME="admm_${CONFIG_ID}"
  EXPORTS="ALL,ADMM_REPO_ROOT=$ADMM_REPO_ROOT,ADMM_WORKTREE_ROOT=$ADMM_WORKTREE_ROOT,ADMM_RESULTS_ROOT=$ADMM_RESULTS_ROOT,ADMM_BUILD_ROOT=$ADMM_BUILD_ROOT,ADMM_CONFIG_ID=$CONFIG_ID,ADMM_COMMIT=$COMMIT,ADMM_PATCH_FILE=$PATCH,ADMM_HORIZON=40,ADMM_TRAJ_SHAPE=star_hold,ADMM_ITERATIONS_OVERRIDE=default,ADMM_ENABLE_TRAJECTORY=1,ADMM_SOLVER_ARCH=$ARCH,ADMM_SIM_FREQ=500,ADMM_TRAJ_START_STEP=0,ADMM_CSIM_DURATION_S=$ADMM_CSIM_DURATION_S,ADMM_CSIM_TIMEOUT_S=$ADMM_CSIM_TIMEOUT_S,ADMM_RUN_CSIM=$ADMM_RUN_CSIM,ADMM_BOARD=$ADMM_BOARD,ADMM_RUN_BITSTREAM=$ADMM_RUN_BITSTREAM,ADMM_COMPARISON_VIEW=$ADMM_COMPARISON_VIEW,VIVADO_MAX_THREADS=$VIVADO_MAX_THREADS"
  if [[ -n "${ADMM_PYTHON_VENV:-}" ]]; then
    EXPORTS="$EXPORTS,ADMM_PYTHON_VENV=$ADMM_PYTHON_VENV"
  fi
  if [[ -n "${ADMM_TOOLCHAIN_SETUP:-}" ]]; then
    EXPORTS="$EXPORTS,ADMM_TOOLCHAIN_SETUP=$ADMM_TOOLCHAIN_SETUP"
  fi

  CMD=(
    sbatch
    "${SBATCH_BASE[@]}"
    --job-name "$JOB_NAME"
    --output "$ADMM_RESULTS_ROOT/slurm/%x_%j.out"
    --error "$ADMM_RESULTS_ROOT/slurm/%x_%j.err"
    --export "$EXPORTS"
    "$RUNNER"
  )

  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'dry-run:'
    printf ' %q' "${CMD[@]}"
    printf ' # ADMM_SOLVER_ARCH=%s\n' "$ARCH"
  else
    "${CMD[@]}"
  fi
done
