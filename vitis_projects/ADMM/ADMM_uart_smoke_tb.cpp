#include <cstdio>

#include "ADMM.h"
#include "data_types.h"

static ap_uint<418> pack_current_state(const current_state_t &current) {
    return pack_current_state_bits(current);
}

static command_out_t unpack_command_out(ap_uint<128> bits) {
    command_out_t out = {};
    out.u0 = bits_to_fp(bits.range(31, 0));
    out.u1 = bits_to_fp(bits.range(63, 32));
    out.u2 = bits_to_fp(bits.range(95, 64));
    out.u3 = bits_to_fp(bits.range(127, 96));
    return out;
}

int main() {
    current_state_t current = {};
    ap_uint<128> cmd_out_bits = 0;

    current.state[0] = (fp_t)2.0;
    current.state[1] = (fp_t)0.0;
    current.state[2] = (fp_t)0.0;
    current.state[3] = (fp_t)0.0;
    current.state[4] = (fp_t)0.0;
    current.state[5] = (fp_t)0.0;
    current.state[6] = (fp_t)0.0;
    current.state[7] = (fp_t)0.0;
    current.state[8] = (fp_t)0.0;
    current.state[9] = (fp_t)0.0;
    current.state[10] = (fp_t)0.0;
    current.state[11] = (fp_t)0.0;
    current.constraints = 0;
    current.traj_cmd = 2;

    ADMM_solver(pack_current_state(current), cmd_out_bits);
    command_out_t cmd_out = unpack_command_out(cmd_out_bits);

    std::printf("u0=% .8f\n", (double)cmd_out.u0);
    std::printf("u1=% .8f\n", (double)cmd_out.u1);
    std::printf("u2=% .8f\n", (double)cmd_out.u2);
    std::printf("u3=% .8f\n", (double)cmd_out.u3);
    return 0;
}
