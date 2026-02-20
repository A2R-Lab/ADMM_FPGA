#ifndef ADMM_H
#define ADMM_H
#include "data_types.h"
#include "data.h"

void forward_substitution(
    const fp_t b[N_VAR],
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
    state_t current_state
);

void ADMM_solver(
    state_t current_state,
    fp_t x[N_VAR],
    int iters
);

#endif // ADMM_H