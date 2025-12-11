
    // #include "forward_300_20.h"
    #include "forward_10_3.h"

    void forward_substitution(
        const fp_t b[N],
        fp_t x[N]
    ) { 
        fp_t window[MAX_BANDWIDTH-1] = {0};
        // #pragma HLS ARRAY_PARTITION complete variable=window

        for (int i = 0; i < N; i++) {
            #pragma HLS PIPELINE II=11

            fp_t sum_val = 0;

            // dot product with window
            for (int j = 0; j < MAX_BANDWIDTH - 1; j++) {
                // #pragma HLS UNROLL
                sum_val += L_row[i][j] * window[j];
            }

            fp_t new_x = (b[i] - sum_val) * L_row[i][MAX_BANDWIDTH-1];
            x[i] = new_x;

            // shift register window
            for (int k = 0; k < MAX_BANDWIDTH - 2; k++) {
                // #pragma HLS UNROLL
                window[k] = window[k+1];
            }
            window[MAX_BANDWIDTH - 2] = new_x;
        }
    }