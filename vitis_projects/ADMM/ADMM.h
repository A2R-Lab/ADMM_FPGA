#ifndef ADMM_H
#define ADMM_H

#include "data_types.h"
#include "data.h"

void forward_substitution(
    const fp_t b[N_VAR],
    const fp_t q[N_VAR],
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
    fp_t current_state[12],
    const fp_t q_vec[N_VAR]
);

void ADMM_solver(
    current_state_t current_in,
    command_out_t &command_out
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
