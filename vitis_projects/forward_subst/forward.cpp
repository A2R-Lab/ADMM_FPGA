
    // #include "forward_300_20.h"
    #include "forward_10_3.h"

    void forward_substitution(
        const fp_t b[N],
        fp_t x[N]
    ) { 
        fp_t window[MAX_BANDWIDTH-1] = {0};
        // #pragma HLS ARRAY_PARTITION complete variable=window

        FORW_EXT: for (int i = 0; i < N; i++) {
            #pragma HLS PIPELINE II=11

            fp_t sum_val = 0;

            // dot product with window
        FORW_DOT:    for (int j = 0; j < MAX_BANDWIDTH - 1; j++) {
                // #pragma HLS UNROLL
                sum_val += L_row[i][j] * window[j];
            }

            fp_t new_x = (b[i] - sum_val) * L_row[i][MAX_BANDWIDTH-1];
            x[i] = new_x;

            // shift register window
        FORW_SHIFT:    for (int k = 0; k < MAX_BANDWIDTH - 2; k++) {
                // #pragma HLS UNROLL
                window[k] = window[k+1];
            }
            window[MAX_BANDWIDTH - 2] = new_x;
        }
    }

void backward_substitution(
    const fp_t b[N],
    fp_t x[N]
) {
    fp_t window[MAX_BANDWIDTH - 1] = {0};
    // #pragma HLS ARRAY_PARTITION complete variable=window

    BACK_EXT: for (int i = N - 1; i >= 0; i--) {
        // #pragma HLS PIPELINE II=1

        fp_t sum_val = 0;

        // Dot product with window: x[i] depends on x[i+1], x[i+2], ...
    BACK_DOT:    for (int k = 1; k < MAX_BANDWIDTH; k++) {
            // #pragma HLS UNROLL

            int j = i + k;
            // if (j < N) 
            {
                // Lᵀ(i, j) = L(j, i)
                // L_row[j][(MAX_BANDWIDTH-1) - k] stores L(j, j-k)
                // and j-k == i, which is the column we want
                fp_t coeff = L_row[j][(MAX_BANDWIDTH - 1) - k];
                sum_val += coeff * window[k - 1];
            }
        }

        // Diagonal of Lᵀ is the same diagonal
        fp_t new_x = (b[i] - sum_val) * L_row[i][MAX_BANDWIDTH - 1];
        x[i] = new_x;

        // Shift window left
    BACK_SHIFT:    for (int s = MAX_BANDWIDTH - 2; s > 0; s--) {
            // #pragma HLS UNROLL
            window[s] = window[s - 1];
        }
        window[0] = new_x;
    }
}
