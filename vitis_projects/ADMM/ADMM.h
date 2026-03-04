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
    const fp_t x[N_VAR],
    fp_t ATx[N_VAR]
);

void ADMM_iteration(
    fp_t x[N_VAR], 
    fp_t current_state[12],
    const fp_t q_vec[N_VAR]
);

void ADMM_solver(
    fp_t current_state[12],
    fp_t x[N_VAR],
    int start_traj
);

#endif // ADMM_HN_VAR
