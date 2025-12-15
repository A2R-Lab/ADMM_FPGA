#ifndef ADMM_H
#define ADMM_H
#include "data_types.h"
#include "data.h"

void forward_substitution(
    const fp_t b[L_BANDED_ROWS],
    fp_t x[L_BANDED_ROWS]
);

void backward_substitution(
    const fp_t b[LT_BANDED_ROWS],
    fp_t x[LT_BANDED_ROWS]
);

void A_mul(
    const fp_t x[L_SIZE],
    fp_t Ax[L_SIZE]
);

void AT_mul(
    const fp_t x[L_SIZE],
    fp_t ATx[L_SIZE]
);

void clamp(
    fp_t x[L_SIZE]
);

void ADMM_iteration(
    fp_t x[L_SIZE],
    fp_t z[L_SIZE],
    fp_t y[L_SIZE]
);

void ADMM_solver(
    fp_t x[L_SIZE],
    int iters,
    bool reset
);

#endif // ADMM_H