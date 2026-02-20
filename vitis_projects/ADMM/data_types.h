#ifndef DATA_TYPES_H
#define DATA_TYPES_H

#include <ap_fixed.h>

typedef ap_fixed<32,10, AP_RND, AP_SAT> fp_t;

/* 12 state values as a struct → 12 scalar ports in RTL (no memory interface) */
#define STATE_LEN 12
typedef struct {
    fp_t s[STATE_LEN];
} state_t;

#endif // DATA_TYPES_H
