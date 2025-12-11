#include <iostream>
#include <cstdlib>
#include <ctime>

// #include "forward_300_20.h"
#include "forward_10_3.h"

int main() {
    
    fp_t x_forward[N] = {0};

    // Forward substitution
    forward_substitution(b, x_forward);

    // Print results
    std::cout << "Forward solution:\n";
    for (int i = 0; i < N; i++) std::cout << x_forward[i] << " " << x[i] << std::endl;
    std::cout << std::endl;

    return 0;
}
