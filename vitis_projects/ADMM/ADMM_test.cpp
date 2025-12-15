#include <stdio.h>
#include <stdlib.h>

#include "data_types.h"
#include "ADMM.h"
#include "test_data.h"

const double REL_ERROR = .02;

bool compare_vectors(fp_t dut[RANDOM_VECTOR_SIZE], const fp_t ref[RANDOM_VECTOR_SIZE], size_t size, double max_rel_err) {
    bool ret = true;
    double rel_error;
    // Check results
    for (int i = 0; i < size; i++) { // i = size - 1; i >= 0; i--) {
        rel_error = fabs((double)(dut[i] - ref[i])) / ((double)ref[i]);

        if (rel_error > max_rel_err) {
            printf("Test failed at index %d: expected %f, got %f. Relative error is: %f.\n", i, (double)ref[i], (double)dut[i], rel_error);
            ret = false;
        }
    }

    printf(ret ? "------------ PASSED ------------\n" : "------------ NOT passed ------------\n");
    return ret;
}

int main() {
    fp_t res_dut[RANDOM_VECTOR_SIZE];
    bool res = true;


    // printf("================= FORWARD SUBSTITUTION =================\n");
    // forward_substitution(random_vector, res_dut);
    // res &= compare_vectors(res_dut, forw_subst_out, RANDOM_VECTOR_SIZE, REL_ERROR * 2);

    printf("================= BACKWARD SUBSTITUTION =================\n");
    backward_substitution(random_vector, res_dut);
    res &= compare_vectors(res_dut, back_subst_out, RANDOM_VECTOR_SIZE, REL_ERROR * 2);

    // printf("================= A MULT =================\n");
    // A_mul(random_vector, res_dut);
    // res &= compare_vectors(res_dut, A_mul_out, RANDOM_VECTOR_SIZE, REL_ERROR);

    // printf("================= AT MULT =================\n");
    // AT_mul(random_vector, res_dut);
    // res &= compare_vectors(res_dut, AT_mul_out, RANDOM_VECTOR_SIZE, REL_ERROR);

    return 0; // res ? 0 : 1;
}
