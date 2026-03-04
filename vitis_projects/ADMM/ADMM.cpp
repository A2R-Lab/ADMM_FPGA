#include "data.h"
#include "traj_data.h"
#include "ADMM.h"
#include "data_types.h"
#include <ap_fixed.h>
#include <cmath>
#include <type_traits>

#ifndef TRAJ_TICK_DIV
#define TRAJ_TICK_DIV 1
#endif

static_assert(TRAJ_TICK_DIV > 0, "TRAJ_TICK_DIV must be > 0");

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
    const fp_t q[L_BANDED_ROWS],
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

        fp_t new_x = (b[i] - q[i] - sum_val) * L_banded[i][L_BANDED_COLS-1];
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

void ADMM_iteration(
    fp_t x[N_VAR], 
    fp_t current_state[12],
    const fp_t q_vec[N_VAR]
) {
    static fp_t b[N_VAR] = {0};
    static fp_t y[N_VAR] = {0};
    fp_t tmp[N_VAR];
    fp_t b_tmp[N_VAR];

    // x_update
    forward_substitution(b, q_vec, tmp);
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
    fp_t current_state[12],
    fp_t x[N_VAR],
    int start_traj
) {
    static bool traj_started = false;
    static int traj_idx = 0;
    static int traj_tick_div_ctr = 0;
    static const fp_t q_zero[N_VAR] = {0};

    if (start_traj != 0) {
        traj_started = true;
    }

    const fp_t* q_runtime = q_zero;
    if (traj_started) {
        int clamped_idx = traj_idx;
        if (clamped_idx > (TRAJ_LENGTH - 1)) {
            clamped_idx = TRAJ_LENGTH - 1;
        }
        // q is preweighted and packed offline; runtime only shifts pointer.
        q_runtime = &traj_q_packed[clamped_idx][0];
    }

    ADMM_MAIN_LOOP:
    for (int iter = 0; iter < 28; iter++) {
        ADMM_iteration(x, current_state, q_runtime);
    }

    if (traj_started && (traj_idx < (TRAJ_LENGTH - 1))) {
        traj_tick_div_ctr++;
        if (traj_tick_div_ctr >= TRAJ_TICK_DIV) {
            traj_tick_div_ctr = 0;
            traj_idx++;
        }
    }
}
