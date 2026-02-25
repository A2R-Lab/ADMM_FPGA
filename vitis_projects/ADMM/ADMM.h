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
    fp_t current_state[12]
);

void ADMM_solver(
    current_state_t current_in,
    command_out_t &command_out
);

#endif // ADMM_H