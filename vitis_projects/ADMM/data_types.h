#ifndef DATA_TYPES_H
#define DATA_TYPES_H

#include <ap_int.h>
#include <ap_fixed.h>
#include "admm_runtime_config.h"

#if ADMM_USE_FLOAT
typedef float fp_t;
#else
typedef ap_fixed<32,10, AP_RND, AP_SAT> fp_t;
#endif

typedef struct {
    fp_t state[12];
    ap_uint<2> traj_cmd;
} current_state_t;

typedef struct {
    fp_t u0;
    fp_t u1;
    fp_t u2;
    fp_t u3;
} command_out_t;

#endif // DATA_TYPES_H
