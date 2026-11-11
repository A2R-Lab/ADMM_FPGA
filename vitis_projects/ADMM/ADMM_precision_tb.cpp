#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

#include "ADMM.h"
#include "data.h"
#include "data_types.h"

static const char *getenv_or_default(const char *name, const char *fallback) {
    const char *value = std::getenv(name);
    if (value == nullptr || value[0] == '\0') {
        return fallback;
    }
    return value;
}

int main() {
    const std::string input_path = getenv_or_default("ADMM_PRECISION_INPUT", "precision_inputs.txt");
    const std::string output_path = getenv_or_default("ADMM_PRECISION_OUTPUT", "precision_outputs.txt");

    std::ifstream in(input_path.c_str());
    if (!in) {
        std::cerr << "ERROR: failed to open input file: " << input_path << "\n";
        return 1;
    }

    int samples = 0;
    in >> samples;
    if (!in || samples <= 0) {
        std::cerr << "ERROR: invalid sample count in " << input_path << "\n";
        return 1;
    }

    std::ofstream out(output_path.c_str());
    if (!out) {
        std::cerr << "ERROR: failed to open output file: " << output_path << "\n";
        return 1;
    }

    out << std::setprecision(17);
    out << samples << " " << N_VAR << "\n";

    for (int sample_idx = 0; sample_idx < samples; ++sample_idx) {
        fp_t current_state[12];
        fp_t q_vec[N_VAR];
        fp_t x_out[N_VAR];
        double dynamic_min_d = 0.0;
        double dynamic_max_d = 0.0;

        for (int i = 0; i < 12; ++i) {
            double value = 0.0;
            in >> value;
            if (!in) {
                std::cerr << "ERROR: failed reading state for sample " << sample_idx << "\n";
                return 1;
            }
            current_state[i] = (fp_t)value;
        }

        in >> dynamic_min_d >> dynamic_max_d;
        if (!in) {
            std::cerr << "ERROR: failed reading dynamic bounds for sample " << sample_idx << "\n";
            return 1;
        }

        for (int i = 0; i < N_VAR; ++i) {
            double value = 0.0;
            in >> value;
            if (!in) {
                std::cerr << "ERROR: failed reading q_vec for sample " << sample_idx << "\n";
                return 1;
            }
            q_vec[i] = (fp_t)value;
        }

        ADMM_benchmark_solve(
            current_state,
            q_vec,
            (fp_t)dynamic_min_d,
            (fp_t)dynamic_max_d,
            x_out
        );

        out << sample_idx;
        for (int i = 0; i < N_VAR; ++i) {
            out << " " << (double)x_out[i];
        }
        out << "\n";
    }

    std::cout << "PRECISION_TB samples=" << samples
              << " n_var=" << N_VAR
              << " input=" << input_path
              << " output=" << output_path
              << "\n";

    return 0;
}
