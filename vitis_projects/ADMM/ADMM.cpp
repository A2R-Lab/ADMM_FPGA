#include "data.h"
#include "ADMM.h"
#include "data_types.h"
#include <ap_fixed.h>
#include <cmath>
#include <type_traits>

template <typename T>
static inline typename std::enable_if<std::is_floating_point<T>::value, T>::type
rho_mul_impl(T v) {
    return std::ldexp(v, RHO_SHIFT);
}

template <typename T>
static inline typename std::enable_if<!std::is_floating_point<T>::value, T>::type
rho_mul_impl(T v) {
    return v << RHO_SHIFT;
}

template <typename T>
static inline typename std::enable_if<std::is_floating_point<T>::value, T>::type
rho_div_impl(T v) {
    return std::ldexp(v, -RHO_SHIFT);
}

template <typename T>
static inline typename std::enable_if<!std::is_floating_point<T>::value, T>::type
rho_div_impl(T v) {
    return v >> RHO_SHIFT;
}

static inline fp_t rho_mul(fp_t v) {
    return rho_mul_impl<fp_t>(v);
}

static inline fp_t rho_div(fp_t v) {
    return rho_div_impl<fp_t>(v);
}

void forward_substitution(
    const fp_t b[L_BANDED_ROWS],
    fp_t x[L_BANDED_ROWS]
) {
    fp_t window[L_BANDED_COLS-1] = {0};

    FORW_SUBST_EXTERN_LOOP:
    for (int i = 0; i < N_VAR; i++) {
        fp_t sum_val = 0;

        FORW_SUBST_DOT_PRODUCT_LOOP:
        // dot product with window
        for (int j = 0; j < L_BANDED_COLS - 1; j++) {
            sum_val += L_banded[i][j] * window[j];
        }

        fp_t new_x = (b[i] - sum_val) * L_banded[i][L_BANDED_COLS-1];
        x[i] = new_x;

        FORW_SUBST_SHIFT_REGISTER_LOOP:
        // shift register window
        for (int k = 0; k < L_BANDED_COLS - 2; k++) {
            window[k] = window[k+1];
        }
        window[L_BANDED_COLS - 2] = new_x;
    }
}
void backward_substitution(
    const fp_t b[LT_BANDED_ROWS],
    fp_t x[LT_BANDED_ROWS]
) {
    fp_t window[LT_BANDED_COLS-1];

    // Initialize window
    INIT_WINDOW:
    for (int j = 0; j < LT_BANDED_COLS-1; j++) {
        window[j] = 0;
    }

    BACK_SUBST_EXTERN_LOOP:
    for (int i = LT_BANDED_ROWS - 1; i >= 0; i--) {
        // Compute dot product with current window state
        fp_t sum_val = 0;

        DOT_PRODUCT:
        for (int j = LT_BANDED_COLS-2; j >= 0; j--) {
            sum_val += LT_banded[i][j+1] * window[j];
        }

        // Compute new x value
        fp_t new_x = (b[i] - sum_val) * LT_banded[i][0];
        x[i] = new_x;

        // Shift window - this happens in parallel with next iteration setup
        SHIFT_WINDOW:
        for (int k = LT_BANDED_COLS - 2; k > 0; k--) {
            window[k] = window[k-1];
        }
        window[0] = new_x;
    }
}

void AT_mul(
    const fp_t x[AT_SPARSE_DATA_ROWS],
    fp_t ATx[AT_SPARSE_DATA_ROWS]
) {
    AT_MUL_EXTERN_LOOP:
    for (int i = 0; i < AT_SPARSE_DATA_ROWS; i++) {
        fp_t sum_val = 0;
        AT_MUL_DOT_PRODUCT_LOOP:
        for (int j = 0; j < AT_SPARSE_DATA_COLS; j++) {
            sum_val += AT_sparse_data[i][j] * x[AT_sparse_indexes[i][j]];
        }
        ATx[i] = sum_val;
    }
}

inline void ADMM_iteration(
    fp_t x[N_VAR],
    fp_t current_state[12]
) {
    #pragma HLS INLINE
    static fp_t b[N_VAR] = {0};
    static fp_t y[N_VAR] = {0};
    fp_t tmp[N_VAR];
    fp_t b_tmp[N_VAR];

    // x_update
    // first cycle b will be 0 anyway, and then it gets updated at the end of the iteration
    forward_substitution(b, tmp);
    backward_substitution(tmp, x);

    // z - y update
    ADMM_IT_ZY_UPDATE_LOOP:
    for (int i = 0; i < N_VAR; i++) {
        fp_t Axi = 0;
        for (int j = 0; j < A_SPARSE_DATA_COLS; j++) {
            Axi += A_sparse_data[i][j] * x[A_sparse_indexes[i][j]];
        }

        fp_t zi;
        if(i < STATE_SIZE) {
            zi = current_state[i];
        } else if (i >= START_INEQ) { // This will depend on horizon length
            zi = Axi + rho_div(y[i]);
            // Cast to fp_t to avoid floating-point comparison hardware
            if (zi < (fp_t)U_MIN) {
                zi = (fp_t)U_MIN;
            } else if (zi > (fp_t)U_MAX) {
                zi = (fp_t)U_MAX;
            }
        } else {
            zi = 0;
        }

        fp_t yi = y[i] + rho_mul(Axi - zi);
        y[i] = yi;
        b_tmp[i] = rho_mul(zi) - yi;

    }
    AT_mul(b_tmp, b);
}

void ADMM_solver(
    current_state_t current_in,
    command_out_t &command_out
) {

    static fp_t x[N_VAR] = {0};
    fp_t current_state_vec[12];

    for (int i = 0; i < 12; i++) {
        current_state_vec[i] = current_in.state[i];
    }

ADMM_MAIN_LOOP:
    for (int iter = 0; iter < ADMM_ITERS; iter++) {
        ADMM_iteration(x, current_state_vec);
    }

    // Add hover thrust offset before returning commands
    command_out.u0 = x[12] + (fp_t)U_HOVER;
    command_out.u1 = x[13] + (fp_t)U_HOVER;
    command_out.u2 = x[14] + (fp_t)U_HOVER;
    command_out.u3 = x[15] + (fp_t)U_HOVER;
}
