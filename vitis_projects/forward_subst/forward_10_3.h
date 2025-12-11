#ifndef L_ROW_H
#define L_ROW_H

#include <ap_fixed.h>

#define N 10
#define MAX_BANDWIDTH 3

typedef ap_fixed<32,16> fp_t;

const fp_t L_row[N][MAX_BANDWIDTH] = {
    { (fp_t)0.00000000, (fp_t)0.00000000, (fp_t)0.64565557 },
    { (fp_t)0.00000000, (fp_t)0.21518937, (fp_t)0.62392241 },
    { (fp_t)0.04488318, (fp_t)-0.07634520, (fp_t)0.60757250 },
    { (fp_t)-0.06241279, (fp_t)0.39177302, (fp_t)0.50925243 },
    { (fp_t)-0.11655848, (fp_t)0.29172504, (fp_t)0.65406722 },
    { (fp_t)0.06804456, (fp_t)0.42559662, (fp_t)0.93367535 },
    { (fp_t)-0.41287071, (fp_t)-0.47978160, (fp_t)0.54566693 },
    { (fp_t)0.27815676, (fp_t)0.37001213, (fp_t)0.50540316 },
    { (fp_t)0.29915857, (fp_t)-0.03852064, (fp_t)0.56163079 },
    { (fp_t)-0.38172558, (fp_t)0.13992102, (fp_t)0.87462026 }
};

// RHS vector b (for reference)
const fp_t b[N] = {
  (fp_t)0.88933784,
  (fp_t)0.04369664,
  (fp_t)-0.17067613,
  (fp_t)-0.47088876,
  (fp_t)0.54846740,
  (fp_t)-0.08769934,
  (fp_t)0.13686790,
  (fp_t)-0.96242040,
  (fp_t)0.23527099,
  (fp_t)0.22419144,
};

// Solution vector x (for reference)
const fp_t x[N] = {
  (fp_t)0.57420594,
  (fp_t)-0.04983041,
  (fp_t)-0.12166799,
  (fp_t)-0.21711090,
  (fp_t)0.39088538,
  (fp_t)-0.22341508,
  (fp_t)0.10425653,
  (fp_t)-0.47449887,
  (fp_t)0.10435311,
  (fp_t)0.02489335,
};



void forward_substitution(const fp_t b[N], fp_t x[N]);
#endif // L_ROW_H
