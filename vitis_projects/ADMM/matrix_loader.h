#ifndef MATRIX_LOADER_H
#define MATRIX_LOADER_H

#include <ap_int.h>

void matrix_loader(
    const ap_uint<32> *flash_blob,
    ap_uint<32> *ddr_blob,
    ap_uint<32> word_count,
    ap_uint<32> &checksum_out
);

#endif // MATRIX_LOADER_H
