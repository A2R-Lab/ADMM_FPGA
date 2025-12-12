import numpy as np

# 1. Generate a random banded lower-triangular matrix (Cholesky factor)
def generate_banded_cholesky(n, max_bandwidth):
    L = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        # Start column for the band (keep within lower triangle)
        start_col = max(0, i - max_bandwidth + 1)
        for j in range(start_col, i + 1):
            # Diagonal elements positive
            if i == j:
                L[i, j] = np.random.uniform(1.0, 2.0)
            else:
                L[i, j] = np.random.uniform(-0.5, 0.5)
    return L

# 2. Convert to row-wise banded storage for FPGA
def convert_to_banded_storage(L, max_bandwidth):
    n = L.shape[0]
    L_row = np.zeros((n, max_bandwidth), dtype=np.float32)
    
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

def generate_l_row_header_apfixed(L_row, filename="l_row.h", array_name="L_row", b=None, x_sol=None):
    n, max_bandwidth = L_row.shape
    with open(filename, "w") as f:
        # Include guard and ap_fixed header
        f.write("#ifndef L_ROW_H\n")
        f.write("#define L_ROW_H\n\n")
        f.write("#include <ap_fixed.h>\n\n")
        f.write(f"#define N {n}\n")
        f.write(f"#define MAX_BANDWIDTH {max_bandwidth}\n\n")
        f.write("typedef ap_fixed<32,16> fp_t;\n\n")
        f.write(f"const fp_t {array_name}[N][MAX_BANDWIDTH] = {{\n")
        
        for i in range(n):
            row_str = ", ".join(f"(fp_t){v:.8f}" for v in L_row[i])
            if i != n - 1:
                f.write(f"    {{ {row_str} }},\n")
            else:
                f.write(f"    {{ {row_str} }}\n")
        
        f.write("};\n\n")

        # Write b as comments if provided
        if b is not None:
            f.write("// RHS vector b (for reference)\n")
            f.write("// fp_t b[N] = {\n")
            for val in b:
                f.write(f"//   (fp_t){val:.8f},\n")
            f.write("// };\n\n")

        # Write solution x as comments if provided
        if x_sol is not None:
            f.write("// Solution vector x (for reference)\n")
            f.write("const fp_t x[N] = {\n")
            for val in x_sol:
                f.write(f"   (fp_t){val:.8f},\n")
            f.write(" };\n\n")

        f.write("void forward_substitution(const fp_t b[N], fp_t x[N]);\n")
        f.write("#endif // L_ROW_H\n")

def forward_substitution(L_row, b):
    n, max_bandwidth = L_row.shape
    x = np.zeros(n, dtype=np.float32)
    
    for i in range(n):
        sum_val = 0.0
        
        for j in range(max_bandwidth - 1):
            val = L_row[i, j]
            col_idx = i - (max_bandwidth - 1 - j)
            if col_idx >= 0:
                sum_val += val * x[col_idx]
        
        # Diagonal is always the last element
        x[i] = (b[i] - sum_val) * L_row[i, -1]
    
    return x

def backward_substitution(L_row, b):
    n, max_bandwidth = L_row.shape
    x = np.zeros(n, dtype=np.float32)

    for i in range(n - 1, -1, -1):
        sum_val = 0.0

        # Traverse superdiagonals of Lᵀ, which correspond to subdiagonals of L
        for k in range(1, max_bandwidth):
            j = i + k
            if j < n:
                # In compact storage, L(j, i+k)'s transpose Lᵀ(i, j)
                # corresponds to L(j, i), located at this column:
                col = (max_bandwidth - 1) - k
                sum_val += L_row[j, col] * x[j]

        # diagonal of Lᵀ is same as diagonal of L
        x[i] = (b[i] - sum_val) * L_row[i, -1]

    return x

def print_matrix(mat, name):
    print(f"{name}:")
    for row in mat:
        print(" ".join(f"{val:8.4f}" for val in row))
    print()

# Parameters
n = 10
max_bandwidth = 3

np.random.seed(0)

# Generate random banded Cholesky factor
L = generate_banded_cholesky(n, max_bandwidth)

# Convert to FPGA-friendly storage
L_row = convert_to_banded_storage(L, max_bandwidth)

# Generate random right-hand side
b = np.random.uniform(-1.0, 1.0, size=n).astype(np.float32)
b[0] = 2*b[0]
print(f"Right-hand side b: {b}\n")

# Solve L x = b using forward substitution
x = forward_substitution(L_row, b)
print(f"Solution x: {x}\n")

x_ref = np.linalg.solve(L, b)  # For verification if needed

print(f"Reference solution x_ref: {x_ref}\n")

generate_l_row_header_apfixed(L_row, b=b, x_sol=x_ref)



# print("-------------Lower-triangular matrix L (standard storage)-------------")
# print_matrix_stats(L)
# print("\n\n\n")
# print("-------------Lower-triangular matrix L_row (banded storage)-------------")
# print_matrix_stats(L_row)