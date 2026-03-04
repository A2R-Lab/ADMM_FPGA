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
    // forward_substitution(random_vector, random_vector, res_dut);
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

    fp_t x[LT_BANDED_ROWS];
    fp_t current_state[12] = {0};
    
    current_state[0] = (fp_t)0.1; current_state[1] = (fp_t)0.1; current_state[2] = (fp_t)-0.1;
    


    printf("================= ADMM SOLVER 100 iterations =================\n");

    ADMM_solver(
        current_state,
        x,
        0
    );
    printf("================= Comparing X =================\n");
    compare_vectors(x, ADMM_x_after_50_iter, LT_BANDED_ROWS, REL_ERROR);
    
    return 0; // res ? 0 : 1;
}
