#ifndef DATA_TYPES_H
#define DATA_TYPES_H

#include <ap_fixed.h>
#include "admm_runtime_config.h"

#if ADMM_USE_FLOAT
typedef float fp_t;
#else
typedef ap_fixed<32,10, AP_RND, AP_SAT> fp_t;
#endif

#endif // DATA_TYPES_H
