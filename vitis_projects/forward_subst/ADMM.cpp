
// #include "forward_300_20.h"
#include "data.h"
#include "ADMM.h"
#include <ap_fixed.h>

const fp_t rho = 256;
const fp_t rho_mult = 1024;

void forward_substitution(
    const fp_t b[L_BANDED_ROWS],
    fp_t x[L_BANDED_ROWS]
) { 
    fp_t window[L_BANDED_COLS-1] = {0};
    
    for (int i = 0; i < L_BANDED_ROWS; i++) {
        #pragma HLS PIPELINE II=11

        fp_t sum_val = 0;

        // dot product with window
        for (int j = 0; j < L_BANDED_COLS - 1; j++) {
            // #pragma HLS UNROLL
            sum_val += L_banded[i][j] * window[j];
        }

        fp_t new_x = (b[i] - sum_val) * L_banded[i][L_BANDED_COLS-1];
        x[i] = new_x;

        // shift register window
        for (int k = 0; k < L_BANDED_COLS - 2; k++) {
            // #pragma HLS UNROLL
            window[k] = window[k+1];
        }
        window[L_BANDED_COLS - 2] = new_x;
    }
}

void backward_substitution(
    const fp_t b[LT_BANDED_ROWS],
    fp_t x[LT_BANDED_ROWS]
) { 
    fp_t window[LT_BANDED_COLS-1] = {0};
    
    for (int i = LT_BANDED_ROWS - 1; i >= 0; i--) {
        fp_t sum_val = 0;

        // dot product with window
        for (int j = 0; j < LT_BANDED_COLS - 1; j++) {
            // #pragma HLS UNROLL
            sum_val += LT_banded[i][j] * window[j];
        }

        fp_t new_x = (b[i] - sum_val) * LT_banded[i][LT_BANDED_COLS-1];
        x[i] = new_x;

        // shift register window
        for (int k = 0; k < LT_BANDED_COLS - 2; k++) {
            // #pragma HLS UNROLL
            window[k] = window[k+1];
        }
        window[LT_BANDED_COLS - 2] = new_x;
    }
}

void A_mul(
    const fp_t x[A_SPARSE_DATA_ROWS],
    fp_t Ax[A_SPARSE_DATA_ROWS]
) {
    for (int i = 0; i < A_SPARSE_DATA_ROWS; i++) {
        fp_t sum_val = 0;
        for (int j = 0; j < A_SPARSE_DATA_COLS; j++) {
            sum_val += A_sparse_data[i][j] * x[A_sparse_indexes[i][j]];
        }
        Ax[i] = sum_val;
    }
}

void AT_mul(
    const fp_t x[AT_SPARSE_DATA_ROWS],
    fp_t ATx[AT_SPARSE_DATA_ROWS]
) {
    for (int i = 0; i < AT_SPARSE_DATA_ROWS; i++) {
        fp_t sum_val = 0;
        for (int j = 0; j < AT_SPARSE_DATA_COLS; j++) {
            sum_val += AT_sparse_data[i][j] * x[AT_sparse_indexes[i][j]];
        }
        ATx[i] = sum_val;
    }
}


void clamp(
    fp_t x[L_SIZE]
) {
    for (int i = 0; i < L_SIZE; i++) {
        if (x[i] < l[i]) {
            x[i] = l[i];
        } else if (x[i] > u[i]) {
            x[i] = u[i];
        }
    }
}

void ADMM_iteration(
    fp_t x[L_SIZE], 
    fp_t z[L_SIZE], 
    fp_t y[L_SIZE]
) {
    fp_t b[L_SIZE];
    fp_t tmp[L_SIZE];
    fp_t tmp2[L_SIZE];
    fp_t Ax[L_SIZE];

    // x-update

    // b computation
    for( int i = 0; i < L_SIZE; i++) {
        tmp[i] = (z[i] << rho) - y[i];
    }
    AT_mul(tmp, b);
    forward_substitution(b, tmp2);
    backward_substitution(tmp2, x);

    // z update
    A_mul(x, Ax);
    for (int i = 0; i < L_SIZE; i++) {
        z[i] = Ax[i] + (y[i] >> rho);
    }
    clamp(z);

    // y-update
    for (int i = 0; i < L_SIZE; i++) {
        y[i] += (Ax[i] - z[i]) << rho;
    }
}

void ADMM_solver(
    fp_t x[L_SIZE],
    int iters,
    bool reset
) {
    static fp_t z[L_SIZE];
    static fp_t y[L_SIZE];

    if (reset) {
        for (int i = 0; i < L_SIZE; i++) {
            x[i] = 0;
            z[i] = 0;
            y[i] = 0;
        }
    }

    for (int iter = 0; iter < iters; iter++) {
        ADMM_iteration(x, z, y);
    }
}