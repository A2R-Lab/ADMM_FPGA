import numpy as np
import argparse
from crazyloihimodel import CrazyLoihiModel


# Default number of ADMM iterations to run in hardware
DEFAULT_ADMM_ITERS = 28

# Run controller at 50 Hz
timer_period = 0.02  # seconds

# Default horizon length
DEFAULT_HORIZON = 20

parser = argparse.ArgumentParser(description="Generate ADMM FPGA headers.")
parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON, help="MPC horizon length.")
parser.add_argument("--admm-iters", type=int, default=DEFAULT_ADMM_ITERS, help="Number of ADMM iterations.")
args = parser.parse_args()

if args.horizon <= 0:
    raise ValueError("--horizon must be > 0")
if args.admm_iters <= 0:
    raise ValueError("--admm-iters must be > 0")

N = args.horizon
ADMM_ITERS = args.admm_iters

rho = 64
rho_mult = 1

# Initialize goal state
xg = np.zeros(13)
xg[3] = 1.0  # unit quaternion
# Create quadrotor instance
quad = CrazyLoihiModel(freq=1/timer_period)
ug = quad.hover_thrust

# Get linearized system
A, B = quad.get_linearized_dynamics(xg, ug)

# Cost matrices
max_dev_x = np.array([0.075, 0.075, 0.075, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.7, 0.7, 0.2])
max_dev_u = np.array([0.5, 0.5, 0.5, 0.5])
Q = np.diag(1./max_dev_x**2)
R = np.diag(1./max_dev_u**2)

# Control input constraints
u_max = np.array([1.0 - ug[0]] * 4)
u_min = np.array([-ug[0]] * 4)


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


# Number of states and inputs
n = A.shape[0]
m = B.shape[1]

# Total number of variables
num_x = n * (N + 1)
num_u = m * N
num_var = num_x + num_u

# Build Hessian matrix P
blocks = []
for k in range(N):
    blocks.append(Q)     # Q_k
    blocks.append(R)     # R_k
blocks.append(Q)         # Final terminal Q_N

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

# Input constraints

# Total number of constraints (only 1 per input)
n_ineq = m * N
A_ineq = np.zeros((n_ineq, num_var))

row = 0
for k in range(N):
    # u_start = n*(N+1) + k*m
    u_start = k * (n + m) + n

    # print("u_start:", u_start)
    u_end   = u_start + m

    # Select ONLY u_k in the full z vector
    A_ineq[  row:row+m    , u_start:u_end] = np.eye(m)
    row += m

A = np.vstack([A_eq, A_ineq])


l = np.hstack([b_eq, np.tile(u_min, N)])
u = np.hstack([b_eq, np.tile(u_max, N)])


rho_vect = rho * np.ones(P.shape[0])
rho_vect[np.where(l == u)[0]] *= rho_mult
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

def ADMM_iteration(l, u, iter):
    x = np.zeros(P.shape[0])
    z = np.zeros(P.shape[0])
    y = np.zeros(P.shape[0])

    for i in range(iter):
        x = np.linalg.solve(KKT, A.T @ ((rho * z) - y))
        z = np.clip(A @ x + (y / rho), l, u)
        y = y + rho * (A @ x - z)
    
    return x, z, y

def testOSQP(l,u, iter):
    import osqp
    from scipy import sparse

    P_csc = sparse.csc_matrix(P)
    A_csc = sparse.csc_matrix(A)

    prob = osqp.OSQP()
    prob.setup(P_csc, np.zeros(P.shape[0]), A_csc, l, u, verbose=False, rho=rho, adaptive_rho = False, max_iter=iter)
    res = prob.solve()

    return res.x

L_banded = convert_chol_to_banded_storage(L)
LT_banded = convert_chol_transposed_to_banded_storage(L.T)
A_sparse_data, A_sparse_indexes, A_n_bits_idx = convert_matrix_to_sparse_storage(A)
AT_sparse_data, AT_sparse_indexes, AT_n_bits_idx = convert_matrix_to_sparse_storage(A.T)
constants = {}
constants["HORIZON_LENGTH"] = N
constants["STATE_SIZE"] = n
constants["N_VAR"] = num_var
constants["START_INEQ"] = A_eq.shape[0]
constants["RHO_SHIFT"] = int(np.log2(rho))
constants["U_MIN"] = u_min[0]
constants["U_MAX"] = u_max[0]
constants["ADMM_ITERS"] = ADMM_ITERS
constants["U_HOVER"] = ug[0]

data = []
data.append(generate_constants_header(constants))
data.append(generate_matrix_header(L_banded, "L_banded"))
data.append(generate_matrix_header(LT_banded, "LT_banded"))
data.append(generate_matrix_header(A_sparse_data, "A_sparse_data"))
data.append(generate_matrix_header(A_sparse_indexes, "A_sparse_indexes", type=f"ap_uint<{A_n_bits_idx}>"))
data.append(generate_matrix_header(AT_sparse_data, "AT_sparse_data"))
data.append(generate_matrix_header(AT_sparse_indexes, "AT_sparse_indexes", type=f"ap_uint<{AT_n_bits_idx}>"))

generate_full_header(data, filename="./vitis_projects/ADMM/data.h")

# Test header generation
np.random.seed(0)
rand_vec = np.random.randn(L_banded.shape[0])
test_data = []
test_data.append(generate_vector_header(rand_vec, "random_vector", type="double"))

forw_subst_out = np.linalg.solve(L, rand_vec)
test_data.append(generate_vector_header(forw_subst_out, "forw_subst_out", type="double"))

back_subst_out = np.linalg.solve(L.T, rand_vec)
test_data.append(generate_vector_header(back_subst_out, "back_subst_out", type="double"))

A_mul_out = A @ rand_vec
test_data.append(generate_vector_header(A_mul_out, "A_mul_out", type="double"))

AT_mul_out = A.T @ rand_vec
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

generate_full_header(test_data, filename="./vitis_projects/ADMM/test_data.h", guard="TEST_DATA_H")

# OSQP_x = testOSQP(l, u, iter=1000)

# print("Comparing OSQP and ADMM results after 100 iterations:")
# print(x[-16:])
# print(OSQP_x[-16:])
# x_diff = np.linalg.norm(OSQP_x - x) / np.linalg.norm(OSQP_x)
# print(f"OSQP vs ADMM differences after 100 iterations: norm rel error : {x_diff}")
