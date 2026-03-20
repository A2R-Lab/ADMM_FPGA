#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "data_types.h"
#include "ADMM.h"
#include "test_data.h"

const double REL_ERROR = .03;

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

    command_out_t cmd_out;
    current_state_t current = {};

    current.state[0] = (fp_t)0.1;
    current.state[1] = (fp_t)0.1;
    current.state[2] = (fp_t)-0.1;
    current.traj_cmd = 0;

    printf("================= ADMM SOLVER %d iterations =================\n", ADMM_ITERATIONS);

    ADMM_solver(current, cmd_out);

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
