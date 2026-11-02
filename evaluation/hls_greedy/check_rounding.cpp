// Compile only for raw/split variants, which define row_feedback in ADMM.cpp.
#include "ADMM.cpp"
#include <cstdio>

int main() {
    uint64_t seed = 0x123456789abcdefULL;
    auto next = [&]() { seed ^= seed << 13; seed ^= seed >> 7; seed ^= seed << 17; return seed; };
    const int64_t edge[] = {0, 1, -1, 2097152, -2097152, 2147483647LL, -2147483648LL,
                           549755813887LL, -549755813888LL};
    for (int i = 0; i < 12000; ++i) {
        fp_t b, q, d;
        acc_t sum;
        b.range(31, 0) = i < 81 ? edge[i % 9] : next();
        q.range(31, 0) = i < 81 ? 0 : next();
        d.range(31, 0) = i < 81 ? edge[i / 9] : next();
        sum.range(39, 0) = i < 81 ? edge[i % 9] : next();
        acc_t original = ((acc_t)b - (acc_t)q - sum) * (acc_t)d;
        fp_t expected = (fp_t)original;
        fp_t actual = row_feedback(b, q, sum, d);
        if (fp_to_bits(expected) != fp_to_bits(actual)) {
            std::printf("Mismatch at case %d\n", i);
            return 1;
        }
    }
    std::puts("12000 exact rounding/saturation cases passed");
}
