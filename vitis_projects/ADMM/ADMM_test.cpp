#include <stdio.h>
#include <stdlib.h>

#include "data_types.h"
#include "ADMM.h"
#include "test_data.h"

const double REL_ERROR = .01;

bool compare_vectors(fp_t dut[RANDOM_VECTOR_SIZE], const double ref[RANDOM_VECTOR_SIZE], size_t size, double max_rel_err) {
    bool ret = true;
    double rel_error;
    int fail_count = 0;
    // Check results
    for (int i = 0; i < size; i++) { // i = size - 1; i >= 0; i--) {
        if(fabs(ref[i]) > 1e-5)
            rel_error = fabs(((double)dut[i]) - ref[i]) / ref[i];
        else
            rel_error = fabs(((double)dut[i]) - ref[i]);

        if (rel_error > max_rel_err) {
            printf("Test failed at index %d: expected %f, got %f. Relative error is: %f.\n", i, ref[i], (double)dut[i], rel_error);
            ret = false;
            fail_count++;
        }
        else
        {
            // printf("Test passed at index %d: expected %f, got %f. Relative error is: %f.\n", i, (double)ref[i], (double)dut[i], rel_error);
        }
    }
    printf("Number of failed elements: %d out of %zu\n", fail_count, size);
    printf(ret ? "------------ PASSED ------------\n" : "------------ NOT passed ------------\n");
    return ret;
}

int main() {
    fp_t res_dut[RANDOM_VECTOR_SIZE];
    bool res = true;


    // printf("================= FORWARD SUBSTITUTION =================\n");
    // forward_substitution(random_vector, res_dut);
    // res &= compare_vectors(res_dut, forw_subst_out, RANDOM_VECTOR_SIZE, REL_ERROR * 2);

    // printf("================= BACKWARD SUBSTITUTION =================\n");
    // backward_substitution(random_vector, res_dut);
    // res &= compare_vectors(res_dut, back_subst_out, RANDOM_VECTOR_SIZE, REL_ERROR * 2);

    // printf("================= A MULT =================\n");
    // A_mul(random_vector, res_dut);
    // res &= compare_vectors(res_dut, A_mul_out, RANDOM_VECTOR_SIZE, REL_ERROR);

    // printf("================= AT MULT =================\n");
    // AT_mul(random_vector, res_dut);
    // res &= compare_vectors(res_dut, AT_mul_out, RANDOM_VECTOR_SIZE, REL_ERROR);

    command_out_t cmd_out;
    current_state_t current;
    
    current.state[0] = (fp_t)0.1; current.state[1] = (fp_t)0.1; current.state[2] = (fp_t)-0.1;
    


    printf("================= ADMM SOLVER %d iterations =================\n", ADMM_ITERS);

    ADMM_solver(
        current,
        cmd_out
    );

    // Compare only the four control components against reference
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
    compare_vectors(dut_controls, ref_controls, 4, REL_ERROR);
    
    return 0; // res ? 0 : 1;
}
