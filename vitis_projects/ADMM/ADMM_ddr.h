#ifndef ADMM_DDR_H
#define ADMM_DDR_H

#include <ap_int.h>

#include "data_types.h"
#include "matrix_layout.h"
#include "solver_constants.h"

void ADMM_solver_ddr(
    current_state_t current_in,
    command_out_t &command_out,
    const ap_uint<32> *matrix_blob
);

#endif // ADMM_DDR_H
