#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  experiments/slurm/submit_sweep.sh [--dry-run] [--versions PATH]

Submits Tier 1 smoke jobs from experiments/versions.yaml: one job per candidate
commit, horizon 40, version-default ADMM iterations, star trajectory, short
closed-loop CSim, and HLS synthesis.

Environment:
  ADMM_REPO_ROOT       Default: inferred repo root from this script path.
  ADMM_WORKTREE_ROOT   Default: <repo-parent>/worktrees.
  ADMM_RESULTS_ROOT    Default: <repo-parent>/exp/2026-05-tier1-smoke.
  ADMM_BUILD_ROOT      Default: <repo-parent>/exp/build/2026-05-tier1-smoke.
  ADMM_SOLVER_ARCH     Default: staged_a.
  ADMM_CSIM_DURATION_S Default: 5. Use "default" for full generated trajectory.
  ADMM_CSIM_TIMEOUT_S  Default: 1800.

Optional Slurm environment:
  ADMM_SLURM_PARTITION
  ADMM_SLURM_ACCOUNT
  ADMM_SLURM_TIME              Default: 02:00:00
  ADMM_SLURM_CPUS_PER_TASK     Default: 8
  ADMM_SLURM_MEM               Default: 16G
  ADMM_SLURM_EXTRA_ARGS        Extra sbatch arguments, split by shell whitespace.
  ADMM_PYTHON_VENV             Default: /home/agrillo/venv if it exists.
  ADMM_TOOLCHAIN_SETUP         Optional shell file sourced by each job.

Examples:
  experiments/slurm/submit_sweep.sh --dry-run
  experiments/slurm/submit_sweep.sh
  ADMM_CSIM_DURATION_S=default ADMM_CSIM_TIMEOUT_S=14400 ADMM_SLURM_TIME=04:30:00 experiments/slurm/submit_sweep.sh
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFERRED_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSIONS_FILE="$INFERRED_REPO_ROOT/experiments/versions.yaml"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --versions)
      VERSIONS_FILE="$2"
      shift 2
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

PYTHON="${PYTHON:-python3}"
ADMM_REPO_ROOT="${ADMM_REPO_ROOT:-$INFERRED_REPO_ROOT}"
ADMM_REPO_ROOT="$(cd "$ADMM_REPO_ROOT" && pwd)"
PROJECT_ROOT="$(dirname "$ADMM_REPO_ROOT")"

ADMM_WORKTREE_ROOT="${ADMM_WORKTREE_ROOT:-$PROJECT_ROOT/worktrees}"
ADMM_RESULTS_ROOT="${ADMM_RESULTS_ROOT:-$PROJECT_ROOT/exp/2026-05-tier1-smoke}"
ADMM_BUILD_ROOT="${ADMM_BUILD_ROOT:-$PROJECT_ROOT/exp/build/2026-05-tier1-smoke}"
ADMM_SOLVER_ARCH="${ADMM_SOLVER_ARCH:-staged_a}"
ADMM_CSIM_DURATION_S="${ADMM_CSIM_DURATION_S:-5}"
ADMM_CSIM_TIMEOUT_S="${ADMM_CSIM_TIMEOUT_S:-1800}"
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

RUNNER="$ADMM_REPO_ROOT/experiments/slurm/run_one_config.sh"
if [[ ! -x "$RUNNER" ]]; then
  echo "error: runner is not executable: $RUNNER" >&2
  exit 1
fi

if [[ ! -f "$VERSIONS_FILE" ]]; then
  echo "error: versions file not found: $VERSIONS_FILE" >&2
  exit 1
fi

mapfile -t CANDIDATES < <("$PYTHON" - "$VERSIONS_FILE" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
items = []
current = None
in_candidates = False

def clean(value: str) -> str:
    value = value.strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    return value

for raw in path.read_text().splitlines():
    if not raw.strip() or raw.lstrip().startswith("#"):
        continue
    if re.match(r"^candidates:\s*$", raw):
        in_candidates = True
        continue
    if not in_candidates:
        continue
    m = re.match(r"^\s*-\s+id:\s*(.+?)\s*$", raw)
    if m:
        current = {"id": clean(m.group(1))}
        items.append(current)
        continue
    if current is None:
        continue
    m = re.match(r"^\s+([A-Za-z0-9_]+):\s*(.*?)\s*$", raw)
    if m:
        current[m.group(1)] = clean(m.group(2))

for item in items:
    if item.get("enabled", "true").lower() in {"false", "0", "no"}:
        continue
    print("\t".join([item["id"], item["commit"], item.get("name", item["id"]), item.get("patch", "")]))
PY
)

if [[ "${#CANDIDATES[@]}" -eq 0 ]]; then
  echo "error: no candidates found in $VERSIONS_FILE" >&2
  exit 1
fi

SBATCH_BASE=()
if [[ -n "${ADMM_SLURM_PARTITION:-}" ]]; then
  SBATCH_BASE+=(--partition "$ADMM_SLURM_PARTITION")
fi
if [[ -n "${ADMM_SLURM_ACCOUNT:-}" ]]; then
  SBATCH_BASE+=(--account "$ADMM_SLURM_ACCOUNT")
fi
SBATCH_BASE+=(--time "${ADMM_SLURM_TIME:-02:00:00}")
SBATCH_BASE+=(--cpus-per-task "${ADMM_SLURM_CPUS_PER_TASK:-8}")
SBATCH_BASE+=(--mem "${ADMM_SLURM_MEM:-16G}")

if [[ -n "${ADMM_SLURM_EXTRA_ARGS:-}" ]]; then
  read -r -a EXTRA_ARGS <<< "$ADMM_SLURM_EXTRA_ARGS"
  SBATCH_BASE+=("${EXTRA_ARGS[@]}")
fi

echo "ADMM_REPO_ROOT=$ADMM_REPO_ROOT"
echo "ADMM_WORKTREE_ROOT=$ADMM_WORKTREE_ROOT"
echo "ADMM_RESULTS_ROOT=$ADMM_RESULTS_ROOT"
echo "ADMM_BUILD_ROOT=$ADMM_BUILD_ROOT"
echo "ADMM_SOLVER_ARCH=$ADMM_SOLVER_ARCH"
echo "ADMM_CSIM_DURATION_S=$ADMM_CSIM_DURATION_S"
echo "ADMM_CSIM_TIMEOUT_S=$ADMM_CSIM_TIMEOUT_S"
echo "ADMM_TOOLCHAIN_SETUP=${ADMM_TOOLCHAIN_SETUP:-}"
echo "versions=$VERSIONS_FILE"
echo "candidates=${#CANDIDATES[@]}"

for candidate in "${CANDIDATES[@]}"; do
  IFS=$'\t' read -r CONFIG_ID COMMIT NAME PATCH <<< "$candidate"
  JOB_NAME="admm_${CONFIG_ID}"
  EXPORTS="ALL,ADMM_REPO_ROOT=$ADMM_REPO_ROOT,ADMM_WORKTREE_ROOT=$ADMM_WORKTREE_ROOT,ADMM_RESULTS_ROOT=$ADMM_RESULTS_ROOT,ADMM_BUILD_ROOT=$ADMM_BUILD_ROOT,ADMM_CONFIG_ID=$CONFIG_ID,ADMM_COMMIT=$COMMIT,ADMM_HORIZON=40,ADMM_TRAJ_SHAPE=star_hold,ADMM_ITERATIONS_OVERRIDE=default,ADMM_ENABLE_TRAJECTORY=1,ADMM_SOLVER_ARCH=$ADMM_SOLVER_ARCH,ADMM_CSIM_DURATION_S=$ADMM_CSIM_DURATION_S,ADMM_CSIM_TIMEOUT_S=$ADMM_CSIM_TIMEOUT_S,ADMM_RUN_CSIM=1,ADMM_RUN_HLS_SYNTH=1"
  if [[ -n "$PATCH" ]]; then
    if [[ "$PATCH" != /* ]]; then
      PATCH="$ADMM_REPO_ROOT/$PATCH"
    fi
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
