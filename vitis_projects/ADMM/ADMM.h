#ifndef ADMM_H
#define ADMM_H

#include "data_types.h"
#include "data.h"

void forward_substitution(
    const fp_t b[N_VAR],
    bool use_traj_q,
    int traj_idx,
    fp_t x[N_VAR]
);

void backward_substitution(
    const fp_t b[N_VAR],
    fp_t x[N_VAR]
);

void AT_mul(
    const fp_t x[N_CONSTR],
    fp_t ATx[N_VAR]
);

void ADMM_iteration(
    fp_t x[N_VAR],
    fp_t b[N_VAR],
    fp_t y[N_CONSTR],
    fp_t current_state[12],
    bool use_traj_q,
    int traj_idx
);

void ADMM_solver(
    ap_uint<386> current_in_bits,
    ap_uint<128> &command_out_bits
);

void ADMM_solver_with_residuals(
    current_state_t current_in,
    fp_t x[N_VAR],
    fp_t* primal_residual,
    fp_t* dual_residual
);

fp_t admm_test_rho_mul(fp_t v);
fp_t admm_test_rho_div(fp_t v);
int admm_test_fp_width();
int admm_test_acc_width();

#endif // ADMM_H
