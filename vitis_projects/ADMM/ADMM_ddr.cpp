#include "ADMM_ddr.h"

#include <ap_fixed.h>

static inline fp_t read_fp_word(const ap_uint<32> *matrix_blob, unsigned word_offset) {
    #pragma HLS INLINE
    fp_t out;
    out.range(31, 0) = matrix_blob[word_offset];
    return out;
}

static inline fp_t read_fp_matrix(
    const ap_uint<32> *matrix_blob,
    unsigned base_word_offset,
    unsigned cols,
    unsigned row,
    unsigned col
) {
    #pragma HLS INLINE
    unsigned word_offset = base_word_offset + row * cols + col;
    return read_fp_word(matrix_blob, word_offset);
}

static inline unsigned read_sparse_index(
    const ap_uint<32> *matrix_blob,
    unsigned base_word_offset,
    unsigned element_index
) {
    #pragma HLS INLINE
#if MATRIX_BLOB_INDEX_BITS == 16
    unsigned packed_word_offset = base_word_offset + (element_index >> 1);
    ap_uint<32> packed = matrix_blob[packed_word_offset];
    ap_uint<16> idx = (element_index & 1U) ? packed.range(31, 16) : packed.range(15, 0);
    return (unsigned)idx;
#elif MATRIX_BLOB_INDEX_BITS == 32
    return (unsigned)matrix_blob[base_word_offset + element_index];
#else
#error "Unsupported MATRIX_BLOB_INDEX_BITS value"
#endif
}

static void forward_substitution_ddr(
    const ap_uint<32> *matrix_blob,
    const fp_t b[N_VAR],
    fp_t x[N_VAR]
) {
    fp_t window[MATRIX_L_BANDED_COLS - 1] = {0};

FORW_SUBST_EXTERN_LOOP_DDR:
    for (int i = 0; i < N_VAR; i++) {
        fp_t sum_val = 0;

FORW_SUBST_DOT_PRODUCT_LOOP_DDR:
        for (int j = 0; j < MATRIX_L_BANDED_COLS - 1; j++) {
            fp_t coeff = read_fp_matrix(
                matrix_blob,
                MATRIX_L_BANDED_WORD_OFFSET,
                MATRIX_L_BANDED_COLS,
                (unsigned)i,
                (unsigned)j
            );
            sum_val += coeff * window[j];
        }

        fp_t inv_diag = read_fp_matrix(
            matrix_blob,
            MATRIX_L_BANDED_WORD_OFFSET,
            MATRIX_L_BANDED_COLS,
            (unsigned)i,
            (unsigned)(MATRIX_L_BANDED_COLS - 1)
        );

        fp_t new_x = (b[i] - sum_val) * inv_diag;
        x[i] = new_x;

FORW_SUBST_SHIFT_WINDOW_LOOP_DDR:
        for (int k = 0; k < MATRIX_L_BANDED_COLS - 2; k++) {
            window[k] = window[k + 1];
        }
        window[MATRIX_L_BANDED_COLS - 2] = new_x;
    }
}

static void backward_substitution_ddr(
    const ap_uint<32> *matrix_blob,
    const fp_t b[N_VAR],
    fp_t x[N_VAR]
) {
    fp_t window[MATRIX_LT_BANDED_COLS - 1];

INIT_BACK_WINDOW_DDR:
    for (int j = 0; j < MATRIX_LT_BANDED_COLS - 1; j++) {
        window[j] = 0;
    }

BACK_SUBST_EXTERN_LOOP_DDR:
    for (int i = N_VAR - 1; i >= 0; i--) {
        fp_t sum_val = 0;

BACK_SUBST_DOT_PRODUCT_LOOP_DDR:
        for (int j = MATRIX_LT_BANDED_COLS - 2; j >= 0; j--) {
            fp_t coeff = read_fp_matrix(
                matrix_blob,
                MATRIX_LT_BANDED_WORD_OFFSET,
                MATRIX_LT_BANDED_COLS,
                (unsigned)i,
                (unsigned)(j + 1)
            );
            sum_val += coeff * window[j];
        }

        fp_t inv_diag = read_fp_matrix(
            matrix_blob,
            MATRIX_LT_BANDED_WORD_OFFSET,
            MATRIX_LT_BANDED_COLS,
            (unsigned)i,
            0
        );

        fp_t new_x = (b[i] - sum_val) * inv_diag;
        x[i] = new_x;

BACK_SUBST_SHIFT_WINDOW_LOOP_DDR:
        for (int k = MATRIX_LT_BANDED_COLS - 2; k > 0; k--) {
            window[k] = window[k - 1];
        }
        window[0] = new_x;
    }
}

static void AT_mul_ddr(
    const ap_uint<32> *matrix_blob,
    const fp_t x[N_VAR],
    fp_t ATx[N_VAR]
) {
AT_MUL_EXTERN_LOOP_DDR:
    for (int i = 0; i < N_VAR; i++) {
        fp_t sum_val = 0;

AT_MUL_DOT_PRODUCT_LOOP_DDR:
        for (int j = 0; j < MATRIX_AT_SPARSE_DATA_COLS; j++) {
            unsigned elem_index = (unsigned)i * MATRIX_AT_SPARSE_INDEXES_COLS + (unsigned)j;
            unsigned idx = read_sparse_index(matrix_blob, MATRIX_AT_SPARSE_INDEXES_WORD_OFFSET, elem_index);
            fp_t coeff = read_fp_matrix(
                matrix_blob,
                MATRIX_AT_SPARSE_DATA_WORD_OFFSET,
                MATRIX_AT_SPARSE_DATA_COLS,
                (unsigned)i,
                (unsigned)j
            );
            sum_val += coeff * x[idx];
        }
        ATx[i] = sum_val;
    }
}

static inline void ADMM_iteration_ddr(
    const ap_uint<32> *matrix_blob,
    fp_t x[N_VAR],
    fp_t current_state[STATE_SIZE]
) {
    #pragma HLS INLINE

    static fp_t b[N_VAR] = {0};
    static fp_t y[N_VAR] = {0};
    fp_t tmp[N_VAR];
    fp_t b_tmp[N_VAR];

    forward_substitution_ddr(matrix_blob, b, tmp);
    backward_substitution_ddr(matrix_blob, tmp, x);

ADMM_IT_ZY_UPDATE_LOOP_DDR:
    for (int i = 0; i < N_VAR; i++) {
        fp_t Axi = 0;

ADMM_IT_ZY_DOT_PRODUCT_LOOP_DDR:
        for (int j = 0; j < MATRIX_A_SPARSE_DATA_COLS; j++) {
            unsigned elem_index = (unsigned)i * MATRIX_A_SPARSE_INDEXES_COLS + (unsigned)j;
            unsigned idx = read_sparse_index(matrix_blob, MATRIX_A_SPARSE_INDEXES_WORD_OFFSET, elem_index);
            fp_t coeff = read_fp_matrix(
                matrix_blob,
                MATRIX_A_SPARSE_DATA_WORD_OFFSET,
                MATRIX_A_SPARSE_DATA_COLS,
                (unsigned)i,
                (unsigned)j
            );
            Axi += coeff * x[idx];
        }

        fp_t zi;
        if (i < STATE_SIZE) {
            zi = current_state[i];
        } else if (i >= START_INEQ) {
            zi = Axi + (y[i] >> RHO_SHIFT);
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

    AT_mul_ddr(matrix_blob, b_tmp, b);
}

void ADMM_solver_ddr(
    current_state_t current_in,
    command_out_t &command_out,
    const ap_uint<32> *matrix_blob
) {
    #pragma HLS INTERFACE ap_ctrl_hs port=return
    #pragma HLS INTERFACE ap_none port=current_in
    #pragma HLS INTERFACE ap_vld port=command_out
    #pragma HLS INTERFACE m_axi port=matrix_blob offset=direct bundle=gmem depth=MATRIX_BLOB_TOTAL_WORDS max_read_burst_length=64 num_read_outstanding=16

    static fp_t x[N_VAR] = {0};
    fp_t current_state_vec[STATE_SIZE];

LOAD_STATE_LOOP_DDR:
    for (int i = 0; i < STATE_SIZE; i++) {
        current_state_vec[i] = current_in.state[i];
    }

ADMM_MAIN_LOOP_DDR:
    for (int iter = 0; iter < ADMM_ITERS; iter++) {
        ADMM_iteration_ddr(matrix_blob, x, current_state_vec);
    }

    command_out.u0 = x[12] + (fp_t)U_HOVER;
    command_out.u1 = x[13] + (fp_t)U_HOVER;
    command_out.u2 = x[14] + (fp_t)U_HOVER;
    command_out.u3 = x[15] + (fp_t)U_HOVER;
}
