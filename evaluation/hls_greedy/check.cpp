#include "ADMM.h"
#include <cstdio>
// Compare raw bits of x, b, y after every iteration, including retained workspace.
int main() {
    fp_t x[N_VAR] = {}, b[N_VAR] = {}, y[N_CONSTR] = {}, q[N_VAR] = {};
    fp_t state[12] = {};
    for (int sample = 0; sample < 8; ++sample) {
        for (int j = 0; j < 12; ++j)
            state[j] = sample == 0 ? 0.0 : 0.03 * ((sample * 7 + j * 3) % 19 - 9);
        for (int j = 0; j < N_VAR; ++j)
            q[j] = sample == 0 ? 0.0 : 0.05 * ((sample + j) % 11 - 5);
        for (int it = 0; it < 10; ++it) {
            ADMM_iteration(x, b, y, state, false, 0, (fp_t)-0.15, (fp_t)0.18, q, true);
            for (int j = 0; j < N_VAR; ++j) {
                std::printf("%08x %08x\n", fp_to_bits(x[j]).to_uint(), fp_to_bits(b[j]).to_uint());
                if (sample == 0 && (x[j] != 0 || b[j] != 0)) return 2;
            }
            for (int j = 0; j < N_CONSTR; ++j) std::printf("%08x\n", fp_to_bits(y[j]).to_uint());
        }
    }
}
