import argparse
import os
import struct

import numpy as np

from crazyloihimodel import CrazyLoihiModel


# Number of ADMM iterations to run in hardware
ADMM_ITERS = 28

# Run controller at 50 Hz
timer_period = 0.02  # seconds

# Horizon length
DEFAULT_HORIZON = int(os.environ.get("ADMM_HORIZON", "20"))
N = DEFAULT_HORIZON

rho = 64
rho_mult = 1


# Initialize goal state
xg = np.zeros(13)
xg[3] = 1.0  # unit quaternion

# Create quadrotor instance
quad = CrazyLoihiModel(freq=1 / timer_period)
ug = quad.hover_thrust

# Get linearized system
A, B = quad.get_linearized_dynamics(xg, ug)

# Cost matrices
max_dev_x = np.array([0.075, 0.075, 0.075, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.7, 0.7, 0.2])
max_dev_u = np.array([0.5, 0.5, 0.5, 0.5])
Q = np.diag(1.0 / max_dev_x**2)
R = np.diag(1.0 / max_dev_u**2)

# Control input constraints
u_max = np.array([1.0 - ug[0]] * 4)
u_min = np.array([-ug[0]] * 4)


def parse_args():
    parser = argparse.ArgumentParser(description="Generate ADMM matrix artifacts.")
    parser.add_argument(
        "--horizon",
        type=int,
        default=DEFAULT_HORIZON,
        help="MPC horizon length N.",
    )
    parser.add_argument(
        "--index-storage-bits",
        type=int,
        default=16,
        choices=[16, 32],
        help="Storage width used for sparse index payload in matrices.bin.",
    )
    parser.add_argument(
        "--data-header",
        default="../vitis_projects/ADMM/data.h",
        help="Output path for legacy dense/sparse matrix header.",
    )
    parser.add_argument(
        "--test-header",
        default="../vitis_projects/ADMM/test_data.h",
        help="Output path for test vectors header.",
    )
    parser.add_argument(
        "--constants-header",
        default="../vitis_projects/ADMM/solver_constants.h",
        help="Output path for solver constants header.",
    )
    parser.add_argument(
        "--layout-header",
        default="../vitis_projects/ADMM/matrix_layout.h",
        help="Output path for DDR matrix layout header.",
    )
    parser.add_argument(
        "--blob-sim-header",
        default="../vitis_projects/ADMM/matrix_blob_sim.h",
        help="Output path for C simulation matrix blob header.",
    )
    parser.add_argument(
        "--blob-bin",
        default="../build/matrices.bin",
        help="Output path for packed binary blob used for QSPI->DDR preload.",
    )
    parser.add_argument(
        "--meta-vh",
        default="../vivado_project/vivado_project.srcs/sources_1/new/matrix_blob_meta.vh",
        help="Output path for generated Verilog metadata include (word count/checksum).",
    )
    return parser.parse_args()


def ensure_parent_dir(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def build_Aeq_interleaved(Anp, Bnp, horizon):
    """
    Build dense A_eq and b_eq for interleaved ordering:
    z = [ x0, u0, x1, u1, ..., xN ]

    A_eq rows:
    [x0 = x_init]         <- initial condition
    [dynamics constraints] x1 - A x0 - B u0 = 0
                            x2 - A x1 - B u1 = 0
                                ...
                            xN - A x(N-1) - B u(N-1) = 0
    """

    n = Anp.shape[0]
    m = Bnp.shape[1]

    num_rows = (horizon + 1) * n
    num_var = (horizon + 1) * n + horizon * m

    def idx_x(k):
        return k * (n + m)

    def idx_u(k):
        return k * (n + m) + n

    A_eq = np.zeros((num_rows, num_var))
    b_eq = np.zeros(num_rows)

    # 1) Initial condition: x0 = x_init
    A_eq[0:n, idx_x(0) : idx_x(0) + n] = np.eye(n)
    b_eq[0:n] = np.zeros(n)

    # 2) Dynamics constraints
    for k in range(horizon):
        row_start = (k + 1) * n
        xk_col = idx_x(k)
        xkp1_col = idx_x(k + 1)
        uk_col = idx_u(k)

        A_eq[row_start : row_start + n, xkp1_col : xkp1_col + n] += np.eye(n)
        A_eq[row_start : row_start + n, xk_col : xk_col + n] -= Anp
        A_eq[row_start : row_start + n, uk_col : uk_col + m] -= Bnp

    return A_eq, b_eq


def print_matrix(mat, name):
    print(f"{name}:")
    for row in mat:
        for val in row:
            txt = f" {val:8.4f}" if val != 0 else "   .    "
            print(txt, end="")
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
        start_col = max(0, i - max_bandwidth + 1)
        row_values = [L[i, j] for j in range(start_col, i + 1)]

        while len(row_values) < max_bandwidth:
            row_values.insert(0, 0.0)

        row_values[-1] = 1.0 / L[i, i]
        L_row[i, :] = row_values

    return L_row


def convert_chol_transposed_to_banded_storage(L):
    n = L.shape[0]
    max_bandwidth = get_max_bandwidth(L)
    L_row = np.zeros((n, max_bandwidth))

    for i in range(n):
        end_col = min(n, i + max_bandwidth)
        row_values = [L[i, j] for j in range(i, end_col)]

        while len(row_values) < max_bandwidth:
            row_values.append(0.0)

        row_values[0] = 1.0 / L[i, i]
        L_row[i, :] = row_values

    return L_row


def generate_constants_header(constants_dict):
    lines = []
    lines.append("// Constants definitions\n")
    for name, value in constants_dict.items():
        lines.append(f"#define {name} {value}\n")
    lines.append("// end constants definitions\n")
    return "".join(lines)


def generate_matrix_header(M, name, ctype="fp_t"):
    size_0, size_1 = M.shape
    lines = []
    lines.append(f"// Matrix {name} of size {size_0} x {size_1}\n")
    lines.append(f"#define {name.upper()}_ROWS {size_0}\n")
    lines.append(f"#define {name.upper()}_COLS {size_1}\n")
    lines.append(f"const {ctype} {name}[{name.upper()}_ROWS][{name.upper()}_COLS] = {{\n")
    for i in range(size_0):
        lines.append("   { " + ", ".join(f"({ctype}){M[i, j]:.8f}" for j in range(size_1)) + " },\n")
    lines.append(f"}};\n// end Matrix {name}\n")
    return "".join(lines)


def generate_vector_header(v, name, ctype="fp_t"):
    size = v.shape[0]
    lines = []
    lines.append(f"// Vector {name} of size {size}\n")
    lines.append(f"#define {name.upper()}_SIZE {size}\n")
    lines.append(f"const {ctype} {name}[{name.upper()}_SIZE] = {{\n")
    for i in range(size):
        lines.append(f"   ({ctype}){v[i]:.8f},\n")
    lines.append(f"}};\n// end Vector {name}\n")
    return "".join(lines)


def generate_full_header(data, filename="data.h", guard="DATA_H"):
    ensure_parent_dir(filename)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"#ifndef {guard}\n")
        f.write(f"#define {guard}\n\n")
        f.write('#include "data_types.h"\n\n')

        for d in data:
            f.write(d)
            f.write("\n// ===================== \n\n")

        f.write(f"#endif // {guard}\n")


def fp_to_q10_22_word(value):
    scaled = int(np.round(float(value) * (1 << 22)))
    if scaled > 0x7FFFFFFF:
        scaled = 0x7FFFFFFF
    if scaled < -0x80000000:
        scaled = -0x80000000
    return np.uint32(scaled & 0xFFFFFFFF)


def flatten_fp_matrix_words(matrix):
    flat = matrix.reshape(-1)
    return [fp_to_q10_22_word(v) for v in flat]


def flatten_index_words(index_matrix, index_storage_bits):
    flat = index_matrix.astype(np.uint32).reshape(-1)

    if index_storage_bits == 32:
        return [np.uint32(v) for v in flat]

    # 16-bit packed: two indexes per 32-bit word
    words = []
    for i in range(0, len(flat), 2):
        lo = int(flat[i]) & 0xFFFF
        hi = int(flat[i + 1]) & 0xFFFF if (i + 1) < len(flat) else 0
        words.append(np.uint32(lo | (hi << 16)))
    return words


def write_solver_constants_header(constants, filename):
    ensure_parent_dir(filename)
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#ifndef SOLVER_CONSTANTS_H\n")
        f.write("#define SOLVER_CONSTANTS_H\n\n")
        f.write("// Auto-generated by scripts/header_generator.py\n")
        for name, value in constants.items():
            f.write(f"#define {name} {value}\n")
        f.write("\n#endif // SOLVER_CONSTANTS_H\n")


def write_matrix_layout_header(layout, filename):
    ensure_parent_dir(filename)
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#ifndef MATRIX_LAYOUT_H\n")
        f.write("#define MATRIX_LAYOUT_H\n\n")
        f.write("// Auto-generated by scripts/header_generator.py\n")
        f.write(f"#define MATRIX_BLOB_INDEX_BITS {layout['index_bits']}\n")
        f.write("#define MATRIX_BLOB_WORD_BYTES 4\n")
        f.write(f"#define MATRIX_BLOB_TOTAL_WORDS {layout['total_words']}\n")
        f.write(f"#define MATRIX_BLOB_TOTAL_BYTES {layout['total_bytes']}\n\n")

        for name in [
            "L_BANDED",
            "LT_BANDED",
            "A_SPARSE_DATA",
            "A_SPARSE_INDEXES",
            "AT_SPARSE_DATA",
            "AT_SPARSE_INDEXES",
        ]:
            sec = layout[name]
            f.write(f"#define MATRIX_{name}_ROWS {sec['rows']}\n")
            f.write(f"#define MATRIX_{name}_COLS {sec['cols']}\n")
            f.write(f"#define MATRIX_{name}_ELEMS {sec['elems']}\n")
            f.write(f"#define MATRIX_{name}_WORD_OFFSET {sec['word_offset']}\n")
            f.write(f"#define MATRIX_{name}_WORD_COUNT {sec['word_count']}\n")
            f.write(f"#define MATRIX_{name}_BYTE_OFFSET {sec['byte_offset']}\n")
            f.write(f"#define MATRIX_{name}_BYTE_COUNT {sec['byte_count']}\n\n")

        f.write("#endif // MATRIX_LAYOUT_H\n")


def write_matrix_blob_sim_header(words, filename):
    ensure_parent_dir(filename)
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#ifndef MATRIX_BLOB_SIM_H\n")
        f.write("#define MATRIX_BLOB_SIM_H\n\n")
        f.write("#include <ap_int.h>\n")
        f.write('#include "matrix_layout.h"\n\n')
        f.write("// Auto-generated by scripts/header_generator.py\n")
        f.write("const ap_uint<32> matrix_blob_words[MATRIX_BLOB_TOTAL_WORDS] = {\n")
        for i, word in enumerate(words):
            f.write(f"    (ap_uint<32>)0x{int(word):08X}")
            if i != len(words) - 1:
                f.write(",")
            f.write("\n")
        f.write("};\n\n")
        f.write("#endif // MATRIX_BLOB_SIM_H\n")


def write_matrix_blob_binary(words, filename):
    ensure_parent_dir(filename)
    with open(filename, "wb") as f:
        for word in words:
            f.write(struct.pack("<I", int(word)))


def compute_blob_checksum(words):
    checksum = 0
    for i, word in enumerate(words):
        checksum ^= (int(word) + i) & 0xFFFFFFFF
    return checksum & 0xFFFFFFFF


def write_matrix_meta_verilog_header(layout, checksum, horizon, filename):
    ensure_parent_dir(filename)
    with open(filename, "w") as f:
        f.write("// Auto-generated by scripts/header_generator.py\n")
        f.write("`ifndef MATRIX_BLOB_META_VH\n")
        f.write("`define MATRIX_BLOB_META_VH\n")
        f.write(f"`define MATRIX_BLOB_TOTAL_WORDS_V 32'd{layout['total_words']}\n")
        f.write(f"`define MATRIX_BLOB_TOTAL_BYTES_V 32'd{layout['total_bytes']}\n")
        f.write(f"`define MATRIX_BLOB_CHECKSUM_V 32'h{checksum:08X}\n")
        f.write(f"`define MATRIX_BLOB_INDEX_BITS_V {layout['index_bits']}\n")
        f.write(f"`define MATRIX_HORIZON_LENGTH_V {horizon}\n")
        f.write("`endif\n")


def build_blob_and_layout(L_banded, LT_banded, A_sparse_data, A_sparse_indexes, AT_sparse_data, AT_sparse_indexes, index_bits):
    words = []
    layout = {"index_bits": index_bits}

    def add_section(name, rows, cols, sec_words):
        word_offset = len(words)
        word_count = len(sec_words)
        words.extend(sec_words)
        layout[name] = {
            "rows": int(rows),
            "cols": int(cols),
            "elems": int(rows * cols),
            "word_offset": int(word_offset),
            "word_count": int(word_count),
            "byte_offset": int(word_offset * 4),
            "byte_count": int(word_count * 4),
        }

    add_section(
        "L_BANDED",
        L_banded.shape[0],
        L_banded.shape[1],
        flatten_fp_matrix_words(L_banded),
    )
    add_section(
        "LT_BANDED",
        LT_banded.shape[0],
        LT_banded.shape[1],
        flatten_fp_matrix_words(LT_banded),
    )
    add_section(
        "A_SPARSE_DATA",
        A_sparse_data.shape[0],
        A_sparse_data.shape[1],
        flatten_fp_matrix_words(A_sparse_data),
    )
    add_section(
        "A_SPARSE_INDEXES",
        A_sparse_indexes.shape[0],
        A_sparse_indexes.shape[1],
        flatten_index_words(A_sparse_indexes, index_bits),
    )
    add_section(
        "AT_SPARSE_DATA",
        AT_sparse_data.shape[0],
        AT_sparse_data.shape[1],
        flatten_fp_matrix_words(AT_sparse_data),
    )
    add_section(
        "AT_SPARSE_INDEXES",
        AT_sparse_indexes.shape[0],
        AT_sparse_indexes.shape[1],
        flatten_index_words(AT_sparse_indexes, index_bits),
    )

    layout["total_words"] = len(words)
    layout["total_bytes"] = len(words) * 4
    return words, layout


def ADMM_iteration_dense(KKT, A_mat, lvec, uvec, rho_val, iterations):
    x = np.zeros(KKT.shape[0])
    z = np.zeros(KKT.shape[0])
    y = np.zeros(KKT.shape[0])

    for _ in range(iterations):
        x = np.linalg.solve(KKT, A_mat.T @ ((rho_val * z) - y))
        z = np.clip(A_mat @ x + (y / rho_val), lvec, uvec)
        y = y + rho_val * (A_mat @ x - z)

    return x, z, y


def main():
    global N
    args = parse_args()
    N = args.horizon

    # Number of states and inputs
    n = A.shape[0]
    m = B.shape[1]

    # Total number of variables
    num_x = n * (N + 1)
    num_u = m * N
    num_var = num_x + num_u

    # Build Hessian matrix P
    blocks = []
    for _k in range(N):
        blocks.append(Q)
        blocks.append(R)
    blocks.append(Q)

    total = sum(block.shape[0] for block in blocks)
    P = np.zeros((total, total))

    start = 0
    for block in blocks:
        size = block.shape[0]
        P[start : start + size, start : start + size] = block
        start += size

    A_eq, b_eq = build_Aeq_interleaved(A, B, N)

    n_ineq = m * N
    A_ineq = np.zeros((n_ineq, num_var))

    row = 0
    for k in range(N):
        u_start = k * (n + m) + n
        u_end = u_start + m
        A_ineq[row : row + m, u_start:u_end] = np.eye(m)
        row += m

    A_full = np.vstack([A_eq, A_ineq])

    l = np.hstack([b_eq, np.tile(u_min, N)])
    u = np.hstack([b_eq, np.tile(u_max, N)])

    rho_vect = rho * np.ones(P.shape[0])
    rho_vect[np.where(l == u)[0]] *= rho_mult
    rho_diag = np.diag(rho_vect)

    KKT = P + A_full.T @ rho_diag @ A_full
    L = np.linalg.cholesky(KKT)

    L_banded = convert_chol_to_banded_storage(L)
    LT_banded = convert_chol_transposed_to_banded_storage(L.T)
    A_sparse_data, A_sparse_indexes, A_n_bits_idx = convert_matrix_to_sparse_storage(A_full)
    AT_sparse_data, AT_sparse_indexes, AT_n_bits_idx = convert_matrix_to_sparse_storage(A_full.T)

    constants = {
        "HORIZON_LENGTH": N,
        "STATE_SIZE": n,
        "N_VAR": num_var,
        "START_INEQ": A_eq.shape[0],
        "RHO_SHIFT": int(np.log2(rho)),
        "U_MIN": u_min[0],
        "U_MAX": u_max[0],
        "ADMM_ITERS": ADMM_ITERS,
        "U_HOVER": ug[0],
    }

    # Legacy matrix header (existing flow compatibility)
    data = []
    data.append(generate_constants_header(constants))
    data.append(generate_matrix_header(L_banded, "L_banded"))
    data.append(generate_matrix_header(LT_banded, "LT_banded"))
    data.append(generate_matrix_header(A_sparse_data, "A_sparse_data"))
    data.append(
        generate_matrix_header(
            A_sparse_indexes,
            "A_sparse_indexes",
            ctype=f"ap_uint<{A_n_bits_idx}>",
        )
    )
    data.append(generate_matrix_header(AT_sparse_data, "AT_sparse_data"))
    data.append(
        generate_matrix_header(
            AT_sparse_indexes,
            "AT_sparse_indexes",
            ctype=f"ap_uint<{AT_n_bits_idx}>",
        )
    )
    generate_full_header(data, filename=args.data_header)

    # New DDR artifacts
    blob_words, layout = build_blob_and_layout(
        L_banded,
        LT_banded,
        A_sparse_data,
        A_sparse_indexes,
        AT_sparse_data,
        AT_sparse_indexes,
        args.index_storage_bits,
    )

    write_solver_constants_header(constants, args.constants_header)
    write_matrix_layout_header(layout, args.layout_header)
    write_matrix_blob_sim_header(blob_words, args.blob_sim_header)
    write_matrix_blob_binary(blob_words, args.blob_bin)
    blob_checksum = compute_blob_checksum(blob_words)
    write_matrix_meta_verilog_header(layout, blob_checksum, N, args.meta_vh)

    # Test header generation
    np.random.seed(0)
    rand_vec = np.random.randn(L_banded.shape[0])
    test_data = []
    test_data.append(generate_vector_header(rand_vec, "random_vector", ctype="double"))

    forw_subst_out = np.linalg.solve(L, rand_vec)
    test_data.append(generate_vector_header(forw_subst_out, "forw_subst_out", ctype="double"))

    back_subst_out = np.linalg.solve(L.T, rand_vec)
    test_data.append(generate_vector_header(back_subst_out, "back_subst_out", ctype="double"))

    A_mul_out = A_full @ rand_vec
    test_data.append(generate_vector_header(A_mul_out, "A_mul_out", ctype="double"))

    AT_mul_out = A_full.T @ rand_vec
    test_data.append(generate_vector_header(AT_mul_out, "AT_mul_out", ctype="double"))

    l_test = l.copy()
    u_test = u.copy()
    l_test[0:3] = (0.1, 0.1, -0.1)
    u_test[0:3] = (0.1, 0.1, -0.1)

    x1, z1, y1 = ADMM_iteration_dense(KKT, A_full, l_test, u_test, rho, iterations=1)
    test_data.append(generate_vector_header(x1, "ADMM_x_after_1_iter", ctype="double"))
    test_data.append(generate_vector_header(z1, "ADMM_z_after_1_iter", ctype="double"))
    test_data.append(generate_vector_header(y1, "ADMM_y_after_1_iter", ctype="double"))

    x10, z10, y10 = ADMM_iteration_dense(KKT, A_full, l_test, u_test, rho, iterations=10)
    test_data.append(generate_vector_header(x10, "ADMM_x_after_10_iter", ctype="double"))
    test_data.append(generate_vector_header(z10, "ADMM_z_after_10_iter", ctype="double"))
    test_data.append(generate_vector_header(y10, "ADMM_y_after_10_iter", ctype="double"))

    x100, z100, y100 = ADMM_iteration_dense(KKT, A_full, l_test, u_test, rho, iterations=100)
    test_data.append(generate_vector_header(x100, "ADMM_x_after_100_iter", ctype="double"))
    test_data.append(generate_vector_header(z100, "ADMM_z_after_100_iter", ctype="double"))
    test_data.append(generate_vector_header(y100, "ADMM_y_after_100_iter", ctype="double"))

    x50, z50, y50 = ADMM_iteration_dense(KKT, A_full, l_test, u_test, rho, iterations=50)
    test_data.append(generate_vector_header(x50, "ADMM_x_after_50_iter", ctype="double"))
    test_data.append(generate_vector_header(z50, "ADMM_z_after_50_iter", ctype="double"))
    test_data.append(generate_vector_header(y50, "ADMM_y_after_50_iter", ctype="double"))

    generate_full_header(test_data, filename=args.test_header, guard="TEST_DATA_H")

    print("Generated artifacts:")
    print(f"  data header      : {os.path.abspath(args.data_header)}")
    print(f"  test header      : {os.path.abspath(args.test_header)}")
    print(f"  constants header : {os.path.abspath(args.constants_header)}")
    print(f"  layout header    : {os.path.abspath(args.layout_header)}")
    print(f"  blob sim header  : {os.path.abspath(args.blob_sim_header)}")
    print(f"  blob binary      : {os.path.abspath(args.blob_bin)}")
    print(f"  blob bytes       : {layout['total_bytes']}")
    print(f"  blob words       : {layout['total_words']}")
    print(f"  blob checksum    : 0x{blob_checksum:08X}")
    print(f"  index bits       : {args.index_storage_bits}")
    print(f"  horizon          : {N}")
    print(f"  meta verilog     : {os.path.abspath(args.meta_vh)}")


if __name__ == "__main__":
    main()
