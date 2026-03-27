#ifndef DATA_TYPES_H
#define DATA_TYPES_H

#include <cstdint>
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

static inline fp_t bits_to_fp(ap_uint<32> bits) {
#if ADMM_USE_FLOAT
    union {
        uint32_t u;
        float f;
    } conv;
    conv.u = (uint32_t)bits;
    return conv.f;
#else
    fp_t v;
    v.range(31, 0) = bits;
    return v;
#endif
}

static inline ap_uint<32> fp_to_bits(fp_t v) {
#if ADMM_USE_FLOAT
    union {
        uint32_t u;
        float f;
    } conv;
    conv.f = v;
    return conv.u;
#else
    return v.range(31, 0);
#endif
}

static inline int fp_bit_width() {
#if ADMM_USE_FLOAT
    return 32;
#else
    return fp_t::width;
#endif
}

#endif // DATA_TYPES_H
