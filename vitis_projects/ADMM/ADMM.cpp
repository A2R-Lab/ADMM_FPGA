#include "data.h"
#include "traj_data.h"
#include "ADMM.h"
#include "data_types.h"
#include "admm_runtime_config.h"
#include <ap_fixed.h>
#include <cmath>
#include <type_traits>

#ifndef TRAJ_TICK_DIV
#define TRAJ_TICK_DIV 1
#endif

static_assert(TRAJ_TICK_DIV > 0, "TRAJ_TICK_DIV must be > 0");

constexpr int ACC_GUARD_BITS = 12;

#ifndef RHO_SHIFT_EQ
#error "RHO_SHIFT_EQ must be generated in data.h by scripts/header_generator.py"
#endif

#ifndef RHO_SHIFT_INEQ
#error "RHO_SHIFT_INEQ must be generated in data.h by scripts/header_generator.py"
#endif

constexpr int RHO_SHIFT_EQ_V = RHO_SHIFT_EQ;
constexpr int RHO_SHIFT_INEQ_V = RHO_SHIFT_INEQ;
constexpr int RHO_SHIFT_MAX_V =
    (RHO_SHIFT_EQ_V > RHO_SHIFT_INEQ_V) ? RHO_SHIFT_EQ_V : RHO_SHIFT_INEQ_V;

static_assert(RHO_SHIFT_EQ_V >= 0, "RHO_SHIFT_EQ must be >= 0");
static_assert(RHO_SHIFT_INEQ_V >= 0, "RHO_SHIFT_INEQ must be >= 0");

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
    template <int Shift>
    static inline T mul_shift(T v) {
        return std::ldexp(v, Shift);
    }

    template <int Shift>
    static inline T div_shift(T v) {
        return std::ldexp(v, -Shift);
    }
};

template <typename T>
struct RhoOps<T, false> {
    typedef ap_fixed<T::width + RHO_SHIFT_MAX_V, T::iwidth + RHO_SHIFT_MAX_V, AP_TRN, AP_WRAP> wide_t;

    template <int Shift>
    static inline T mul_shift(T v) {
        wide_t t = v;
        t <<= Shift;
        return (T)t;
    }

    template <int Shift>
    static inline T div_shift(T v) {
        wide_t t = v;
        t >>= Shift;
        return (T)t;
    }
};

static inline bool is_inequality_constraint(int constraint_idx) {
    return constraint_idx >= START_INEQ;
}

static inline fp_t rho_mul(fp_t v, bool use_ineq_rho) {
    return use_ineq_rho
               ? RhoOps<fp_t>::template mul_shift<RHO_SHIFT_INEQ_V>(v)
               : RhoOps<fp_t>::template mul_shift<RHO_SHIFT_EQ_V>(v);
}

static inline fp_t rho_div(fp_t v, bool use_ineq_rho) {
    return use_ineq_rho
               ? RhoOps<fp_t>::template div_shift<RHO_SHIFT_INEQ_V>(v)
               : RhoOps<fp_t>::template div_shift<RHO_SHIFT_EQ_V>(v);
}

static inline bool traj_start_cmd(const current_state_t &current_in) {
    return current_in.traj_cmd[0] != 0;
}

static inline bool traj_reset_cmd(const current_state_t &current_in) {
    return current_in.traj_cmd[1] != 0;
}

void forward_substitution(
    const fp_t b[L_BANDED_ROWS],
    const fp_t q[L_BANDED_ROWS],
    fp_t x[L_BANDED_ROWS]
) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=L_banded dim=2 complete

    fp_t window[L_BANDED_COLS - 1] = {0};
#pragma HLS ARRAY_PARTITION variable=window dim=1 complete

    FORW_SUBST_EXTERN_LOOP:
    for (int i = 0; i < N_VAR; i++) {
#pragma HLS PIPELINE II=6
        acc_t sum_val = 0;

        FORW_SUBST_DOT_PRODUCT_LOOP:
        for (int j = 0; j < L_BANDED_COLS - 1; j++) {
#pragma HLS UNROLL factor=4
            sum_val += (acc_t)L_banded[i][j] * (acc_t)window[j];
        }

        acc_t new_x = ((acc_t)b[i] - (acc_t)q[i] - sum_val) * (acc_t)L_banded[i][L_BANDED_COLS - 1];
        x[i] = (fp_t)new_x;

        FORW_SUBST_SHIFT_REGISTER_LOOP:
        for (int k = 0; k < L_BANDED_COLS - 2; k++) {
#pragma HLS UNROLL factor=4
            window[k] = window[k + 1];
        }
        window[L_BANDED_COLS - 2] = (fp_t)new_x;
    }
}

void backward_substitution(
    const fp_t b[LT_BANDED_ROWS],
    fp_t x[LT_BANDED_ROWS]
) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=LT_banded dim=2 complete

    fp_t window[LT_BANDED_COLS - 1];
#pragma HLS ARRAY_PARTITION variable=window dim=1 complete

    INIT_WINDOW:
    for (int j = 0; j < LT_BANDED_COLS - 1; j++) {
#pragma HLS UNROLL
        window[j] = 0;
    }

    BACK_SUBST_EXTERN_LOOP:
    for (int i = LT_BANDED_ROWS - 1; i >= 0; i--) {
#pragma HLS PIPELINE II=6
        acc_t sum_val = 0;

        DOT_PRODUCT:
        for (int j = LT_BANDED_COLS - 2; j >= 0; j--) {
#pragma HLS UNROLL factor=4
            sum_val += (acc_t)LT_banded[i][j + 1] * (acc_t)window[j];
        }

        acc_t new_x = ((acc_t)b[i] - sum_val) * (acc_t)LT_banded[i][0];
        x[i] = (fp_t)new_x;

        SHIFT_WINDOW:
        for (int k = LT_BANDED_COLS - 2; k > 0; k--) {
#pragma HLS UNROLL factor=4
            window[k] = window[k - 1];
        }
        window[0] = (fp_t)new_x;
    }
}

void AT_mul(
    const fp_t x[N_CONSTR],
    fp_t ATx[N_VAR]
) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=AT_sparse_data dim=2 complete
#pragma HLS ARRAY_PARTITION variable=AT_sparse_indexes dim=2 complete

    AT_MUL_EXTERN_LOOP:
    for (int i = 0; i < AT_SPARSE_DATA_ROWS; i++) {
#pragma HLS PIPELINE II=1
        acc_t sum_val = 0;
        AT_MUL_DOT_PRODUCT_LOOP:
        for (int j = 0; j < AT_SPARSE_DATA_COLS; j++) {
#pragma HLS UNROLL
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
#pragma HLS INLINE
    static fp_t b[N_VAR] = {0};
    static fp_t y[N_CONSTR] = {0};
    fp_t tmp[N_VAR];
    fp_t b_tmp[N_CONSTR];

    forward_substitution(b, q_vec, tmp);
    backward_substitution(tmp, x);

    ADMM_IT_ZY_UPDATE_LOOP:
    for (int i = 0; i < N_CONSTR; i++) {
#pragma HLS PIPELINE II=1
        acc_t Axi = 0;
        for (int j = 0; j < A_SPARSE_DATA_COLS; j++) {
#pragma HLS UNROLL
            Axi += (acc_t)A_sparse_data[i][j] * (acc_t)x[A_sparse_indexes[i][j]];
        }
        fp_t Axi_fp = (fp_t)Axi;
        const bool use_ineq_rho = is_inequality_constraint(i);

        fp_t zi;
        if (i < STATE_SIZE) {
            zi = current_state[i];
        } else if (i >= START_XY_INEQ) {
            zi = Axi_fp + rho_div(y[i], use_ineq_rho);
            if (zi < (fp_t)XY_MIN) {
                zi = (fp_t)XY_MIN;
            } else if (zi > (fp_t)XY_MAX) {
                zi = (fp_t)XY_MAX;
            }
        } else if (i >= START_U_INEQ) {
            zi = Axi_fp + rho_div(y[i], use_ineq_rho);
            if (zi < (fp_t)U_MIN) {
                zi = (fp_t)U_MIN;
            } else if (zi > (fp_t)U_MAX) {
                zi = (fp_t)U_MAX;
            }
        } else {
            zi = 0;
        }

        fp_t yi = y[i] + rho_mul(Axi_fp - zi, use_ineq_rho);
        y[i] = yi;
        b_tmp[i] = rho_mul(zi, use_ineq_rho) - yi;
    }
    AT_mul(b_tmp, b);
}

void ADMM_solver(
    current_state_t current_in,
    command_out_t &command_out
) {
    static fp_t x[N_VAR] = {0};
    static bool traj_started = false;
    static int traj_idx = 0;
    static int traj_tick_div_ctr = 0;
    static const fp_t q_zero[N_VAR] = {0};
    fp_t current_state_vec[12];

    for (int i = 0; i < 12; i++) {
        current_state_vec[i] = current_in.state[i];
    }

    if (traj_reset_cmd(current_in)) {
        traj_started = false;
        traj_idx = 0;
        traj_tick_div_ctr = 0;
    }
    if (traj_start_cmd(current_in)) {
        traj_started = true;
    }

    const fp_t *q_runtime = q_zero;
    if (traj_started && (traj_idx < TRAJ_LENGTH)) {
        q_runtime = &traj_q_packed[traj_idx][0];
    }

ADMM_MAIN_LOOP:
    for (int iter = 0; iter < ADMM_ITERATIONS; iter++) {
        ADMM_iteration(x, current_state_vec, q_runtime);
    }

    if (traj_started && (traj_idx < TRAJ_LENGTH)) {
        traj_tick_div_ctr++;
        if (traj_tick_div_ctr >= TRAJ_TICK_DIV) {
            traj_tick_div_ctr = 0;
            traj_idx++;
        }
    }

    command_out.u0 = x[12] + (fp_t)U_HOVER;
    command_out.u1 = x[13] + (fp_t)U_HOVER;
    command_out.u2 = x[14] + (fp_t)U_HOVER;
    command_out.u3 = x[15] + (fp_t)U_HOVER;
}

void ADMM_solver_with_residuals(
    current_state_t current_in,
    fp_t x[N_VAR],
    fp_t *primal_residual,
    fp_t *dual_residual
) {
    static bool traj_started = false;
    static int traj_idx = 0;
    static int traj_tick_div_ctr = 0;
    static const fp_t q_zero[N_VAR] = {0};
    static fp_t b[N_VAR] = {0};
    static fp_t y[N_CONSTR] = {0};
    fp_t current_state_vec[12];

    for (int i = 0; i < 12; ++i) {
        current_state_vec[i] = current_in.state[i];
    }

    if (traj_reset_cmd(current_in)) {
        traj_started = false;
        traj_idx = 0;
        traj_tick_div_ctr = 0;
    }
    if (traj_start_cmd(current_in)) {
        traj_started = true;
    }

    const fp_t *q_runtime = q_zero;
    if (traj_started && (traj_idx < TRAJ_LENGTH)) {
        q_runtime = &traj_q_packed[traj_idx][0];
    }

    fp_t tmp[N_VAR];
    fp_t b_tmp[N_CONSTR];
    fp_t z_prev[N_CONSTR] = {0};
    fp_t z_curr[N_CONSTR] = {0};
    fp_t dz[N_CONSTR];
    fp_t rho_dz[N_CONSTR];
    fp_t ATdz[N_VAR];
    fp_t primal_last = 0;
    fp_t dual_last = 0;
    bool has_prev_z = false;

    for (int iter = 0; iter < ADMM_ITERATIONS; ++iter) {
        forward_substitution(b, q_runtime, tmp);
        backward_substitution(tmp, x);

        double primal_sq = 0.0;
        for (int i = 0; i < N_CONSTR; ++i) {
            acc_t Axi = 0;
            for (int j = 0; j < A_SPARSE_DATA_COLS; ++j) {
                Axi += (acc_t)A_sparse_data[i][j] * (acc_t)x[A_sparse_indexes[i][j]];
            }
            const fp_t Axi_fp = (fp_t)Axi;
            const bool use_ineq_rho = is_inequality_constraint(i);

            fp_t zi;
            if (i < STATE_SIZE) {
                zi = current_state_vec[i];
            } else if (i >= START_XY_INEQ) {
                zi = Axi_fp + rho_div(y[i], use_ineq_rho);
                if (zi < (fp_t)XY_MIN) {
                    zi = (fp_t)XY_MIN;
                } else if (zi > (fp_t)XY_MAX) {
                    zi = (fp_t)XY_MAX;
                }
            } else if (i >= START_U_INEQ) {
                zi = Axi_fp + rho_div(y[i], use_ineq_rho);
                if (zi < (fp_t)U_MIN) {
                    zi = (fp_t)U_MIN;
                } else if (zi > (fp_t)U_MAX) {
                    zi = (fp_t)U_MAX;
                }
            } else {
                zi = 0;
            }

            z_curr[i] = zi;

            const fp_t r_i = Axi_fp - zi;
            const double r_i_d = (double)r_i;
            primal_sq += r_i_d * r_i_d;

            const fp_t yi = y[i] + rho_mul(r_i, use_ineq_rho);
            y[i] = yi;
            b_tmp[i] = rho_mul(zi, use_ineq_rho) - yi;
        }

        AT_mul(b_tmp, b);

        primal_last = (fp_t)std::sqrt(primal_sq);
        if (has_prev_z) {
            for (int i = 0; i < N_CONSTR; ++i) {
                dz[i] = z_curr[i] - z_prev[i];
                rho_dz[i] = rho_mul(dz[i], is_inequality_constraint(i));
            }
            AT_mul(rho_dz, ATdz);

            double atdz_sq = 0.0;
            for (int i = 0; i < N_VAR; ++i) {
                const double v = (double)ATdz[i];
                atdz_sq += v * v;
            }
            dual_last = (fp_t)std::sqrt(atdz_sq);
        } else {
            dual_last = 0;
        }

        for (int i = 0; i < N_CONSTR; ++i) {
            z_prev[i] = z_curr[i];
        }
        has_prev_z = true;
    }

    if (primal_residual != nullptr) {
        *primal_residual = primal_last;
    }
    if (dual_residual != nullptr) {
        *dual_residual = dual_last;
    }

    if (traj_started && (traj_idx < TRAJ_LENGTH)) {
        traj_tick_div_ctr++;
        if (traj_tick_div_ctr >= TRAJ_TICK_DIV) {
            traj_tick_div_ctr = 0;
            traj_idx++;
        }
    }
}

template <typename T, bool IsFloat = std::is_floating_point<T>::value>
struct TypeWidth;

template <typename T>
struct TypeWidth<T, true> {
    static int width() { return (int)(sizeof(T) * 8); }
};

template <typename T>
struct TypeWidth<T, false> {
    static int width() { return T::width; }
};

fp_t admm_test_rho_mul(fp_t v) {
    return rho_mul(v, false);
}

fp_t admm_test_rho_div(fp_t v) {
    return rho_div(v, false);
}

int admm_test_fp_width() {
    return TypeWidth<fp_t>::width();
}

int admm_test_acc_width() {
    return TypeWidth<acc_t>::width();
}
