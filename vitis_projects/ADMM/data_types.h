#ifndef DATA_TYPES_H
#define DATA_TYPES_H

#include <ap_fixed.h>

typedef ap_fixed<32,10, AP_RND, AP_SAT> fp_t;

typedef struct {
    fp_t state[12];
} current_state_t;

typedef struct {
    fp_t u0;
    fp_t u1;
    fp_t u2;
    fp_t u3;
} command_out_t;

#endif // DATA_TYPES_H
