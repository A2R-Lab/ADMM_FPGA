#include "ADMM.h"
#include <fstream>
#include <iostream>
#include <vector>
#include <cstdint>

void baseline_forward_substitution(const fp_t*, bool, int, fp_t*);
void baseline_backward_substitution(const fp_t*, fp_t*);
void baseline_ADMM_iteration(fp_t*, fp_t*, fp_t*, fp_t*, bool, int,
                             fp_t, fp_t, const fp_t*, bool);
void baseline_ADMM_solver(ap_uint<418>, ap_uint<128>&);

static uint32_t seed = 0x13579bdf;
static uint32_t random_bits() {
    seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
    return seed;
}
static fp_t sample(int pattern, int i) {
    static const uint32_t edges[] = {0, 1, 0xffffffff, 0x7fffffff,
        0x80000000, 0x003fffff, 0x00400000, 0xffc00001};
    if (pattern == 0) return (fp_t)0;
    if (pattern == 1) return bits_to_fp(edges[i % 8]);
    if (pattern == 2) return bits_to_fp((i & 1) ? 0x7fffffff : 0x80000000);
    if (pattern == 3) return bits_to_fp((random_bits() & 0x007fffff) - 0x00400000);
    return bits_to_fp(random_bits());
}
static bool equal(const char* name, const fp_t* a, const fp_t* b, int n) {
    for (int i = 0; i < n; ++i) {
        if (fp_to_bits(a[i]) != fp_to_bits(b[i])) {
            std::cerr << name << " mismatch at " << i << ": "
                      << fp_to_bits(a[i]) << " != " << fp_to_bits(b[i]) << '\n';
            return false;
        }
    }
    return true;
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    std::vector<fp_t> rhs(N_VAR), ref(N_VAR), got(N_VAR), q(N_VAR);
    for (int p = 0; p < 8; ++p) {
        for (int i = 0; i < N_VAR; ++i) rhs[i] = sample(p, i);
        baseline_forward_substitution(rhs.data(), false, 0, ref.data());
        forward_substitution(rhs.data(), false, 0, got.data());
        if (!equal("forward", ref.data(), got.data(), N_VAR)) return 1;
        baseline_backward_substitution(rhs.data(), ref.data());
        backward_substitution(rhs.data(), got.data());
        if (!equal("backward", ref.data(), got.data(), N_VAR)) return 1;
#if ADMM_ENABLE_TRAJECTORY
        baseline_forward_substitution(rhs.data(), true, 0, ref.data());
        forward_substitution(rhs.data(), true, 0, got.data());
        if (!equal("trajectory forward", ref.data(), got.data(), N_VAR)) return 1;
#endif
    }
    std::vector<fp_t> xr(N_VAR), br(N_VAR), yr(N_CONSTR);
    std::vector<fp_t> xc(N_VAR), bc(N_VAR), yc(N_CONSTR);
    fp_t state[12];
    for (int p = 0; p < 12; ++p) {
        for (int i = 0; i < 12; ++i) state[i] = sample(p % 5, i);
        for (int i = 0; i < N_VAR; ++i) q[i] = sample(p % 5, i);
        const fp_t lo = (p & 1) ? (fp_t)-0.001 : (fp_t)-2;
        const fp_t hi = (p & 1) ? (fp_t)0.001 : (fp_t)2;
        baseline_ADMM_iteration(xr.data(), br.data(), yr.data(), state,
            false, 0, lo, hi, q.data(), true);
        ADMM_iteration(xc.data(), bc.data(), yc.data(), state,
            false, 0, lo, hi, q.data(), true);
        if (!equal("iteration x", xr.data(), xc.data(), N_VAR) ||
            !equal("iteration b", br.data(), bc.data(), N_VAR) ||
            !equal("iteration y", yr.data(), yc.data(), N_CONSTR)) return 1;
    }
    std::ofstream vectors(argv[1]);
    if (!vectors) return 2;
    vectors << "static const char* shared_l_vectors[][2] = {\n";
    for (int p = 0; p < 8; ++p) {
        current_state_t in = {};
        for (int i = 0; i < 12; ++i) in.state[i] = sample(p % 5, i);
        if (p & 1) in.constraints = (uint32_t(uint16_t(1000)) << 16) | uint16_t(-1000);
        in.traj_cmd = p % 4;
        const ap_uint<418> input = pack_current_state_bits(in);
        ap_uint<128> expected, actual;
        baseline_ADMM_solver(input, expected);
        ADMM_solver(input, actual);
        if (actual != expected) {
            std::cerr << "warm solve mismatch at " << p << '\n'; return 1;
        }
        vectors << "{\"" << input.to_string(16, false) << "\",\""
                << expected.to_string(16, false) << "\"},\n";
    }
    vectors << "};\n";
    std::cout << "PASS: 8 forward/backward cases, 12 full-state iterations, "
                 "8 repeated warm-start solves; raw bits match baseline.\n";
}
