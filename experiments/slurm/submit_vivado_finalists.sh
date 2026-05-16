#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  experiments/slurm/submit_vivado_finalists.sh [--dry-run]

Submits the first normalized finalist Vivado comparison:

  View A: end-to-end native trajectory storage, custom board/top_spi,
          same star_hold trajectory configuration, HLS IP export,
          Vivado synthesis, and Vivado implementation.

Default candidates:
  - 1c23f1f flight baseline
  - ee338c6 memory optimization with Vitis 2025.2 / 418-bit compatibility patch

Environment:
  ADMM_REPO_ROOT       Default: inferred repo root from this script path.
  ADMM_WORKTREE_ROOT   Default: <repo-parent>/worktrees.
  ADMM_RESULTS_ROOT    Default: <repo-parent>/exp/2026-05-vivado-finalists-view-a.
  ADMM_BUILD_ROOT      Default: <repo-parent>/exp/build/2026-05-vivado-finalists-view-a.
  ADMM_SOLVER_ARCH     Default: staged_a.
  ADMM_BOARD           Default: custom.
  ADMM_RUN_CSIM        Default: 0. Set to 1 to run a 5 s CSim smoke before Vivado.
  ADMM_RUN_BITSTREAM   Default: 0. Set to 1 to generate bitstreams after route.

Optional Slurm environment:
  ADMM_SLURM_PARTITION
  ADMM_SLURM_ACCOUNT
  ADMM_SLURM_TIME              Default: 08:00:00
  ADMM_SLURM_CPUS_PER_TASK     Default: 8
  ADMM_SLURM_MEM               Default: 59000M
  ADMM_SLURM_EXTRA_ARGS        Extra sbatch arguments, split by shell whitespace.
  ADMM_PYTHON_VENV             Default: /home/agrillo/venv if it exists.
  ADMM_TOOLCHAIN_SETUP         Optional shell file sourced by each job.

Examples:
  experiments/slurm/submit_vivado_finalists.sh --dry-run
  experiments/slurm/submit_vivado_finalists.sh
  ADMM_RUN_CSIM=1 experiments/slurm/submit_vivado_finalists.sh
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
ADMM_RESULTS_ROOT="${ADMM_RESULTS_ROOT:-$PROJECT_ROOT/exp/2026-05-vivado-finalists-view-a}"
ADMM_BUILD_ROOT="${ADMM_BUILD_ROOT:-$PROJECT_ROOT/exp/build/2026-05-vivado-finalists-view-a}"
ADMM_SOLVER_ARCH="${ADMM_SOLVER_ARCH:-staged_a}"
ADMM_BOARD="${ADMM_BOARD:-custom}"
ADMM_RUN_CSIM="${ADMM_RUN_CSIM:-0}"
ADMM_RUN_BITSTREAM="${ADMM_RUN_BITSTREAM:-0}"
ADMM_COMPARISON_VIEW="${ADMM_COMPARISON_VIEW:-end_to_end_native_trajectory}"
ADMM_CSIM_DURATION_S="${ADMM_CSIM_DURATION_S:-5}"
ADMM_CSIM_TIMEOUT_S="${ADMM_CSIM_TIMEOUT_S:-1800}"
SBATCH_CPUS_PER_TASK="${ADMM_SLURM_CPUS_PER_TASK:-8}"
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

mkdir -p "$ADMM_WORKTREE_ROOT" "$ADMM_RESULTS_ROOT/slurm" "$ADMM_BUILD_ROOT"

RUNNER="$ADMM_REPO_ROOT/experiments/slurm/run_vivado_config.sh"
if [[ ! -x "$RUNNER" ]]; then
  echo "error: runner is not executable: $RUNNER" >&2
  exit 1
fi

EE338C6_PATCH="$ADMM_REPO_ROOT/experiments/patches/ee338c6_vitis2025_and_418bit.patch"
if [[ ! -f "$EE338C6_PATCH" ]]; then
  echo "error: missing patch: $EE338C6_PATCH" >&2
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

declare -a CONFIG_IDS=(
  "vivado_flight_baseline_native"
  "vivado_ee338c6_native"
)
declare -a COMMITS=(
  "1c23f1fb276b193294ac106037873362d5740f6e"
  "ee338c643eec3b10c02e64e3ffc29437312c48d4"
)
declare -a PATCHES=(
  ""
  "$EE338C6_PATCH"
)
declare -a NAMES=(
  "Flight baseline native trajectory storage"
  "ee338c6 native trajectory storage with compatibility patch"
)

echo "ADMM_REPO_ROOT=$ADMM_REPO_ROOT"
echo "ADMM_WORKTREE_ROOT=$ADMM_WORKTREE_ROOT"
echo "ADMM_RESULTS_ROOT=$ADMM_RESULTS_ROOT"
echo "ADMM_BUILD_ROOT=$ADMM_BUILD_ROOT"
echo "ADMM_SOLVER_ARCH=$ADMM_SOLVER_ARCH"
echo "ADMM_BOARD=$ADMM_BOARD"
echo "ADMM_RUN_CSIM=$ADMM_RUN_CSIM"
echo "ADMM_RUN_BITSTREAM=$ADMM_RUN_BITSTREAM"
echo "ADMM_COMPARISON_VIEW=$ADMM_COMPARISON_VIEW"
echo "ADMM_TOOLCHAIN_SETUP=${ADMM_TOOLCHAIN_SETUP:-}"
echo "VIVADO_MAX_THREADS=$VIVADO_MAX_THREADS"
echo "candidates=${#CONFIG_IDS[@]}"

for idx in "${!CONFIG_IDS[@]}"; do
  CONFIG_ID="${CONFIG_IDS[$idx]}"
  COMMIT="${COMMITS[$idx]}"
  PATCH="${PATCHES[$idx]}"
  NAME="${NAMES[$idx]}"
  JOB_NAME="admm_${CONFIG_ID}"
  EXPORTS="ALL,ADMM_REPO_ROOT=$ADMM_REPO_ROOT,ADMM_WORKTREE_ROOT=$ADMM_WORKTREE_ROOT,ADMM_RESULTS_ROOT=$ADMM_RESULTS_ROOT,ADMM_BUILD_ROOT=$ADMM_BUILD_ROOT,ADMM_CONFIG_ID=$CONFIG_ID,ADMM_COMMIT=$COMMIT,ADMM_HORIZON=40,ADMM_TRAJ_SHAPE=star_hold,ADMM_ITERATIONS_OVERRIDE=default,ADMM_ENABLE_TRAJECTORY=1,ADMM_SOLVER_ARCH=$ADMM_SOLVER_ARCH,ADMM_SIM_FREQ=500,ADMM_TRAJ_START_STEP=0,ADMM_CSIM_DURATION_S=$ADMM_CSIM_DURATION_S,ADMM_CSIM_TIMEOUT_S=$ADMM_CSIM_TIMEOUT_S,ADMM_RUN_CSIM=$ADMM_RUN_CSIM,ADMM_BOARD=$ADMM_BOARD,ADMM_RUN_BITSTREAM=$ADMM_RUN_BITSTREAM,ADMM_COMPARISON_VIEW=$ADMM_COMPARISON_VIEW,VIVADO_MAX_THREADS=$VIVADO_MAX_THREADS"
  if [[ -n "$PATCH" ]]; then
    EXPORTS="$EXPORTS,ADMM_PATCH_FILE=$PATCH"
  fi
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
    printf ' # %s\n' "$NAME"
  else
    "${CMD[@]}"
  fi
done
