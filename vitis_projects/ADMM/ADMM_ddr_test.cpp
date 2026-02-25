#include <math.h>
#include <stdio.h>

#include "ADMM_ddr.h"
#include "matrix_blob_sim.h"
#include "test_data.h"

static const double REL_ERROR = 0.01;

static bool compare_vectors(const fp_t *dut, const double *ref, size_t size, double max_rel_err) {
    bool ret = true;
    int fail_count = 0;

    for (size_t i = 0; i < size; i++) {
        double rel_error;
        if (fabs(ref[i]) > 1e-5) {
            rel_error = fabs((double)dut[i] - ref[i]) / fabs(ref[i]);
        } else {
            rel_error = fabs((double)dut[i] - ref[i]);
        }

        if (rel_error > max_rel_err) {
            printf(
                "Test failed at index %zu: expected %f, got %f. Relative error: %f\n",
                i,
                ref[i],
                (double)dut[i],
                rel_error
            );
            ret = false;
            fail_count++;
        }
    }

    printf("Number of failed elements: %d out of %zu\n", fail_count, size);
    printf(ret ? "------------ PASSED ------------\n" : "------------ NOT passed ------------\n");
    return ret;
}

int main() {
    command_out_t cmd_out;
    current_state_t current;

    for (int i = 0; i < STATE_SIZE; i++) {
        current.state[i] = (fp_t)0.0;
    }
    current.state[0] = (fp_t)0.1;
    current.state[1] = (fp_t)0.1;
    current.state[2] = (fp_t)-0.1;

    printf("================= ADMM SOLVER DDR %d iterations =================\n", ADMM_ITERS);

    ADMM_solver_ddr(current, cmd_out, matrix_blob_words);

    fp_t dut_controls[4];
    double ref_controls[4];

    dut_controls[0] = cmd_out.u0 - (fp_t)U_HOVER;
    dut_controls[1] = cmd_out.u1 - (fp_t)U_HOVER;
    dut_controls[2] = cmd_out.u2 - (fp_t)U_HOVER;
    dut_controls[3] = cmd_out.u3 - (fp_t)U_HOVER;

    for (int i = 0; i < 4; ++i) {
        ref_controls[i] = ADMM_x_after_50_iter[12 + i];
    }

    printf("================= Comparing control outputs =================\n");
    bool ok = compare_vectors(dut_controls, ref_controls, 4, REL_ERROR * 3.0);
    return ok ? 0 : 1;
}
