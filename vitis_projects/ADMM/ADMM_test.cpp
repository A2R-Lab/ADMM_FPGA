#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "data_types.h"
#include "ADMM.h"
#include "test_data.h"

const double REL_ERROR = .03;

static ap_uint<386> pack_current_state(const current_state_t &current) {
    ap_uint<386> bits = 0;
    for (int i = 0; i < 12; ++i) {
        bits.range(i * 32 + 31, i * 32) = fp_to_bits(current.state[i]);
    }
    bits.range(385, 384) = current.traj_cmd;
    return bits;
}

static command_out_t unpack_command_out(ap_uint<128> bits) {
    command_out_t out;
    out.u0 = bits_to_fp(bits.range(31, 0));
    out.u1 = bits_to_fp(bits.range(63, 32));
    out.u2 = bits_to_fp(bits.range(95, 64));
    out.u3 = bits_to_fp(bits.range(127, 96));
    return out;
}

bool compare_vectors(const fp_t *dut, const double *ref, size_t size, double max_rel_err) {
    bool ret = true;
    double rel_error;
    int fail_count = 0;
    for (int i = 0; i < (int)size; i++) {
        if (fabs(ref[i]) > 1e-5) {
            rel_error = fabs(((double)dut[i]) - ref[i]) / fabs(ref[i]);
        } else {
            rel_error = fabs(((double)dut[i]) - ref[i]);
        }

        if (rel_error > max_rel_err) {
            printf("Test failed at index %d: expected %f, got %f. Relative error is: %f.\n",
                   i, ref[i], (double)dut[i], rel_error);
            ret = false;
            fail_count++;
        }
    }
    printf("Number of failed elements: %d out of %zu\n", fail_count, size);
    printf(ret ? "------------ PASSED ------------\n" : "------------ NOT passed ------------\n");
    return ret;
}

int main() {
    bool res = true;

    current_state_t current = {};
    ap_uint<128> cmd_out_bits = 0;

    current.state[0] = (fp_t)0.1;
    current.state[1] = (fp_t)0.1;
    current.state[2] = (fp_t)-0.1;
    current.traj_cmd = 0;

    printf("================= ADMM SOLVER %d iterations =================\n", ADMM_ITERATIONS);

    ADMM_solver(pack_current_state(current), cmd_out_bits);
    command_out_t cmd_out = unpack_command_out(cmd_out_bits);

    fp_t dut_controls[4];
    double ref_controls[4];

    dut_controls[0] = cmd_out.u0 - (fp_t)U_HOVER;
    dut_controls[1] = cmd_out.u1 - (fp_t)U_HOVER;
    dut_controls[2] = cmd_out.u2 - (fp_t)U_HOVER;
    dut_controls[3] = cmd_out.u3 - (fp_t)U_HOVER;

    for (int i = 0; i < 4; ++i) {
        ref_controls[i] = ADMM_x_after_hw_iters[12 + i];
    }

    printf("================= Comparing control outputs against ADMM_x_after_hw_iters =================\n");
    res &= compare_vectors(dut_controls, ref_controls, 4, REL_ERROR);

    return res ? 0 : 1;
}
