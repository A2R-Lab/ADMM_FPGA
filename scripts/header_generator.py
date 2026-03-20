from pathlib import Path
import re
import os
import numpy as np
from crazyloihimodel import CrazyLoihiModel
from parameters import (
    AMP_X,
    AMP_Y,
    HORIZON_LENGTH,
    Q_DIAG,
    R_DIAG,
    RHO_EQ_PARAM,
    RHO_INEQ_PARAM,
    DELAY_STEPS,
    ADMM_USE_FLOAT,
    ADMM_ITERATIONS,
    MPC_LINEAR_DRAG_XY,
    MPC_LINEAR_DRAG_Z,
    STAR_INNER_RATIO,
    TRAJ_WARMSTART_PAD,
    TRAJ_TICK_DIV,
    TRAJ_SHAPE,
    U_ABS_MIN,
    U_ABS_MAX,
    XY_MIN,
    XY_MAX,
)


# Number of ADMM iterations to run in hardware
ADMM_ITERS = int(ADMM_ITERATIONS)

# Run controller at 50 Hz
timer_period = 0.02  # seconds

# Horizon length
N = HORIZON_LENGTH

# ADMM row-wise rho values (single source of truth for both KKT generation
# and emitted C/HLS constants).
rho_ineq = RHO_INEQ_PARAM
rho_eq = RHO_EQ_PARAM
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
TRAJ_DATA_HEADER_PATH = REPO_ROOT / "vitis_projects" / "ADMM" / "traj_data.h"
DATA_HEADER_PATH = REPO_ROOT / "vitis_projects" / "ADMM" / "data.h"
TEST_DATA_HEADER_PATH = REPO_ROOT / "vitis_projects" / "ADMM" / "test_data.h"
RTL_PARAMS_HEADER_PATH = REPO_ROOT / "vivado_project" / "vivado_project.srcs" / "sources_1" / "new" / "admm_autogen_params.vh"
RUNTIME_CONFIG_HEADER_PATH = REPO_ROOT / "vitis_projects" / "ADMM" / "admm_runtime_config.h"
ABQR_OVERRIDE_PATH = os.environ.get("ADMM_ABQR_OVERRIDE_PATH", "").strip()

# Initialize goal state
xg = np.zeros(13)
xg[3] = 1.0  # unit quaternion
# Create quadrotor instance
quad = CrazyLoihiModel(freq=1/timer_period)
ug = quad.hover_thrust
mass_kg = quad.mass

def _parse_matrix_block(text: str, name: str, rows: int, cols: int) -> np.ndarray:
    m = re.search(rf"\b{name}\s*<<\s*(.*?);", text, re.DOTALL)
    if m is None:
        raise ValueError(f"Missing block for {name} in override file")
    body = m.group(1)
    nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?f?", body)
    vals = [float(tok[:-1] if tok.lower().endswith("f") else tok) for tok in nums]
    expected = rows * cols
    if len(vals) != expected:
        raise ValueError(f"{name} expected {expected} values, found {len(vals)}")
    return np.asarray(vals, dtype=np.float64).reshape(rows, cols)


def _load_abqr_override(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    text = path.read_text()
    A_ovr = _parse_matrix_block(text, "A", 12, 12)
    B_ovr = _parse_matrix_block(text, "B", 12, 4)
    Q_ovr = _parse_matrix_block(text, "Q", 12, 12)
    R_ovr = _parse_matrix_block(text, "R", 4, 4)
    return A_ovr, B_ovr, Q_ovr, R_ovr


if ABQR_OVERRIDE_PATH:
    override_path = Path(ABQR_OVERRIDE_PATH)
    A, B, Q, R = _load_abqr_override(override_path)
    print(f"Using matrix override file: {override_path}")
else:
    # Get linearized system
    A, B = quad.get_linearized_dynamics(xg, ug)

    # Match dominant plant non-ideality (linear drag) in the MPC model.
    A[6, 6] -= timer_period * (MPC_LINEAR_DRAG_XY / mass_kg)
    A[7, 7] -= timer_period * (MPC_LINEAR_DRAG_XY / mass_kg)
    A[8, 8] -= timer_period * (MPC_LINEAR_DRAG_Z / mass_kg)

    q_diag = Q_DIAG
    Q = np.diag(q_diag)
    R = np.diag(R_DIAG)


def load_traj_length_from_header(header_path: Path, horizon: int) -> int:
    text = header_path.read_text()
    m = re.search(r"#define\s+TRAJ_Q_PACKED_ROWS\s+(\d+)", text)
    if m is None:
        raise ValueError(f"Could not find TRAJ_Q_PACKED_ROWS in {header_path}")
    rows = int(m.group(1))
    traj_length = rows - horizon
    if traj_length <= 0:
        raise ValueError(f"Invalid TRAJ_LENGTH derived from {header_path}: {traj_length}")
    return traj_length

# Control input constraints
u_max = np.array([U_ABS_MAX - ug[0]] * 4)
u_min = np.array([U_ABS_MIN - ug[0]] * 4)


def build_Aeq_interleaved(Anp, Bnp, N):
    """
    Build dense A_eq and b_eq for interleaved ordering:
    z = [ x0, u0, x1, u1, ..., xN ]

    A_eq rows:
    [x0 = x_init]         ← initial condition
    [dynamics constraints] x1 - A x0 - B u0 = 0
                            x2 - A x1 - B u1 = 0
                                ...
                            xN - A x(N-1) - B u(N-1) = 0
    """

    n = Anp.shape[0]
    m = Bnp.shape[1]

    num_rows = (N + 1) * n     # (1 initial + N dynamics)
    num_var  = (N + 1) * n + N * m

    def idx_x(k):   # k in 0..N
        return k * (n + m)

    def idx_u(k):   # k in 0..N-1
        return k * (n + m) + n

    A_eq = np.zeros((num_rows, num_var))
    b_eq = np.zeros(num_rows)

    # 1) Initial condition: x0 = x_init
    A_eq[0:n, idx_x(0):idx_x(0) + n] = np.eye(n)
    b_eq[0:n] = np.zeros(n) #x0.reshape(-1)

    # 2) Dynamics constraints
    for k in range(N):
        row_start = (k + 1) * n  # shifted down by n rows
        xk_col    = idx_x(k)
        xkp1_col  = idx_x(k + 1)
        uk_col    = idx_u(k)

        A_eq[row_start:row_start + n, xkp1_col:xkp1_col + n] += np.eye(n)
        A_eq[row_start:row_start + n, xk_col:xk_col + n]     -= Anp
        A_eq[row_start:row_start + n, uk_col:uk_col + m]     -= Bnp

    return A_eq, b_eq


def compute_lqr_terminal_cost(
    A: np.ndarray,
    B: np.ndarray,
    Q: np.ndarray,
    R: np.ndarray,
    *,
    max_iter: int = 2000,
    tol: float = 1e-10,
) -> np.ndarray:
    """Solve the discrete-time algebraic Riccati equation via fixed-point iteration."""
    P = Q.astype(np.float64).copy()
    for _ in range(max_iter):
        bt_p = B.T @ P
        s = R + bt_p @ B
        k = np.linalg.solve(s, bt_p @ A)
        p_next = Q + A.T @ P @ A - A.T @ P @ B @ k
        p_next = 0.5 * (p_next + p_next.T)
        if np.linalg.norm(p_next - P, ord="fro") < tol:
            return p_next
        P = p_next
    raise RuntimeError("LQR terminal-cost Riccati iteration did not converge")


# Number of states and inputs
n = A.shape[0]
m = B.shape[1]

# Total number of variables
num_x = n * (N + 1)
num_u = m * N
num_var = num_x + num_u

# Build Hessian matrix P
Q_terminal = compute_lqr_terminal_cost(A, B, Q, R)
blocks = []
for k in range(N):
    blocks.append(Q)     # Q_k
    blocks.append(R)     # R_k
blocks.append(Q)  # Final terminal Q_N from discrete LQR

# total size
total = sum(block.shape[0] for block in blocks)

# initialize final matrix
P = np.zeros((total, total))

# fill block diagonal piece by piece
start = 0
for block in blocks:
    size = block.shape[0]
    P[start:start+size, start:start+size] = block
    start += size

A_eq, b_eq = build_Aeq_interleaved(A, B, N)

# Input + state box constraints
num_input_ineq = m * N
num_state_box_ineq = 2 * N  # x and y for predicted states k=1..N
n_ineq = num_input_ineq + num_state_box_ineq
A_ineq = np.zeros((n_ineq, num_var))
START_U_INEQ = 0
START_XY_INEQ = num_input_ineq

row = 0
# Input box constraints: u_min <= u_k <= u_max
for k in range(N):
    u_start = k * (n + m) + n
    u_end = u_start + m
    A_ineq[row : row + m, u_start:u_end] = np.eye(m)
    row += m

# State box constraints: -1 <= x_k <= 1 and -1 <= y_k <= 1
# Apply only to predicted states (k=1..N). k=0 is measured/current state and
# is already enforced by the equality constraint x0 = current_state.
for k in range(1, N + 1):
    xk_start = k * (n + m)
    # x position
    A_ineq[row, xk_start + 0] = 1.0
    row += 1
    # y position
    A_ineq[row, xk_start + 1] = 1.0
    row += 1

if row != n_ineq:
    raise RuntimeError(f"Internal inequality row mismatch: row={row}, n_ineq={n_ineq}")

A = np.vstack([A_eq, A_ineq])


# Keep constraints aligned with trajectory frame for the rotated-square mode:
# midpoint of one side is treated as origin, so shift XY bounds equally.
xy_bound_shift = 0.0
xy_bound_halfspan = None
if TRAJ_SHAPE == "diamond1m_hold":
    xy_bound_shift = 0.5 / np.sqrt(2.0)  # side=1.0 => midpoint component
    # Match constraint box side to trajectory side (1.0 m).
    xy_bound_halfspan = 0.5
elif TRAJ_SHAPE == "star_hold":
    diagonal_angle = np.arctan2(AMP_X, AMP_Y)
    xy_bound_shift = AMP_X * STAR_INNER_RATIO * np.cos(diagonal_angle)

if xy_bound_halfspan is None:
    xy_min_eff = XY_MIN - xy_bound_shift
    xy_max_eff = XY_MAX - xy_bound_shift
else:
    xy_min_eff = -xy_bound_halfspan - xy_bound_shift
    xy_max_eff = xy_bound_halfspan - xy_bound_shift
l_u = np.hstack([np.tile(u_min, N), np.full(num_state_box_ineq, xy_min_eff)])
u_u = np.hstack([np.tile(u_max, N), np.full(num_state_box_ineq, xy_max_eff)])
l = np.hstack([b_eq, l_u])
u = np.hstack([b_eq, u_u])


rho_vect = rho_ineq * np.ones(A.shape[0])
rho_vect[np.where(l == u)[0]] = rho_eq
rho_diag = np.diag(rho_vect)

eq_indices = np.arange(n * (N + 1))

KKT = P + A.T @ rho_diag @ A

L = np.linalg.cholesky(KKT)

def print_matrix(mat, name):
    print(f"{name}:")
    for row in mat:
        for val in row:
            str = f" {val:8.4f}" if val != 0 else "   .    "
            print(str, end="")
        print()
    print()

def get_max_bandwidth(L):
    n = L.shape[0]
    max_bandwidth = 0

    for i in range(n):
        row_nonzeros = np.nonzero(L[i, :])[0]
        if len(row_nonzeros) == 0:
            continue
        first_nonzero = row_nonzeros[0]
        last_nonzero = row_nonzeros[-1]
        bandwidth = last_nonzero - first_nonzero + 1
        if bandwidth > max_bandwidth:
            max_bandwidth = bandwidth

    return max_bandwidth

def convert_matrix_to_sparse_storage(M):
    n = M.shape[0]
    k = np.max([np.count_nonzero(M[i, :]) for i in range(n)])
    M_data = np.zeros((n, k))
    M_indexes = np.zeros((n, k), dtype=np.uint)
    
    for i in range(n):
        row_nonzeros = np.nonzero(M[i, :])[0]
        for j, col_idx in enumerate(row_nonzeros):
            M_data[i, j] = M[i, col_idx]
            M_indexes[i, j] = col_idx

    n_bits_idx = int(np.ceil(np.log2(np.max(M_indexes) + 1)))
    return M_data, M_indexes, n_bits_idx

def convert_chol_to_banded_storage(L):
    n = L.shape[0]
    max_bandwidth = get_max_bandwidth(L)
    L_row = np.zeros((n, max_bandwidth))
    
    for i in range(n):
        # Start column index of the band for this row
        start_col = max(0, i - max_bandwidth + 1)
        
        # Extract elements from start_col to diagonal (inclusive)
        row_values = [L[i, j] for j in range(start_col, i + 1)]
        
        # Pad with zeros on the left if needed
        while len(row_values) < max_bandwidth:
            row_values.insert(0, 0.0)
        
        row_values[-1] = 1.0 / L[i, i]  # Store reciprocal of diagonal

        L_row[i, :] = row_values
    
    return L_row

def convert_chol_transposed_to_banded_storage(L):
    n = L.shape[0]
    max_bandwidth = get_max_bandwidth(L)
    L_row = np.zeros((n, max_bandwidth))
    
    for i in range(n):
        end_col = min(n, i + max_bandwidth)        

        # print("i:",i," end_col:",end_col)

        row_values = [L[i, j] for j in range(i, end_col)]
        
        # Pad with zeros on the left if needed
        while len(row_values) < max_bandwidth:
            row_values.append(0.0)
        
        row_values[0] = 1.0 / L[i, i]  # Store reciprocal of diagonal

        L_row[i, :] = row_values
    
    return L_row


def generate_constants_header(constants_dict):
    lines = []
    lines.append("// Constants definitions\n")
    for name, value in constants_dict.items():
        lines.append(f"#define {name} {value}\n")
    lines.append("// end constants definitions\n")
    return "".join(lines)


def generate_verilog_params_header(constants_dict):
    lines = []
    lines.append("// Auto-generated by scripts/header_generator.py. Do not edit.\n")
    lines.append("`ifndef ADMM_AUTOGEN_PARAMS_VH\n")
    lines.append("`define ADMM_AUTOGEN_PARAMS_VH\n\n")
    lines.append(f"`define ADMM_HORIZON_LENGTH {constants_dict['HORIZON_LENGTH']}\n")
    lines.append(f"`define ADMM_N_STATE {constants_dict['STATE_SIZE']}\n")
    lines.append(f"`define ADMM_STAGE_SIZE {constants_dict['STAGE_SIZE']}\n")
    lines.append(f"`define ADMM_N_VAR {constants_dict['N_VAR']}\n")
    lines.append(f"`define ADMM_N_CONSTR {constants_dict['N_CONSTR']}\n")
    lines.append(f"`define ADMM_START_INEQ {constants_dict['START_INEQ']}\n")
    lines.append(f"`define ADMM_DELAY_STEPS {constants_dict['DELAY_STEPS']}\n")
    lines.append("`endif // ADMM_AUTOGEN_PARAMS_VH\n")
    return "".join(lines)


def generate_runtime_config_header() -> str:
    lines = []
    lines.append("// Auto-generated by scripts/header_generator.py. Do not edit.\n")
    lines.append("#ifndef ADMM_RUNTIME_CONFIG_H\n")
    lines.append("#define ADMM_RUNTIME_CONFIG_H\n\n")
    lines.append(f"#define ADMM_USE_FLOAT {1 if ADMM_USE_FLOAT else 0}\n")
    lines.append(f"#define ADMM_ITERATIONS {int(ADMM_ITERATIONS)}\n")
    lines.append("\n#endif // ADMM_RUNTIME_CONFIG_H\n")
    return "".join(lines)

def generate_matrix_header(M, name, type="fp_t"):
    size_0, size_1 = M.shape
    lines = []
    lines.append(f"// Matrix {name} of size {size_0} x {size_1}\n")
    lines.append(f"#define {name.upper()}_ROWS {size_0}\n")
    lines.append(f"#define {name.upper()}_COLS {size_1}\n")
    lines.append(f"const {type} {name}[{name.upper()}_ROWS][{name.upper()}_COLS] = {{\n")
    for i in range(size_0):
        lines.append("   { " + ", ".join(f"({type}){M[i,j]:.8f}" for j in range(size_1)) + " },\n")
    lines.append(f"}};\n// end Matrix {name}\n")
    return "".join(lines)

def generate_vector_header(v, name, type="fp_t"):
    size = v.shape[0]
    lines = []
    lines.append(f"// Vector {name} of size {size}\n")
    lines.append(f"#define {name.upper()}_SIZE {size}\n")
    lines.append(f"const {type} {name}[{name.upper()}_SIZE] = {{\n")
    for i in range(size):
        lines.append(f"   ({type}){v[i]:.8f},\n")
    lines.append(f"}};\n// end Vector {name}\n")
    return "".join(lines)

def generate_full_header(data, filename="data.h", guard="DATA_H"):
    with open(filename, "w") as f:
        f.write(f"#ifndef {guard}\n")
        f.write(f"#define {guard}\n\n")

        f.write('#include "data_types.h"\n\n')
        
        for d in data:
            f.write(d)
            f.write("\n// ===================== \n\n")
        
        f.write(f"#endif // {guard}\n")

def _checked_pow2_shift(name: str, value: int) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    shift = int(np.log2(value))
    if (1 << shift) != value:
        raise ValueError(f"{name} must be a power of two for shift-based rho ops, got {value}")
    return shift


def ADMM_iteration(l, u, iter):
    x = np.zeros(P.shape[0])
    z = np.zeros(A.shape[0])
    y = np.zeros(A.shape[0])
    q_vec = np.zeros(P.shape[0])
    state_rows = n
    ineq_start = A_eq.shape[0]
    u_ineq_start = A_eq.shape[0] + START_U_INEQ
    xy_ineq_start = A_eq.shape[0] + START_XY_INEQ

    for _ in range(iter):
        x = np.linalg.solve(KKT, A.T @ ((rho_vect * z) - y) - q_vec)
        Ax = A @ x

        z_new = np.zeros_like(z)
        for idx in range(A.shape[0]):
            if idx < state_rows:
                z_new[idx] = l[idx]
            elif idx < ineq_start:
                z_new[idx] = 0.0
            else:
                zi = Ax[idx] + (y[idx] / rho_vect[idx])
                if idx >= xy_ineq_start:
                    z_new[idx] = np.clip(zi, l[idx], u[idx])
                elif idx >= u_ineq_start:
                    z_new[idx] = np.clip(zi, l[idx], u[idx])
                else:
                    z_new[idx] = np.clip(zi, l[idx], u[idx])

        y = y + rho_vect * (Ax - z_new)
        z = z_new
    
    return x, z, y

def testOSQP(l,u, iter):
    import osqp
    from scipy import sparse

    P_csc = sparse.csc_matrix(P)
    A_csc = sparse.csc_matrix(A)

    prob = osqp.OSQP()
    prob.setup(P_csc, np.zeros(P.shape[0]), A_csc, l, u, verbose=False, rho=rho_eq, adaptive_rho = False, max_iter=iter)
    res = prob.solve()

    return res.x

L_banded = convert_chol_to_banded_storage(L)
LT_banded = convert_chol_transposed_to_banded_storage(L.T)
A_sparse_data, A_sparse_indexes, A_n_bits_idx = convert_matrix_to_sparse_storage(A)
AT_sparse_data, AT_sparse_indexes, AT_n_bits_idx = convert_matrix_to_sparse_storage(A.T)
constants = {}
constants["HORIZON_LENGTH"] = N
constants["STATE_SIZE"] = n
constants["INPUT_SIZE"] = m
constants["STAGE_SIZE"] = n + m
constants["N_VAR"] = num_var
constants["N_CONSTR"] = A.shape[0]
constants["N_INEQ"] = n_ineq
constants["START_INEQ"] = A_eq.shape[0]
constants["START_U_INEQ"] = A_eq.shape[0] + START_U_INEQ
constants["START_XY_INEQ"] = A_eq.shape[0] + START_XY_INEQ
constants["DELAY_STEPS"] = DELAY_STEPS
rho_shift_ineq = _checked_pow2_shift("rho_ineq", int(rho_ineq))
rho_shift_eq = _checked_pow2_shift("rho_eq", int(rho_eq))
constants["RHO_SHIFT_INEQ"] = rho_shift_ineq
constants["RHO_SHIFT_EQ"] = rho_shift_eq
# Backward-compat alias for existing code/tests that still use RHO_SHIFT.
constants["RHO_SHIFT"] = rho_shift_eq
constants["U_MIN"] = u_min[0]
constants["U_MAX"] = u_max[0]
constants["XY_MIN"] = xy_min_eff
constants["XY_MAX"] = xy_max_eff
constants["U_HOVER"] = ug[0]
constants["TRAJ_LENGTH"] = load_traj_length_from_header(TRAJ_DATA_HEADER_PATH, horizon=N)
constants["TRAJ_TICK_DIV"] = TRAJ_TICK_DIV
constants["TRAJ_WARMSTART_PAD"] = TRAJ_WARMSTART_PAD

data = []
data.append(generate_constants_header(constants))
data.append(generate_matrix_header(L_banded, "L_banded"))
data.append(generate_matrix_header(LT_banded, "LT_banded"))
data.append(generate_matrix_header(A_sparse_data, "A_sparse_data"))
data.append(generate_matrix_header(A_sparse_indexes, "A_sparse_indexes", type=f"ap_uint<{A_n_bits_idx}>"))
data.append(generate_matrix_header(AT_sparse_data, "AT_sparse_data"))
data.append(generate_matrix_header(AT_sparse_indexes, "AT_sparse_indexes", type=f"ap_uint<{AT_n_bits_idx}>"))

generate_full_header(data, filename=str(DATA_HEADER_PATH))
RTL_PARAMS_HEADER_PATH.write_text(generate_verilog_params_header(constants))
RUNTIME_CONFIG_HEADER_PATH.write_text(generate_runtime_config_header())

# Test header generation
np.random.seed(0)
rand_vec_var = np.random.randn(L_banded.shape[0])
rand_vec_constr = np.random.randn(A.shape[0])
test_data = []
test_data.append(generate_vector_header(rand_vec_var, "random_vector", type="double"))

forw_subst_out = np.linalg.solve(L, rand_vec_var)
test_data.append(generate_vector_header(forw_subst_out, "forw_subst_out", type="double"))

back_subst_out = np.linalg.solve(L.T, rand_vec_var)
test_data.append(generate_vector_header(back_subst_out, "back_subst_out", type="double"))

A_mul_out = A @ rand_vec_var
test_data.append(generate_vector_header(A_mul_out, "A_mul_out", type="double"))

AT_mul_out = A.T @ rand_vec_constr
test_data.append(generate_vector_header(AT_mul_out, "AT_mul_out", type="double"))

l[0:3] = 0.1, 0.1, -0.1
u[0:3] = 0.1, 0.1, -0.1

x, z, y = ADMM_iteration(l, u, iter=1)
test_data.append(generate_vector_header(x, "ADMM_x_after_1_iter", type="double"))
test_data.append(generate_vector_header(z, "ADMM_z_after_1_iter", type="double"))
test_data.append(generate_vector_header(y, "ADMM_y_after_1_iter", type="double"))

x, z, y = ADMM_iteration(l, u, iter=10)
test_data.append(generate_vector_header(x, "ADMM_x_after_10_iter", type="double"))
test_data.append(generate_vector_header(z, "ADMM_z_after_10_iter", type="double"))
test_data.append(generate_vector_header(y, "ADMM_y_after_10_iter", type="double"))

x, z, y = ADMM_iteration(l, u, iter=100)
test_data.append(generate_vector_header(x, "ADMM_x_after_100_iter", type="double"))
test_data.append(generate_vector_header(z, "ADMM_z_after_100_iter", type="double"))
test_data.append(generate_vector_header(y, "ADMM_y_after_100_iter", type="double"))

x, z, y = ADMM_iteration(l, u, iter=50)
test_data.append(generate_vector_header(x, "ADMM_x_after_50_iter", type="double"))
test_data.append(generate_vector_header(z, "ADMM_z_after_50_iter", type="double"))
test_data.append(generate_vector_header(y, "ADMM_y_after_50_iter", type="double"))

# Reference snapshot matching the configured hardware iteration count.
x, z, y = ADMM_iteration(l, u, iter=ADMM_ITERS)
test_data.append(generate_vector_header(x, "ADMM_x_after_hw_iters", type="double"))
test_data.append(generate_vector_header(z, "ADMM_z_after_hw_iters", type="double"))
test_data.append(generate_vector_header(y, "ADMM_y_after_hw_iters", type="double"))

generate_full_header(test_data, filename=str(TEST_DATA_HEADER_PATH), guard="TEST_DATA_H")

# OSQP_x = testOSQP(l, u, iter=1000)

# print("Comparing OSQP and ADMM results after 100 iterations:")
# print(x[-16:])
# print(OSQP_x[-16:])
# x_diff = np.linalg.norm(OSQP_x - x) / np.linalg.norm(OSQP_x)
# print(f"OSQP vs ADMM differences after 100 iterations: norm rel error : {x_diff}")
