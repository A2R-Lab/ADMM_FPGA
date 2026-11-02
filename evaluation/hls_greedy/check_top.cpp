#include "ADMM.h"
#include <cstdio>
#ifndef GENERATE_GOLDEN
#include "top_golden.h"
#endif

int main() {
    for (int sample = 0; sample < 3; ++sample) {
        current_state_t state = {};
        for (int j = 0; j < 12; ++j)
            state.state[j] = sample == 0 ? 0.0 : 0.02 * ((sample * 7 + j * 3) % 17 - 8);
        if (sample == 2) {
            state.constraints.range(15, 0) = ap_int<16>(-150);
            state.constraints.range(31, 16) = ap_int<16>(180);
        }
        ap_uint<128> output;
        ADMM_solver(pack_current_state_bits(state), output);
        for (int j = 0; j < 4; ++j) {
            ap_uint<32> word = output.range(j * 32 + 31, j * 32);
#ifdef GENERATE_GOLDEN
            std::printf("%u\n", word.to_uint());
#else
            if (word.to_uint() != golden[sample][j]) {
                std::printf("Mismatch sample=%d channel=%d actual=%u expected=%u\n",
                            sample, j, word.to_uint(), golden[sample][j]);
                return 1;
            }
#endif
        }
    }
#ifndef GENERATE_GOLDEN
    std::puts("Three top-level retained-state transactions matched baseline bits");
#endif
}
