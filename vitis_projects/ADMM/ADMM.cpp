#include "data.h"
#include "ADMM.h"
#include "data_types.h"
#include <ap_fixed.h>

void forward_substitution(
    const fp_t b[L_BANDED_ROWS],
    fp_t x[L_BANDED_ROWS]
) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=L_banded dim=2 complete

    fp_t window[L_BANDED_COLS-1] = {0};
#pragma HLS ARRAY_PARTITION variable=window dim=1 complete

    FORW_SUBST_EXTERN_LOOP:
    for (int i = 0; i < N_VAR; i++) {
#pragma HLS PIPELINE II=6
        fp_t sum_val = 0;

        FORW_SUBST_DOT_PRODUCT_LOOP:
        for (int j = 0; j < L_BANDED_COLS - 1; j++) {
#pragma HLS UNROLL factor=4
            sum_val += L_banded[i][j] * window[j];
        }

        fp_t new_x = (b[i] - sum_val) * L_banded[i][L_BANDED_COLS-1];
        x[i] = new_x;

        FORW_SUBST_SHIFT_REGISTER_LOOP:
        for (int k = 0; k < L_BANDED_COLS - 2; k++) {
#pragma HLS UNROLL factor=4
            window[k] = window[k+1];
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

    fp_t window[LT_BANDED_COLS-1];
#pragma HLS ARRAY_PARTITION variable=window dim=1 complete

    // Initialize window
    INIT_WINDOW:
    for (int j = 0; j < LT_BANDED_COLS-1; j++) {
#pragma HLS UNROLL
        window[j] = 0;
    }

    BACK_SUBST_EXTERN_LOOP:
    for (int i = LT_BANDED_ROWS - 1; i >= 0; i--) {
#pragma HLS PIPELINE II=6
        fp_t sum_val = 0;

        DOT_PRODUCT:
        for (int j = LT_BANDED_COLS-2; j >= 0; j--) {
#pragma HLS UNROLL factor=4
            sum_val += LT_banded[i][j+1] * window[j];
        }

        fp_t new_x = (b[i] - sum_val) * LT_banded[i][0];
        x[i] = new_x;

        SHIFT_WINDOW:
        for (int k = LT_BANDED_COLS - 2; k > 0; k--) {
#pragma HLS UNROLL factor=4
            window[k] = window[k-1];
        }
        window[0] = new_x;
    }
}

void AT_mul(
    const fp_t x[AT_SPARSE_DATA_ROWS],
    fp_t ATx[AT_SPARSE_DATA_ROWS]
) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=AT_sparse_data dim=2 complete
#pragma HLS ARRAY_PARTITION variable=AT_sparse_indexes dim=2 complete

    AT_MUL_EXTERN_LOOP:
    for (int i = 0; i < AT_SPARSE_DATA_ROWS; i++) {
#pragma HLS PIPELINE II=1
        fp_t sum_val = 0;
        AT_MUL_DOT_PRODUCT_LOOP:
        for (int j = 0; j < AT_SPARSE_DATA_COLS; j++) {
#pragma HLS UNROLL
            sum_val += AT_sparse_data[i][j] * x[AT_sparse_indexes[i][j]];
        }
        ATx[i] = sum_val;
    }
}

void ADMM_iteration(
    fp_t x[N_VAR], 
    fp_t current_state[12]
) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=A_sparse_data dim=2 complete
#pragma HLS ARRAY_PARTITION variable=A_sparse_indexes dim=2 complete
    // current_state kept as single port for top-level interface

    static fp_t b[N_VAR] = {0};
#pragma HLS ARRAY_PARTITION variable=b cyclic factor=16 dim=1
    static fp_t y[N_VAR] = {0};
#pragma HLS ARRAY_PARTITION variable=y cyclic factor=16 dim=1
    fp_t tmp[N_VAR];
#pragma HLS ARRAY_PARTITION variable=tmp cyclic factor=16 dim=1
    fp_t b_tmp[N_VAR];
#pragma HLS ARRAY_PARTITION variable=b_tmp cyclic factor=16 dim=1

    // x_update
    // first cycle b will be 0 anyway, and then it gets updated at the end of the iteration
    forward_substitution(b, tmp);
    backward_substitution(tmp, x);

    // z - y update
    ADMM_IT_ZY_UPDATE_LOOP:
    for (int i = 0; i < N_VAR; i++) {
#pragma HLS PIPELINE II=1
        fp_t Axi = 0;
        for (int j = 0; j < A_SPARSE_DATA_COLS; j++) {
#pragma HLS UNROLL
            Axi += A_sparse_data[i][j] * x[A_sparse_indexes[i][j]];
        }

        fp_t zi;
        if(i < STATE_SIZE) {
            zi = current_state[i];
        } else if (i >= START_INEQ) { // This will depend on horizon length
            zi = Axi + (y[i] >> RHO_SHIFT);
            // Cast to fp_t to avoid floating-point comparison hardware
            if (zi < (fp_t)U_MIN) {
                zi = (fp_t)U_MIN;
            } else if (zi > (fp_t)U_MAX) {
                zi = (fp_t)U_MAX;
            }
        } else {
            zi = 0;
        }

        fp_t yi = y[i] + ((Axi - zi) << RHO_SHIFT);
        y[i] = yi;
        b_tmp[i] = (zi << RHO_SHIFT) - yi;

    }
    AT_mul(b_tmp, b);
}

void ADMM_solver(
    fp_t current_state[12],
    fp_t x[N_VAR],
    int iters
) {
    // x kept as single port so top_spi RTL interface matches
    ADMM_MAIN_LOOP:
    for (int iter = 0; iter < 10; iter++) {
#pragma HLS PIPELINE off
        ADMM_iteration(x, current_state);
    }
}
