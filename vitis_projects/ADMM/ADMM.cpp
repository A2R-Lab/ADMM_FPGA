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

constexpr int ACC_GUARD_BITS = 12;

template <typename T, bool IsFloat = std::is_floating_point<T>::value>
struct AccType {
    typedef T type;
};

template <typename T>
struct AccType<T, false> {
    typedef ap_fixed<T::width + ACC_GUARD_BITS, T::iwidth + ACC_GUARD_BITS, AP_RND, AP_SAT> type;
};

typedef typename AccType<fp_t>::type acc_t;

template <typename T, bool IsFloat = std::is_floating_point<T>::value>
struct RhoOps;

template <typename T>
struct RhoOps<T, true> {
    static inline T mul(T v) {
        return std::ldexp(v, RHO_SHIFT);
    }

    static inline T div(T v) {
        return std::ldexp(v, -RHO_SHIFT);
    }
};

template <typename T>
struct RhoOps<T, false> {
    typedef ap_fixed<T::width + RHO_SHIFT, T::iwidth + RHO_SHIFT, AP_TRN, AP_WRAP> wide_t;

    static inline T mul(T v) {
        wide_t t = v;
        t <<= RHO_SHIFT;
        // Narrowing cast applies T's configured quantization/overflow mode.
        return (T)t;
    }

    static inline T div(T v) {
        wide_t t = v;
        t >>= RHO_SHIFT;
        return (T)t;
    }
};

static inline fp_t rho_mul(fp_t v) { return RhoOps<fp_t>::mul(v); }

static inline fp_t rho_div(fp_t v) { return RhoOps<fp_t>::div(v); }

fp_t admm_test_rho_mul(fp_t v) { return rho_mul(v); }

fp_t admm_test_rho_div(fp_t v) { return rho_div(v); }

int admm_test_fp_width() { return fp_t::width; }

int admm_test_acc_width() { return acc_t::width; }

void forward_substitution(
    const fp_t b[L_BANDED_ROWS],
    const fp_t q[L_BANDED_ROWS],
    fp_t x[L_BANDED_ROWS]
) {
    fp_t window[L_BANDED_COLS-1] = {0};

    FORW_SUBST_EXTERN_LOOP:
    for (int i = 0; i < N_VAR; i++) {
        acc_t sum_val = 0;

        FORW_SUBST_DOT_PRODUCT_LOOP:
        // dot product with window
        for (int j = 0; j < L_BANDED_COLS - 1; j++) {
            sum_val += (acc_t)L_banded[i][j] * (acc_t)window[j];
        }

        acc_t new_x = ((acc_t)b[i] - (acc_t)q[i] - sum_val) * (acc_t)L_banded[i][L_BANDED_COLS-1];
        x[i] = (fp_t)new_x;

        FORW_SUBST_SHIFT_REGISTER_LOOP:
        // shift register window
        for (int k = 0; k < L_BANDED_COLS - 2; k++) {
            window[k] = window[k+1];
        }
        window[L_BANDED_COLS - 2] = (fp_t)new_x;
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
        acc_t sum_val = 0;

        DOT_PRODUCT:
        for (int j = LT_BANDED_COLS-2; j >= 0; j--) {
            sum_val += (acc_t)LT_banded[i][j+1] * (acc_t)window[j];
        }

        // Compute new x value
        acc_t new_x = ((acc_t)b[i] - sum_val) * (acc_t)LT_banded[i][0];
        x[i] = (fp_t)new_x;

        // Shift window - this happens in parallel with next iteration setup
        SHIFT_WINDOW:
        for (int k = LT_BANDED_COLS - 2; k > 0; k--) {
            window[k] = window[k-1];
        }
        window[0] = (fp_t)new_x;
    }
}

void AT_mul(
    const fp_t x[AT_SPARSE_DATA_ROWS],
    fp_t ATx[AT_SPARSE_DATA_ROWS]
) {
    AT_MUL_EXTERN_LOOP:
    for (int i = 0; i < AT_SPARSE_DATA_ROWS; i++) {
        acc_t sum_val = 0;
        AT_MUL_DOT_PRODUCT_LOOP:
        for (int j = 0; j < AT_SPARSE_DATA_COLS; j++) {
            sum_val += (acc_t)AT_sparse_data[i][j] * (acc_t)x[AT_sparse_indexes[i][j]];
        }
        ATx[i] = (fp_t)sum_val;
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
        acc_t Axi = 0;
        for (int j = 0; j < A_SPARSE_DATA_COLS; j++) {
            Axi += (acc_t)A_sparse_data[i][j] * (acc_t)x[A_sparse_indexes[i][j]];
        }
        fp_t Axi_fp = (fp_t)Axi;

        fp_t zi;
        if(i < STATE_SIZE) {
            zi = current_state[i];
        } else if (i >= START_INEQ) { // This will depend on horizon length
            zi = Axi_fp + rho_div(y[i]);
            // Cast to fp_t to avoid floating-point comparison hardware
            if (zi < (fp_t)U_MIN) {
                zi = (fp_t)U_MIN;
            } else if (zi > (fp_t)U_MAX) {
                zi = (fp_t)U_MAX;
            }
        } else {
            zi = 0;
        }

        fp_t yi = y[i] + rho_mul(Axi_fp - zi);
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
    if (traj_started && (traj_idx < TRAJ_LENGTH)) {
        // q is preweighted and packed offline; runtime only shifts pointer.
        q_runtime = &traj_q_packed[traj_idx][0];
    }

    ADMM_MAIN_LOOP:
    for (int iter = 0; iter < 20; iter++) {
        ADMM_iteration(x, current_state, q_runtime);
    }

    if (traj_started && (traj_idx < TRAJ_LENGTH)) {
        traj_tick_div_ctr++;
        if (traj_tick_div_ctr >= TRAJ_TICK_DIV) {
            traj_tick_div_ctr = 0;
            traj_idx++;
        }
    }
}
