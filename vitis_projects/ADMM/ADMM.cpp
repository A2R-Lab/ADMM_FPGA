#include "data.h"
#include "traj_data.h"
#include "ADMM.h"
#include "data_types.h"
#include "admm_runtime_config.h"
#include <ap_fixed.h>
#include <cstdint>
#include <cmath>

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

typedef ap_fixed<fp_t::width + ACC_GUARD_BITS, fp_t::iwidth + ACC_GUARD_BITS, AP_RND, AP_SAT> acc_t;
typedef ap_fixed<fp_t::width + RHO_SHIFT_MAX_V, fp_t::iwidth + RHO_SHIFT_MAX_V, AP_TRN, AP_WRAP> rho_acc_t;

static inline bool is_inequality_constraint(int constraint_idx) {
    return constraint_idx >= START_INEQ;
}

static inline fp_t rho_mul_eq(fp_t v) {
    rho_acc_t t = v;
    t <<= RHO_SHIFT_EQ;
    return (fp_t)t;
}

static inline fp_t rho_mul_ineq(fp_t v) {
    rho_acc_t t = v;
    t <<= RHO_SHIFT_INEQ;
    return (fp_t)t;
}

static inline fp_t rho_div_eq(fp_t v) {
    rho_acc_t t = v;
    t >>= RHO_SHIFT_EQ;
    return (fp_t)t;
}

static inline fp_t rho_div_ineq(fp_t v) {
    rho_acc_t t = v;
    t >>= RHO_SHIFT_INEQ;
    return (fp_t)t;
}

static inline fp_t rho_mul(fp_t v, bool use_ineq_rho) {
    return use_ineq_rho ? rho_mul_ineq(v) : rho_mul_eq(v);
}

static inline fp_t rho_div(fp_t v, bool use_ineq_rho) {
    return use_ineq_rho ? rho_div_ineq(v) : rho_div_eq(v);
}

static inline bool traj_start_cmd(const current_state_t &current_in) {
    return current_in.traj_cmd[0] != 0;
}

static inline bool traj_reset_cmd(const current_state_t &current_in) {
    return current_in.traj_cmd[1] != 0;
}

static inline fp_t bits_to_fp(ap_uint<32> bits) {
    fp_t v;
    v.range(31, 0) = bits;
    return v;
}

static inline ap_uint<32> fp_to_bits(fp_t v) {
    return v.range(31, 0);
}

static inline current_state_t unpack_current_state(ap_uint<386> current_in_bits) {
    current_state_t current_in = {};
    for (int i = 0; i < 12; ++i) {
        current_in.state[i] = bits_to_fp(current_in_bits.range(i * 32 + 31, i * 32));
    }
    current_in.traj_cmd = current_in_bits.range(385, 384);
    return current_in;
}

static inline ap_uint<128> pack_command_out(const command_out_t &command_out) {
    ap_uint<128> command_out_bits = 0;
    command_out_bits.range(31, 0) = fp_to_bits(command_out.u0);
    command_out_bits.range(63, 32) = fp_to_bits(command_out.u1);
    command_out_bits.range(95, 64) = fp_to_bits(command_out.u2);
    command_out_bits.range(127, 96) = fp_to_bits(command_out.u3);
    return command_out_bits;
}

void forward_substitution(
    const fp_t b[L_BANDED_ROWS],
    bool use_traj_q,
    int traj_idx,
    fp_t x[L_BANDED_ROWS]
) {
    fp_t window[L_BANDED_COLS - 1] = {0};

    FORW_SUBST_EXTERN_LOOP:
    for (int i = 0; i < N_VAR; i++) {
        fp_t sum_val = 0;
        fp_t q_i = 0;

        if (use_traj_q && (traj_idx < TRAJ_LENGTH)) {
            q_i = traj_q_packed[traj_idx][i];
        }

        FORW_SUBST_DOT_PRODUCT_LOOP:
        for (int j = 0; j < L_BANDED_COLS - 1; j++) {
            acc_t mul_term = (acc_t)L_banded[i][j] * (acc_t)window[j];
            sum_val += (fp_t)mul_term;
        }

        fp_t new_x = (b[i] - q_i - sum_val) * L_banded[i][L_BANDED_COLS - 1];
        x[i] = new_x;

        FORW_SUBST_SHIFT_REGISTER_LOOP:
        for (int k = 0; k < L_BANDED_COLS - 2; k++) {
            window[k] = window[k + 1];
        }
        window[L_BANDED_COLS - 2] = new_x;
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
    fp_t b[N_VAR],
    fp_t y[N_CONSTR],
    fp_t current_state[12],
    bool use_traj_q,
    int traj_idx
) {
#pragma HLS INLINE
    fp_t tmp[N_VAR];
    fp_t b_tmp[N_CONSTR];

    forward_substitution(b, use_traj_q, traj_idx, tmp);
    backward_substitution(tmp, x);

    ADMM_IT_ZY_UPDATE_LOOP:
    for (int i = 0; i < N_CONSTR; i++) {
#pragma HLS PIPELINE II=1
        acc_t Axi_acc = 0;
        for (int j = 0; j < A_SPARSE_DATA_COLS; j++) {
#pragma HLS UNROLL
            Axi_acc += (acc_t)A_sparse_data[i][j] * (acc_t)x[A_sparse_indexes[i][j]];
        }
        fp_t Axi = (fp_t)Axi_acc;
        const bool use_ineq_rho = is_inequality_constraint(i);
        rho_acc_t y_div = (rho_acc_t)y[i];
        y_div >>= use_ineq_rho ? RHO_SHIFT_INEQ : RHO_SHIFT_EQ;

        fp_t zi;
        if (i < STATE_SIZE) {
            zi = current_state[i];
        } else if (i >= START_XY_INEQ) {
            zi = (fp_t)((rho_acc_t)Axi + y_div);
            if (zi < (fp_t)XY_MIN) {
                zi = (fp_t)XY_MIN;
            } else if (zi > (fp_t)XY_MAX) {
                zi = (fp_t)XY_MAX;
            }
        } else if (i >= START_U_INEQ) {
            zi = (fp_t)((rho_acc_t)Axi + y_div);
            if (zi < (fp_t)U_MIN) {
                zi = (fp_t)U_MIN;
            } else if (zi > (fp_t)U_MAX) {
                zi = (fp_t)U_MAX;
            }
        } else {
            zi = 0;
        }

        rho_acc_t r_shifted = (rho_acc_t)(Axi - zi);
        r_shifted <<= use_ineq_rho ? RHO_SHIFT_INEQ : RHO_SHIFT_EQ;
        fp_t yi = (fp_t)((rho_acc_t)y[i] + r_shifted);
        y[i] = yi;
        rho_acc_t zi_shifted = zi;
        zi_shifted <<= use_ineq_rho ? RHO_SHIFT_INEQ : RHO_SHIFT_EQ;
        b_tmp[i] = (fp_t)(zi_shifted - (rho_acc_t)yi);
    }
    AT_mul(b_tmp, b);
}

static void ADMM_solver_core(
    current_state_t current_in,
    command_out_t &command_out
) {
    static fp_t x[N_VAR] = {0};
    static fp_t b[N_VAR] = {0};
    static fp_t y[N_CONSTR] = {0};
    static bool traj_started = false;
    static int traj_idx = 0;
    static int traj_tick_div_ctr = 0;
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

    const bool use_traj_q = traj_started && (traj_idx < TRAJ_LENGTH);

ADMM_MAIN_LOOP:
    for (int iter = 0; iter < ADMM_ITERATIONS; iter++) {
        ADMM_iteration(x, b, y, current_state_vec, use_traj_q, traj_idx);
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

void ADMM_solver(
    ap_uint<386> current_in_bits,
    ap_uint<128> &command_out_bits
) {
    current_state_t current_in = unpack_current_state(current_in_bits);
    command_out_t command_out;
    ADMM_solver_core(current_in, command_out);
    command_out_bits = pack_command_out(command_out);
}

void ADMM_solver_with_residuals(
    current_state_t current_in,
    fp_t x[N_VAR],
    fp_t *primal_residual,
    fp_t *dual_residual
) {
#pragma HLS aggregate variable=current_in compact=bit
    static bool traj_started = false;
    static int traj_idx = 0;
    static int traj_tick_div_ctr = 0;
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

    const bool use_traj_q = traj_started && (traj_idx < TRAJ_LENGTH);

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
        forward_substitution(b, use_traj_q, traj_idx, tmp);
        backward_substitution(tmp, x);

        double primal_sq = 0.0;
        for (int i = 0; i < N_CONSTR; ++i) {
            fp_t Axi = 0;
            for (int j = 0; j < A_SPARSE_DATA_COLS; ++j) {
                Axi += A_sparse_data[i][j] * x[A_sparse_indexes[i][j]];
            }
            const bool use_ineq_rho = is_inequality_constraint(i);

            fp_t zi;
            if (i < STATE_SIZE) {
                zi = current_state_vec[i];
            } else if (i >= START_XY_INEQ) {
                zi = use_ineq_rho ? (Axi + (y[i] >> RHO_SHIFT_INEQ)) : (Axi + (y[i] >> RHO_SHIFT_EQ));
                if (zi < (fp_t)XY_MIN) {
                    zi = (fp_t)XY_MIN;
                } else if (zi > (fp_t)XY_MAX) {
                    zi = (fp_t)XY_MAX;
                }
            } else if (i >= START_U_INEQ) {
                zi = use_ineq_rho ? (Axi + (y[i] >> RHO_SHIFT_INEQ)) : (Axi + (y[i] >> RHO_SHIFT_EQ));
                if (zi < (fp_t)U_MIN) {
                    zi = (fp_t)U_MIN;
                } else if (zi > (fp_t)U_MAX) {
                    zi = (fp_t)U_MAX;
                }
            } else {
                zi = 0;
            }

            z_curr[i] = zi;

            const fp_t r_i = Axi - zi;
            const double r_i_d = (double)r_i;
            primal_sq += r_i_d * r_i_d;

            const fp_t yi = use_ineq_rho
                                ? (y[i] + (r_i << RHO_SHIFT_INEQ))
                                : (y[i] + (r_i << RHO_SHIFT_EQ));
            y[i] = yi;
            b_tmp[i] = use_ineq_rho ? ((zi << RHO_SHIFT_INEQ) - yi) : ((zi << RHO_SHIFT_EQ) - yi);
        }

        AT_mul(b_tmp, b);

        primal_last = (fp_t)std::sqrt(primal_sq);
        if (has_prev_z) {
            for (int i = 0; i < N_CONSTR; ++i) {
                dz[i] = z_curr[i] - z_prev[i];
                rho_dz[i] = is_inequality_constraint(i)
                                ? (dz[i] << RHO_SHIFT_INEQ)
                                : (dz[i] << RHO_SHIFT_EQ);
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

fp_t admm_test_rho_mul(fp_t v) {
    return rho_mul(v, false);
}

fp_t admm_test_rho_div(fp_t v) {
    return rho_div(v, false);
}

int admm_test_fp_width() {
    return fp_t::width;
}

int admm_test_acc_width() {
    return acc_t::width;
}
