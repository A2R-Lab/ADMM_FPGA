#include "matrix_loader.h"

#include "matrix_layout.h"

void matrix_loader(
    const ap_uint<32> *flash_blob,
    ap_uint<32> *ddr_blob,
    ap_uint<32> word_count,
    ap_uint<32> &checksum_out
) {
    #pragma HLS INTERFACE ap_ctrl_hs port=return
    #pragma HLS INTERFACE ap_none port=word_count
    #pragma HLS INTERFACE ap_vld port=checksum_out
    #pragma HLS INTERFACE m_axi port=flash_blob offset=direct bundle=flash depth=MATRIX_BLOB_TOTAL_WORDS max_read_burst_length=64 num_read_outstanding=16
    #pragma HLS INTERFACE m_axi port=ddr_blob offset=direct bundle=ddr depth=MATRIX_BLOB_TOTAL_WORDS max_write_burst_length=64 num_write_outstanding=16

    ap_uint<32> checksum = 0;

LOAD_LOOP:
    for (ap_uint<32> i = 0; i < word_count; i++) {
        #pragma HLS PIPELINE II=1
        ap_uint<32> word = flash_blob[i];
        ddr_blob[i] = word;
        checksum ^= (word + i);
    }

    checksum_out = checksum;
}
