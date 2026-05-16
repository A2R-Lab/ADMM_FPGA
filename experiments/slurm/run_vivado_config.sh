#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  ADMM_REPO_ROOT=/path/to/ADMM_FPGA \
  ADMM_WORKTREE_ROOT=/path/to/worktrees \
  ADMM_RESULTS_ROOT=/path/to/exp/2026-05-vivado-finalists-view-a \
  ADMM_BUILD_ROOT=/path/to/exp/build/2026-05-vivado-finalists-view-a \
  ADMM_CONFIG_ID=vivado_flight_baseline_native \
  ADMM_COMMIT=1c23f1f \
  experiments/slurm/run_vivado_config.sh

Required environment:
  ADMM_REPO_ROOT       Main ADMM_FPGA git repository.
  ADMM_WORKTREE_ROOT   Parent directory for per-job git worktrees.
  ADMM_RESULTS_ROOT    Parent directory for archived raw results.
  ADMM_BUILD_ROOT      Parent directory for auxiliary per-job build products.
  ADMM_CONFIG_ID       Short config/candidate id.
  ADMM_COMMIT          Candidate commit or ref.

Optional environment:
  ADMM_HORIZON                 Default: 40
  ADMM_TRAJ_SHAPE              Default: star_hold
  ADMM_ITERATIONS_OVERRIDE     Default: default
  ADMM_ENABLE_TRAJECTORY       Default: 1
  ADMM_SOLVER_ARCH             Default: staged_a
  ADMM_SIM_FREQ                Default: 500
  ADMM_TRAJ_START_STEP         Default: 0
  ADMM_CSIM_DURATION_S         Default: 5
  ADMM_CSIM_TIMEOUT_S          Default: 1800
  ADMM_RUN_CSIM                Default: 0
  ADMM_BOARD                   Default: custom
  ADMM_RUN_BITSTREAM           Default: 0
  ADMM_PATCH_FILE              Optional git-apply patch to apply after checkout.
  ADMM_COMPARISON_VIEW         Optional label, e.g. end_to_end_native_trajectory.
  ADMM_PYTHON_VENV             Optional Python venv directory.
  ADMM_TOOLCHAIN_SETUP         Optional shell file to source before running tools.
  ADMM_KEEP_WORKTREE           Default: 1
  PYTHON                       Default: python3
  VITIS_RUN                    Default: vitis-run
  VITIS_HLS                    Default: v++
  VIVADO                       Default: vivado
  VIVADO_MAX_THREADS           Optional Vivado max thread count.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "error: $name is required" >&2
    usage >&2
    exit 2
  fi
}

require_env ADMM_REPO_ROOT
require_env ADMM_WORKTREE_ROOT
require_env ADMM_RESULTS_ROOT
require_env ADMM_BUILD_ROOT
require_env ADMM_CONFIG_ID
require_env ADMM_COMMIT

DEFAULT_TOOLCHAIN_SETUP="$SCRIPT_DIR/setup_xilinx_2025_2.sh"
if [[ -z "${ADMM_TOOLCHAIN_SETUP:-}" \
    && -x "$DEFAULT_TOOLCHAIN_SETUP" \
    && -r /home/agrillo/amdfpga/2025.2/Vivado/settings64.sh \
    && -r /home/agrillo/amdfpga/2025.2/Vitis/settings64.sh ]]; then
  ADMM_TOOLCHAIN_SETUP="$DEFAULT_TOOLCHAIN_SETUP"
fi

PYTHON="${PYTHON:-python3}"
VITIS_RUN="${VITIS_RUN:-vitis-run}"
VITIS_HLS="${VITIS_HLS:-v++}"
VIVADO="${VIVADO:-vivado}"
if ! command -v "$VITIS_RUN" >/dev/null 2>&1 && [[ -x /home/agrillo/amdfpga/2025.2/Vitis/bin/vitis-run ]]; then
  VITIS_RUN=/home/agrillo/amdfpga/2025.2/Vitis/bin/vitis-run
fi
if ! command -v "$VITIS_HLS" >/dev/null 2>&1 && [[ -x /home/agrillo/amdfpga/2025.2/Vitis/bin/v++ ]]; then
  VITIS_HLS=/home/agrillo/amdfpga/2025.2/Vitis/bin/v++
fi
if ! command -v "$VIVADO" >/dev/null 2>&1 && [[ -x /home/agrillo/amdfpga/2025.2/Vivado/bin/vivado ]]; then
  VIVADO=/home/agrillo/amdfpga/2025.2/Vivado/bin/vivado
fi

ADMM_HORIZON="${ADMM_HORIZON:-40}"
ADMM_TRAJ_SHAPE="${ADMM_TRAJ_SHAPE:-star_hold}"
ADMM_ITERATIONS_OVERRIDE="${ADMM_ITERATIONS_OVERRIDE:-default}"
ADMM_ENABLE_TRAJECTORY="${ADMM_ENABLE_TRAJECTORY:-1}"
ADMM_SOLVER_ARCH="${ADMM_SOLVER_ARCH:-staged_a}"
ADMM_SIM_FREQ="${ADMM_SIM_FREQ:-500}"
ADMM_TRAJ_START_STEP="${ADMM_TRAJ_START_STEP:-0}"
ADMM_CSIM_DURATION_S="${ADMM_CSIM_DURATION_S:-5}"
ADMM_CSIM_TIMEOUT_S="${ADMM_CSIM_TIMEOUT_S:-1800}"
ADMM_RUN_CSIM="${ADMM_RUN_CSIM:-0}"
ADMM_BOARD="${ADMM_BOARD:-custom}"
ADMM_RUN_BITSTREAM="${ADMM_RUN_BITSTREAM:-0}"
ADMM_KEEP_WORKTREE="${ADMM_KEEP_WORKTREE:-1}"
ADMM_COMPARISON_VIEW="${ADMM_COMPARISON_VIEW:-end_to_end_native_trajectory}"

ADMM_REPO_ROOT="$(cd "$ADMM_REPO_ROOT" && pwd)"
mkdir -p "$ADMM_WORKTREE_ROOT" "$ADMM_RESULTS_ROOT" "$ADMM_BUILD_ROOT"
ADMM_WORKTREE_ROOT="$(cd "$ADMM_WORKTREE_ROOT" && pwd)"
ADMM_RESULTS_ROOT="$(cd "$ADMM_RESULTS_ROOT" && pwd)"
ADMM_BUILD_ROOT="$(cd "$ADMM_BUILD_ROOT" && pwd)"

RUN_TAG="${SLURM_JOB_ID:-manual_$(date -u +%Y%m%dT%H%M%SZ)}"
REQUESTED_COMMIT="$ADMM_COMMIT"
RESOLVED_COMMIT="$(git -C "$ADMM_REPO_ROOT" rev-parse "$REQUESTED_COMMIT^{commit}")"
COMMIT_SHORT="$(git -C "$ADMM_REPO_ROOT" rev-parse --short "$RESOLVED_COMMIT")"
SAFE_CONFIG_ID="$(printf '%s' "$ADMM_CONFIG_ID" | tr -c 'A-Za-z0-9_.-' '_')"
RUN_ID="${SAFE_CONFIG_ID}_${COMMIT_SHORT}_${RUN_TAG}"

WORKTREE_DIR="$ADMM_WORKTREE_ROOT/$RUN_ID"
RESULT_DIR="$ADMM_RESULTS_ROOT/raw/$RUN_ID"
BUILD_DIR="$ADMM_BUILD_ROOT/$RUN_ID"
LOG_DIR="$RESULT_DIR/logs"
GIT_DIR="$RESULT_DIR/git"
GENERATED_DIR="$RESULT_DIR/generated"
REPORT_DIR="$RESULT_DIR/reports"
STATUS_FILE="$RESULT_DIR/status.txt"
FAILED_STEP=""
OVERALL_RC=0

mkdir -p "$LOG_DIR" "$GIT_DIR" "$GENERATED_DIR" "$REPORT_DIR" "$BUILD_DIR"

export ADMM_REPO_ROOT ADMM_WORKTREE_ROOT ADMM_RESULTS_ROOT ADMM_BUILD_ROOT
export ADMM_CONFIG_ID REQUESTED_COMMIT RESOLVED_COMMIT COMMIT_SHORT
export ADMM_HORIZON ADMM_TRAJ_SHAPE ADMM_ITERATIONS_OVERRIDE ADMM_ENABLE_TRAJECTORY
export ADMM_SOLVER_ARCH
export ADMM_SIM_FREQ ADMM_TRAJ_START_STEP ADMM_CSIM_DURATION_S ADMM_CSIM_TIMEOUT_S
export ADMM_RUN_CSIM ADMM_BOARD ADMM_RUN_BITSTREAM ADMM_COMPARISON_VIEW
export ADMM_PATCH_FILE="${ADMM_PATCH_FILE:-}"
export ADMM_TOOLCHAIN_SETUP="${ADMM_TOOLCHAIN_SETUP:-}"
export VITIS_RUN VITIS_HLS VIVADO
export WORKTREE_DIR RESULT_DIR BUILD_DIR RUN_ID

prepend_tool_dir() {
  local tool="$1"
  if [[ "$tool" == */* ]]; then
    local dir
    dir="$(dirname "$tool")"
    if [[ -d "$dir" ]]; then
      export PATH="$dir:$PATH"
    fi
  fi
}
prepend_tool_dir "$VITIS_RUN"
prepend_tool_dir "$VITIS_HLS"
prepend_tool_dir "$VIVADO"

if [[ -n "${ADMM_PYTHON_VENV:-}" ]]; then
  if [[ ! -f "$ADMM_PYTHON_VENV/bin/activate" ]]; then
    echo "error: ADMM_PYTHON_VENV does not contain bin/activate: $ADMM_PYTHON_VENV" >&2
    exit 2
  fi
  # shellcheck source=/dev/null
  source "$ADMM_PYTHON_VENV/bin/activate"
fi

if [[ -n "${ADMM_TOOLCHAIN_SETUP:-}" ]]; then
  # shellcheck source=/dev/null
  source "$ADMM_TOOLCHAIN_SETUP"
fi

write_metadata() {
  local path="$1"
  local exit_code="${2:-}"
  META_PATH="$path" META_EXIT_CODE="$exit_code" "$PYTHON" - <<'PY'
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

keys = [
    "ADMM_CONFIG_ID",
    "REQUESTED_COMMIT",
    "RESOLVED_COMMIT",
    "COMMIT_SHORT",
    "ADMM_HORIZON",
    "ADMM_TRAJ_SHAPE",
    "ADMM_ITERATIONS_OVERRIDE",
    "ADMM_ENABLE_TRAJECTORY",
    "ADMM_SOLVER_ARCH",
    "ADMM_SIM_FREQ",
    "ADMM_TRAJ_START_STEP",
    "ADMM_CSIM_DURATION_S",
    "ADMM_CSIM_TIMEOUT_S",
    "ADMM_RUN_CSIM",
    "ADMM_BOARD",
    "ADMM_RUN_BITSTREAM",
    "ADMM_COMPARISON_VIEW",
    "ADMM_PATCH_FILE",
    "ADMM_TOOLCHAIN_SETUP",
    "VITIS_RUN",
    "VITIS_HLS",
    "VIVADO",
    "VIVADO_MAX_THREADS",
    "ADMM_REPO_ROOT",
    "ADMM_WORKTREE_ROOT",
    "ADMM_RESULTS_ROOT",
    "ADMM_BUILD_ROOT",
    "WORKTREE_DIR",
    "RESULT_DIR",
    "BUILD_DIR",
    "RUN_ID",
    "SLURM_JOB_ID",
    "SLURM_JOB_NAME",
    "SLURM_SUBMIT_DIR",
    "SLURM_CPUS_PER_TASK",
]
data = {key.lower(): os.environ.get(key, "") for key in keys}
data["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
if os.environ.get("META_EXIT_CODE", "") != "":
    data["exit_code"] = int(os.environ["META_EXIT_CODE"])
    data["failed_step"] = os.environ.get("FAILED_STEP", "")

worktree = Path(os.environ.get("WORKTREE_DIR", ""))
hls_dir = worktree / "vitis_projects" / "ADMM"

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

for name in ["trajectory_refs.csv", "traj_data.h", "traj_data_raw.h", "data.h"]:
    path = hls_dir / name
    if path.exists():
        data[f"{name.replace('.', '_')}_sha256"] = sha256(path)

traj_header = hls_dir / "traj_data.h"
if traj_header.exists():
    text = traj_header.read_text(errors="replace")
    for macro in ["TRAJ_Q_PACKED_ROWS", "TRAJ_Q_PACKED_COLS"]:
        m = re.search(rf"#define\s+{macro}\s+(\d+)", text)
        if m:
            data[macro.lower()] = int(m.group(1))

Path(os.environ["META_PATH"]).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY
}

archive_artifacts() {
  set +e
  if [[ -d "$WORKTREE_DIR/.git" || -f "$WORKTREE_DIR/.git" ]]; then
    git -C "$WORKTREE_DIR" rev-parse HEAD > "$GIT_DIR/worktree_head.txt" 2>&1
    git -C "$WORKTREE_DIR" status --short --branch > "$GIT_DIR/worktree_status.txt" 2>&1
    git -C "$WORKTREE_DIR" diff > "$GIT_DIR/worktree_dirty.patch" 2>&1
    if [[ -n "${ADMM_PATCH_FILE:-}" && -f "$ADMM_PATCH_FILE" ]]; then
      cp -a "$ADMM_PATCH_FILE" "$GIT_DIR/input_patch.patch"
    fi

    local hls_dir="$WORKTREE_DIR/vitis_projects/ADMM"
    local rtl_dir="$WORKTREE_DIR/vivado_project/vivado_project.srcs/sources_1/new"
    for file in \
      "$hls_dir/data.h" \
      "$hls_dir/test_data.h" \
      "$hls_dir/traj_data.h" \
      "$hls_dir/traj_data_raw.h" \
      "$hls_dir/admm_runtime_config.h" \
      "$hls_dir/trajectory_refs.csv" \
      "$rtl_dir/admm_autogen_params.vh"; do
      if [[ -f "$file" ]]; then
        cp -a "$file" "$GENERATED_DIR/"
      fi
    done

    if [[ -d "$WORKTREE_DIR/build/reports" ]]; then
      mkdir -p "$REPORT_DIR/vivado"
      cp -a "$WORKTREE_DIR/build/reports/." "$REPORT_DIR/vivado/"
    fi
    if [[ -d "$WORKTREE_DIR/build/logs" ]]; then
      mkdir -p "$REPORT_DIR/vivado_logs"
      cp -a "$WORKTREE_DIR/build/logs/." "$REPORT_DIR/vivado_logs/"
    fi
    if [[ -d "$hls_dir/ADMM/hls/syn/report" ]]; then
      mkdir -p "$REPORT_DIR/hls_synth"
      cp -a "$hls_dir/ADMM/hls/syn/report/." "$REPORT_DIR/hls_synth/"
    fi
    if [[ -d "$BUILD_DIR/hls_csim/ADMM_closed_loop/logs" ]]; then
      mkdir -p "$REPORT_DIR/hls_csim_logs"
      cp -a "$BUILD_DIR/hls_csim/ADMM_closed_loop/logs/." "$REPORT_DIR/hls_csim_logs/"
    fi
    find "$WORKTREE_DIR/build" -maxdepth 1 -type f \( -name '*.bit' -o -name '*.bin' -o -name '*.dcp' \) -print0 2>/dev/null |
      while IFS= read -r -d '' artifact; do
        mkdir -p "$RESULT_DIR/build_artifacts"
        cp -a "$artifact" "$RESULT_DIR/build_artifacts/"
      done
  fi
}

finish() {
  local rc=$?
  export FAILED_STEP
  archive_artifacts
  write_metadata "$RESULT_DIR/metadata_final.json" "$rc"
  if [[ "$ADMM_KEEP_WORKTREE" != "1" && -e "$WORKTREE_DIR" ]]; then
    git -C "$ADMM_REPO_ROOT" worktree remove --force "$WORKTREE_DIR" >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap finish EXIT

run_logged_in_dir() {
  local step="$1"
  local cwd="$2"
  shift 2
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $step: cwd=$cwd command=$*" | tee -a "$LOG_DIR/commands.log"
  set +e
  (
    cd "$cwd"
    "$@"
  ) > "$LOG_DIR/${step}.stdout.log" 2> "$LOG_DIR/${step}.stderr.log"
  local rc=$?
  set -e
  echo "$rc" > "$LOG_DIR/${step}.rc"
  if [[ "$rc" -ne 0 ]]; then
    FAILED_STEP="$step"
    echo "failed_step=$step" > "$STATUS_FILE"
    return "$rc"
  fi
  return 0
}

run_logged_env_in_dir() {
  local step="$1"
  local cwd="$2"
  shift 2
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $step: cwd=$cwd command=$*" | tee -a "$LOG_DIR/commands.log"
  set +e
  (
    cd "$cwd"
    ADMM_HORIZON_LENGTH="$ADMM_HORIZON" \
    ADMM_TRAJ_SHAPE="$ADMM_TRAJ_SHAPE" \
    ADMM_ENABLE_TRAJECTORY="$ADMM_ENABLE_TRAJECTORY" \
    "$@"
  ) > "$LOG_DIR/${step}.stdout.log" 2> "$LOG_DIR/${step}.stderr.log"
  local rc=$?
  set -e
  echo "$rc" > "$LOG_DIR/${step}.rc"
  if [[ "$rc" -ne 0 ]]; then
    FAILED_STEP="$step"
    echo "failed_step=$step" > "$STATUS_FILE"
    return "$rc"
  fi
  return 0
}

record_failure() {
  local step="$1"
  local rc="$2"
  if [[ -z "$FAILED_STEP" ]]; then
    FAILED_STEP="$step"
  else
    FAILED_STEP="${FAILED_STEP},${step}"
  fi
  OVERALL_RC=1
  echo "failed_step=$FAILED_STEP" > "$STATUS_FILE"
  echo "step $step failed with rc=$rc" | tee -a "$LOG_DIR/commands.log"
}

echo "started" > "$STATUS_FILE"
write_metadata "$RESULT_DIR/metadata_initial.json"
git -C "$ADMM_REPO_ROOT" status --short --branch > "$GIT_DIR/main_repo_status_at_start.txt" 2>&1

if [[ -e "$WORKTREE_DIR" ]]; then
  echo "error: worktree path already exists: $WORKTREE_DIR" >&2
  FAILED_STEP="prepare_worktree"
  exit 1
fi

run_logged_in_dir prepare_worktree "$ADMM_REPO_ROOT" git worktree add --detach "$WORKTREE_DIR" "$RESOLVED_COMMIT"
git -C "$WORKTREE_DIR" rev-parse HEAD > "$GIT_DIR/worktree_head_initial.txt"
git -C "$WORKTREE_DIR" status --short --branch > "$GIT_DIR/worktree_status_initial.txt"

if [[ -n "${ADMM_PATCH_FILE:-}" ]]; then
  if [[ ! -f "$ADMM_PATCH_FILE" ]]; then
    echo "error: ADMM_PATCH_FILE not found: $ADMM_PATCH_FILE" >&2
    FAILED_STEP="apply_patch"
    exit 1
  fi
  run_logged_in_dir apply_patch "$WORKTREE_DIR" git apply "$ADMM_PATCH_FILE"
fi

export ADMM_HORIZON_LENGTH="$ADMM_HORIZON"
export ADMM_TRAJ_SHAPE="$ADMM_TRAJ_SHAPE"
export ADMM_ENABLE_TRAJECTORY="$ADMM_ENABLE_TRAJECTORY"
if [[ "$ADMM_ITERATIONS_OVERRIDE" == "default" || -z "$ADMM_ITERATIONS_OVERRIDE" ]]; then
  unset ADMM_ITERATIONS
else
  export ADMM_ITERATIONS="$ADMM_ITERATIONS_OVERRIDE"
fi

SCRIPTS_DIR="$WORKTREE_DIR/scripts"
HLS_DIR="$WORKTREE_DIR/vitis_projects/ADMM"
CSIM_WORK_DIR="$BUILD_DIR/hls_csim/ADMM_closed_loop"
mkdir -p "$CSIM_WORK_DIR"

run_logged_env_in_dir generate_trajectory "$SCRIPTS_DIR" "$PYTHON" trajectory_generator.py
run_logged_env_in_dir generate_headers "$SCRIPTS_DIR" "$PYTHON" header_generator.py
write_metadata "$RESULT_DIR/metadata_after_generation.json"

if [[ "$ADMM_RUN_CSIM" == "1" ]]; then
  mkdir -p "$RESULT_DIR/closed_loop"
  echo "csim_duration_s=$ADMM_CSIM_DURATION_S" > "$RESULT_DIR/closed_loop/config.txt"
  echo "sim_freq_hz=$ADMM_SIM_FREQ" >> "$RESULT_DIR/closed_loop/config.txt"
  echo "traj_start_step=$ADMM_TRAJ_START_STEP" >> "$RESULT_DIR/closed_loop/config.txt"
  set +e
  (
    cd "$HLS_DIR"
    timeout "$ADMM_CSIM_TIMEOUT_S" env \
      "ADMM_HORIZON_LENGTH=$ADMM_HORIZON" \
      "ADMM_TRAJ_SHAPE=$ADMM_TRAJ_SHAPE" \
      "ADMM_ENABLE_TRAJECTORY=$ADMM_ENABLE_TRAJECTORY" \
      "ADMM_SOLVER_ARCH=$ADMM_SOLVER_ARCH" \
      "ADMM_SIM_FREQ=$ADMM_SIM_FREQ" \
      "ADMM_SIM_DURATION_S=$ADMM_CSIM_DURATION_S" \
      "ADMM_TRAJ_START_STEP=$ADMM_TRAJ_START_STEP" \
      "ADMM_CSIM_TRAJ_PATH=$RESULT_DIR/closed_loop/trajectory.csv" \
      "ADMM_FAIL_ON_EARLY_STOP=1" \
      "$VITIS_RUN" --mode hls --csim --config ./hls_eval_config.cfg --work_dir "$CSIM_WORK_DIR"
  ) > "$LOG_DIR/closed_loop_csim.stdout.log" 2> "$LOG_DIR/closed_loop_csim.stderr.log"
  rc=$?
  set -e
  echo "$rc" > "$LOG_DIR/closed_loop_csim.rc"
  if [[ "$rc" -ne 0 ]]; then
    record_failure "closed_loop_csim" "$rc"
  fi
fi

set +e
(
  cd "$WORKTREE_DIR"
  make BOARD="$ADMM_BOARD" PYTHON="$PYTHON" VITIS_HLS="$VITIS_HLS" VIVADO="$VIVADO" vivado
) > "$LOG_DIR/vivado.stdout.log" 2> "$LOG_DIR/vivado.stderr.log"
rc=$?
set -e
echo "$rc" > "$LOG_DIR/vivado.rc"
if [[ "$rc" -ne 0 ]]; then
  record_failure "vivado" "$rc"
fi

if [[ "$ADMM_RUN_BITSTREAM" == "1" && "$OVERALL_RC" -eq 0 ]]; then
  set +e
  (
    cd "$WORKTREE_DIR"
    make BOARD="$ADMM_BOARD" PYTHON="$PYTHON" VITIS_HLS="$VITIS_HLS" VIVADO="$VIVADO" bit
  ) > "$LOG_DIR/bitstream.stdout.log" 2> "$LOG_DIR/bitstream.stderr.log"
  rc=$?
  set -e
  echo "$rc" > "$LOG_DIR/bitstream.rc"
  if [[ "$rc" -ne 0 ]]; then
    record_failure "bitstream" "$rc"
  fi
fi

if [[ "$OVERALL_RC" -ne 0 ]]; then
  exit "$OVERALL_RC"
fi

echo "completed" > "$STATUS_FILE"
