#include <cmath>
#include <iostream>

#include "ADMM.h"
#include "data.h"
#include "data_types.h"

static bool approx_equal(double a, double b, double tol) {
    return std::fabs(a - b) <= tol;
}

int main() {
    bool ok = true;

    const fp_t t = (fp_t)0.125;
    const fp_t m = admm_test_rho_mul(t);
    const fp_t d = admm_test_rho_div(t);
    const fp_t md = admm_test_rho_div(m);

    const double rho_scale = static_cast<double>(1 << RHO_SHIFT);
    const double exp_m = 0.125 * rho_scale;
    const double exp_d = 0.125 / rho_scale;
    const double exp_md = 0.125;

    constexpr double tol = 1e-6;

    std::cout << "RHO_SHIFT=" << RHO_SHIFT << " rho_scale=" << rho_scale << "\n";
    std::cout << "t  = " << (double)t << "\n";
    std::cout << "m  = " << (double)m << " (expected " << exp_m << ")\n";
    std::cout << "d  = " << (double)d << " (expected " << exp_d << ")\n";
    std::cout << "md = " << (double)md << " (expected " << exp_md << ")\n";

    if (!approx_equal((double)m, exp_m, tol)) {
        std::cerr << "FAIL: rho_mul scaling mismatch\n";
        ok = false;
    }
    if (!approx_equal((double)d, exp_d, tol)) {
        std::cerr << "FAIL: rho_div scaling mismatch\n";
        ok = false;
    }
    if (!approx_equal((double)md, exp_md, tol)) {
        std::cerr << "FAIL: rho_div(rho_mul(t)) mismatch\n";
        ok = false;
    }

    const int fp_w = admm_test_fp_width();
    const int acc_w = admm_test_acc_width();
    std::cout << "fp_t width  = " << fp_w << "\n";
    std::cout << "acc_t width = " << acc_w << "\n";
    std::cout << "guard bits  = " << (acc_w - fp_w) << "\n";

    if (acc_w <= fp_w) {
        std::cerr << "FAIL: accumulator is not wider than fp_t\n";
        ok = false;
    }

    if (ok) {
        std::cout << "PASS: rho scaling and accumulator width checks passed.\n";
        return 0;
    }

    std::cerr << "FAIL: testbench checks failed.\n";
    return 1;
}
