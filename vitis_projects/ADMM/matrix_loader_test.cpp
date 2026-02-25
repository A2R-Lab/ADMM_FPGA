#include <stdio.h>

#include "matrix_blob_sim.h"
#include "matrix_loader.h"

int main() {
    static ap_uint<32> flash_mem[MATRIX_BLOB_TOTAL_WORDS];
    static ap_uint<32> ddr_mem[MATRIX_BLOB_TOTAL_WORDS];

    for (int i = 0; i < MATRIX_BLOB_TOTAL_WORDS; i++) {
        flash_mem[i] = matrix_blob_words[i];
        ddr_mem[i] = 0;
    }

    ap_uint<32> checksum = 0;
    matrix_loader(flash_mem, ddr_mem, MATRIX_BLOB_TOTAL_WORDS, checksum);

    ap_uint<32> expected_checksum = 0;
    int mismatches = 0;

    for (int i = 0; i < MATRIX_BLOB_TOTAL_WORDS; i++) {
        expected_checksum ^= (flash_mem[i] + (ap_uint<32>)i);
        if (ddr_mem[i] != flash_mem[i]) {
            mismatches++;
            if (mismatches < 8) {
                printf("Mismatch at word %d: expected 0x%08X got 0x%08X\n", i, (unsigned)flash_mem[i], (unsigned)ddr_mem[i]);
            }
        }
    }

    if (checksum != expected_checksum) {
        printf("Checksum mismatch: expected 0x%08X got 0x%08X\n", (unsigned)expected_checksum, (unsigned)checksum);
        return 1;
    }

    if (mismatches != 0) {
        printf("Loader copy failed with %d mismatches\n", mismatches);
        return 1;
    }

    printf("Loader test passed: %d words copied, checksum 0x%08X\n", MATRIX_BLOB_TOTAL_WORDS, (unsigned)checksum);
    return 0;
}
