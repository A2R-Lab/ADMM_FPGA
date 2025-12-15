#include "data.h"
#include "ADMM.h"
#include "data_types.h"
#include <ap_fixed.h>

const fp_t rho = 8;

void forward_substitution(
    const fp_t b[L_BANDED_ROWS],
    fp_t x[L_BANDED_ROWS]
) {
    fp_t window[L_BANDED_COLS-1] = {0};

    FORW_SUBST_EXTERN_LOOP:
    for (int i = 0; i < L_BANDED_ROWS; i++) {
        fp_t sum_val = 0;

        FORW_SUBST_DOT_PRODUCT_LOOP:
        // dot product with window
        for (int j = 0; j < L_BANDED_COLS - 1; j++) {
            sum_val += L_banded[i][j] * window[j];
        }

        fp_t new_x = (b[i] - sum_val) * L_banded[i][L_BANDED_COLS-1];
        x[i] = new_x;

        FORW_SUBST_SHIFT_REGISTER_LOOP:
        // shift register window
        for (int k = 0; k < L_BANDED_COLS - 2; k++) {
            window[k] = window[k+1];
        }
        window[L_BANDED_COLS - 2] = new_x;
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
        fp_t sum_val = 0;

        DOT_PRODUCT:
        for (int j = LT_BANDED_COLS-2; j >= 0; j--) {
            sum_val += LT_banded[i][j+1] * window[j];
        }

        // Compute new x value
        fp_t new_x = (b[i] - sum_val) * LT_banded[i][0];
        x[i] = new_x;

        // Shift window - this happens in parallel with next iteration setup
        SHIFT_WINDOW:
        for (int k = LT_BANDED_COLS - 2; k > 0; k--) {
            window[k] = window[k-1];
        }
        window[0] = new_x;
    }
}

void A_mul(
    const fp_t x[A_SPARSE_DATA_ROWS],
    fp_t Ax[A_SPARSE_DATA_ROWS]
) {
    A_MUL_EXTERN_LOOP:
    for (int i = 0; i < A_SPARSE_DATA_ROWS; i++) {
        fp_t sum_val = 0;
        A_MUL_DOT_PRODUCT_LOOP:
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
    AT_MUL_EXTERN_LOOP:
    for (int i = 0; i < AT_SPARSE_DATA_ROWS; i++) {
        fp_t sum_val = 0;
        AT_MUL_DOT_PRODUCT_LOOP:
        for (int j = 0; j < AT_SPARSE_DATA_COLS; j++) {
            sum_val += AT_sparse_data[i][j] * x[AT_sparse_indexes[i][j]];
        }
        ATx[i] = sum_val;
    }
}


void clamp(
    fp_t x[L_SIZE]
) {
    CLAMP_LOOP:
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
    ADMM_IT_B_COMPUTE_LOOP:
    for( int i = 0; i < L_SIZE; i++) {
        tmp[i] = (z[i] << rho) - y[i];
    }
    AT_mul(tmp, b);
    forward_substitution(b, tmp2);
    backward_substitution(tmp2, x);

    // z update
    A_mul(x, Ax);
    ADMM_IT_Z_UPDATE_LOOP:
    for (int i = 0; i < L_SIZE; i++) {
        z[i] = Ax[i] + (y[i] >> rho);
    }
    clamp(z);

    // y-update
    ADMM_IT_Y_UPDATE_LOOP:
    for (int i = 0; i < L_SIZE; i++) {
        y[i] += (Ax[i] - z[i]) << rho;
    }
}

const int iters = 10;
void ADMM_solver(
    const fp_t obs[12],
    fp_t motor_controls[4],
    bool reset
) {
    static fp_t x[L_SIZE];
    static fp_t z[L_SIZE];
    static fp_t y[L_SIZE];

    // if (reset) {
    //     ADMM_RESET_LOOP:
    //     for (int i = 0; i < L_SIZE; i++) {
    //         x[i] = 0;
    //         z[i] = 0;
    //         y[i] = 0;
    //     }
    // }

    ADMM_MAIN_LOOP:
    for (int iter = 0; iter < iters; iter++) {
        ADMM_iteration(x, z, y);
    }
}
