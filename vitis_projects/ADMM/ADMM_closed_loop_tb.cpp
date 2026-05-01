#include <array>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "ADMM.h"
#include "data.h"
#include "data_types.h"

namespace {

ap_uint<386> pack_current_state(const current_state_t &current) {
    ap_uint<386> bits = 0;
    for (int i = 0; i < 12; ++i) {
        bits.range(i * 32 + 31, i * 32) = fp_to_bits(current.state[i]);
    }
    bits.range(385, 384) = current.traj_cmd;
    return bits;
}

command_out_t unpack_command_out(ap_uint<128> bits) {
    command_out_t out = {};
    out.u0 = bits_to_fp(bits.range(31, 0));
    out.u1 = bits_to_fp(bits.range(63, 32));
    out.u2 = bits_to_fp(bits.range(95, 64));
    out.u3 = bits_to_fp(bits.range(127, 96));
    return out;
}

struct SimConfig {
    double sim_freq = 200.0;
    double sim_duration_s = 10.0;
    int traj_start_step = 0;
    double step_x = 2.0;
    double step_y = 0.0;
    double step_z = 0.0;
    double step_yaw = 0.1;
    double yaw_drift_rate_rad_s = 0.0;
    double motor_time_constant_s = 0.02;
    double mass_scale = 1.03;
    double thrust_scale = 0.97;
    double torque_scale = 1.05;
    double linear_drag_xy = 0.08;
    double linear_drag_z = 0.12;
    double quadratic_drag = 0.03;
    double angular_damping = 1.2e-6;
    double rotor_imbalance = 0.03;
    double control_min = -0.02;
    double control_max = 1.02;
    double max_abs_x = 3.0;
    double max_abs_y = 3.0;
    double max_abs_z = 1.0;
    double max_abs_rp = 0.45;
    double max_abs_rate = 8.0;
    double max_control_step = 0.45;
    double late_check_after_s = -1.0;
    double late_max_abs_x = 0.5;
    double late_max_abs_y = 0.5;
    double late_max_abs_z = 0.5;
    double late_max_control_hover_error = 0.2;
    int fail_on_early_stop = 0;
    std::string traj_path = "trajectory.csv";
};

double getenv_double(const char *name, double default_val) {
    const char *raw = std::getenv(name);
    if (raw == nullptr || raw[0] == '\0') {
        return default_val;
    }
    char *endptr = nullptr;
    const double parsed = std::strtod(raw, &endptr);
    if (endptr == raw) {
        return default_val;
    }
    return parsed;
}

int getenv_int(const char *name, int default_val) {
    const char *raw = std::getenv(name);
    if (raw == nullptr || raw[0] == '\0') {
        return default_val;
    }
    char *endptr = nullptr;
    const long parsed = std::strtol(raw, &endptr, 10);
    if (endptr == raw) {
        return default_val;
    }
    return static_cast<int>(parsed);
}

std::string getenv_string(const char *name, const std::string &default_val) {
    const char *raw = std::getenv(name);
    if (raw == nullptr) {
        return default_val;
    }
    return std::string(raw);
}

SimConfig load_config() {
    SimConfig cfg;
    cfg.sim_freq = getenv_double("ADMM_SIM_FREQ", cfg.sim_freq);
    cfg.sim_duration_s = getenv_double("ADMM_SIM_DURATION_S", cfg.sim_duration_s);
    cfg.traj_start_step = getenv_int("ADMM_TRAJ_START_STEP", cfg.traj_start_step);
    cfg.step_x = getenv_double("ADMM_STEP_X", cfg.step_x);
    cfg.step_y = getenv_double("ADMM_STEP_Y", cfg.step_y);
    cfg.step_z = getenv_double("ADMM_STEP_Z", cfg.step_z);
    cfg.step_yaw = getenv_double("ADMM_STEP_YAW", cfg.step_yaw);
    cfg.yaw_drift_rate_rad_s = getenv_double("ADMM_YAW_DRIFT_RAD_S", cfg.yaw_drift_rate_rad_s);
    cfg.motor_time_constant_s = getenv_double("ADMM_MOTOR_TAU_S", cfg.motor_time_constant_s);
    cfg.mass_scale = getenv_double("ADMM_MASS_SCALE", cfg.mass_scale);
    cfg.thrust_scale = getenv_double("ADMM_THRUST_SCALE", cfg.thrust_scale);
    cfg.torque_scale = getenv_double("ADMM_TORQUE_SCALE", cfg.torque_scale);
    cfg.linear_drag_xy = getenv_double("ADMM_LINEAR_DRAG_XY", cfg.linear_drag_xy);
    cfg.linear_drag_z = getenv_double("ADMM_LINEAR_DRAG_Z", cfg.linear_drag_z);
    cfg.quadratic_drag = getenv_double("ADMM_QUADRATIC_DRAG", cfg.quadratic_drag);
    cfg.angular_damping = getenv_double("ADMM_ANGULAR_DAMPING", cfg.angular_damping);
    cfg.rotor_imbalance = getenv_double("ADMM_ROTOR_IMBALANCE", cfg.rotor_imbalance);
    cfg.control_min = getenv_double("ADMM_CONTROL_MIN", cfg.control_min);
    cfg.control_max = getenv_double("ADMM_CONTROL_MAX", cfg.control_max);
    cfg.max_abs_x = getenv_double("ADMM_MAX_ABS_X", cfg.max_abs_x);
    cfg.max_abs_y = getenv_double("ADMM_MAX_ABS_Y", cfg.max_abs_y);
    cfg.max_abs_z = getenv_double("ADMM_MAX_ABS_Z", cfg.max_abs_z);
    cfg.max_abs_rp = getenv_double("ADMM_MAX_ABS_RP", cfg.max_abs_rp);
    cfg.max_abs_rate = getenv_double("ADMM_MAX_ABS_RATE", cfg.max_abs_rate);
    cfg.max_control_step = getenv_double("ADMM_MAX_CONTROL_STEP", cfg.max_control_step);
    cfg.late_check_after_s = getenv_double("ADMM_LATE_CHECK_AFTER_S", cfg.late_check_after_s);
    cfg.late_max_abs_x = getenv_double("ADMM_LATE_MAX_ABS_X", cfg.late_max_abs_x);
    cfg.late_max_abs_y = getenv_double("ADMM_LATE_MAX_ABS_Y", cfg.late_max_abs_y);
    cfg.late_max_abs_z = getenv_double("ADMM_LATE_MAX_ABS_Z", cfg.late_max_abs_z);
    cfg.late_max_control_hover_error = getenv_double("ADMM_LATE_MAX_CONTROL_HOVER_ERROR", cfg.late_max_control_hover_error);
    cfg.fail_on_early_stop = getenv_int("ADMM_FAIL_ON_EARLY_STOP", cfg.fail_on_early_stop);
    cfg.traj_path = getenv_string("ADMM_CSIM_TRAJ_PATH", cfg.traj_path);
    return cfg;
}

double clamp(double v, double lo, double hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

std::array<double, 3> cross3(const std::array<double, 3> &a, const std::array<double, 3> &b) {
    return {
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    };
}

double norm4(const std::array<double, 4> &q) {
    return std::sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
}

std::array<double, 4> rptoq(const std::array<double, 3> &phi) {
    const double phi_sq = phi[0] * phi[0] + phi[1] * phi[1] + phi[2] * phi[2];
    const double scale = 1.0 / std::sqrt(1.0 + phi_sq);
    return {scale, scale * phi[0], scale * phi[1], scale * phi[2]};
}

std::array<double, 3> qtorp(const std::array<double, 4> &q) {
    return {q[1] / q[0], q[2] / q[0], q[3] / q[0]};
}

void quat_to_rotmat(const std::array<double, 4> &q_in, double R[3][3]) {
    std::array<double, 4> q = q_in;
    const double n = norm4(q);
    if (n > 0.0) {
        q[0] /= n;
        q[1] /= n;
        q[2] /= n;
        q[3] /= n;
    }
    const double w = q[0];
    const double x = q[1];
    const double y = q[2];
    const double z = q[3];

    R[0][0] = 1.0 - 2.0 * (y * y + z * z);
    R[0][1] = 2.0 * (x * y - w * z);
    R[0][2] = 2.0 * (x * z + w * y);
    R[1][0] = 2.0 * (x * y + w * z);
    R[1][1] = 1.0 - 2.0 * (x * x + z * z);
    R[1][2] = 2.0 * (y * z - w * x);
    R[2][0] = 2.0 * (x * z - w * y);
    R[2][1] = 2.0 * (y * z + w * x);
    R[2][2] = 1.0 - 2.0 * (x * x + y * y);
}

std::array<double, 13> dynamics13(
    const std::array<double, 13> &x,
    const std::array<double, 4> &u,
    const SimConfig &cfg,
    const std::array<double, 4> &motor_gains
) {
    constexpr double mass = 0.048;
    constexpr double Jx = 2.3951e-5;
    constexpr double Jy = 2.3951e-5;
    constexpr double Jz = 3.2347e-5;
    constexpr double g = 9.81;
    constexpr double thrust_to_torque = 0.002078;
    constexpr double el = 0.0353;
    constexpr double scale = 65535.0;
    const double mass_eff = mass * cfg.mass_scale;
    const double kt = (2.90e-6 * scale) * cfg.thrust_scale;
    const double km = (kt * thrust_to_torque) * cfg.torque_scale;

    std::array<double, 13> dx = {};
    const std::array<double, 4> q = {x[3], x[4], x[5], x[6]};
    const std::array<double, 3> omg = {x[10], x[11], x[12]};
    const std::array<double, 4> u_eff = {
        clamp(u[0], 0.0, 1.0) * motor_gains[0],
        clamp(u[1], 0.0, 1.0) * motor_gains[1],
        clamp(u[2], 0.0, 1.0) * motor_gains[2],
        clamp(u[3], 0.0, 1.0) * motor_gains[3],
    };

    dx[0] = x[7];
    dx[1] = x[8];
    dx[2] = x[9];

    dx[3] = 0.5 * (-q[1] * omg[0] - q[2] * omg[1] - q[3] * omg[2]);
    dx[4] = 0.5 * (q[0] * omg[0] + q[2] * omg[2] - q[3] * omg[1]);
    dx[5] = 0.5 * (q[0] * omg[1] + q[3] * omg[0] - q[1] * omg[2]);
    dx[6] = 0.5 * (q[0] * omg[2] + q[1] * omg[1] - q[2] * omg[0]);

    double Q[3][3];
    quat_to_rotmat(q, Q);
    const std::array<double, 3> vel = {x[7], x[8], x[9]};
    const double speed = std::sqrt(vel[0] * vel[0] + vel[1] * vel[1] + vel[2] * vel[2]);
    const double thrust_sum = kt * (u_eff[0] + u_eff[1] + u_eff[2] + u_eff[3]);
    const std::array<double, 3> drag_acc = {
        -(cfg.linear_drag_xy * vel[0] + cfg.quadratic_drag * speed * vel[0]) / mass_eff,
        -(cfg.linear_drag_xy * vel[1] + cfg.quadratic_drag * speed * vel[1]) / mass_eff,
        -(cfg.linear_drag_z * vel[2] + cfg.quadratic_drag * speed * vel[2]) / mass_eff,
    };
    dx[7] = (Q[0][2] * thrust_sum) / mass_eff + drag_acc[0];
    dx[8] = (Q[1][2] * thrust_sum) / mass_eff + drag_acc[1];
    dx[9] = -g + (Q[2][2] * thrust_sum) / mass_eff + drag_acc[2];

    const std::array<double, 3> Jw = {Jx * omg[0], Jy * omg[1], Jz * omg[2]};
    const std::array<double, 3> cross_w_Jw = cross3(omg, Jw);
    const std::array<double, 3> tau = {
        (-el * kt * u_eff[0]) + (-el * kt * u_eff[1]) + (el * kt * u_eff[2]) + (el * kt * u_eff[3]),
        (-el * kt * u_eff[0]) + (el * kt * u_eff[1]) + (el * kt * u_eff[2]) + (-el * kt * u_eff[3]),
        (-km * u_eff[0]) + (km * u_eff[1]) + (-km * u_eff[2]) + (km * u_eff[3]),
    };

    dx[10] = (-cross_w_Jw[0] + tau[0] - cfg.angular_damping * omg[0]) / Jx;
    dx[11] = (-cross_w_Jw[1] + tau[1] - cfg.angular_damping * omg[1]) / Jy;
    dx[12] = (-cross_w_Jw[2] + tau[2] - cfg.angular_damping * omg[2]) / Jz;

    return dx;
}

std::array<double, 13> rk4_step(
    const std::array<double, 13> &x,
    const std::array<double, 4> &u,
    double dt,
    const SimConfig &cfg,
    const std::array<double, 4> &motor_gains
) {
    const auto f1 = dynamics13(x, u, cfg, motor_gains);

    std::array<double, 13> x2 = {};
    for (int i = 0; i < 13; ++i) x2[i] = x[i] + 0.5 * dt * f1[i];
    const auto f2 = dynamics13(x2, u, cfg, motor_gains);

    std::array<double, 13> x3 = {};
    for (int i = 0; i < 13; ++i) x3[i] = x[i] + 0.5 * dt * f2[i];
    const auto f3 = dynamics13(x3, u, cfg, motor_gains);

    std::array<double, 13> x4 = {};
    for (int i = 0; i < 13; ++i) x4[i] = x[i] + dt * f3[i];
    const auto f4 = dynamics13(x4, u, cfg, motor_gains);

    std::array<double, 13> xn = {};
    for (int i = 0; i < 13; ++i) {
        xn[i] = x[i] + (dt / 6.0) * (f1[i] + 2.0 * f2[i] + 2.0 * f3[i] + f4[i]);
    }

    std::array<double, 4> qn = {xn[3], xn[4], xn[5], xn[6]};
    const double qn_norm = norm4(qn);
    if (qn_norm > 0.0) {
        xn[3] /= qn_norm;
        xn[4] /= qn_norm;
        xn[5] /= qn_norm;
        xn[6] /= qn_norm;
    }
    return xn;
}

std::array<double, 12> step12(
    const std::array<double, 12> &x12,
    const std::array<double, 4> &u,
    double dt,
    const SimConfig &cfg,
    const std::array<double, 4> &motor_gains
) {
    std::array<double, 13> x13 = {};
    const std::array<double, 3> rp = {x12[3], x12[4], x12[5]};
    const std::array<double, 4> q = rptoq(rp);

    x13[0] = x12[0];
    x13[1] = x12[1];
    x13[2] = x12[2];
    x13[3] = q[0];
    x13[4] = q[1];
    x13[5] = q[2];
    x13[6] = q[3];
    x13[7] = x12[6];
    x13[8] = x12[7];
    x13[9] = x12[8];
    x13[10] = x12[9];
    x13[11] = x12[10];
    x13[12] = x12[11];

    const std::array<double, 13> xn = rk4_step(x13, u, dt, cfg, motor_gains);
    const std::array<double, 4> qn = {xn[3], xn[4], xn[5], xn[6]};
    const std::array<double, 3> rpn = qtorp(qn);

    std::array<double, 12> out = {};
    out[0] = xn[0];
    out[1] = xn[1];
    out[2] = xn[2];
    out[3] = rpn[0];
    out[4] = rpn[1];
    out[5] = rpn[2];
    out[6] = xn[7];
    out[7] = xn[8];
    out[8] = xn[9];
    out[9] = xn[10];
    out[10] = xn[11];
    out[11] = xn[12];
    return out;
}

void write_traj_csv(
    const std::string &path,
    const std::vector<double> &t,
    const std::vector<std::array<double, 12>> &x_hist,
    const std::vector<std::array<double, 4>> &u_hist,
    const std::vector<double> &primal_res_hist,
    const std::vector<double> &dual_res_hist
) {
    std::ofstream f(path);
    if (!f.is_open()) {
        std::cerr << "Failed to open trajectory file: " << path << "\n";
        std::exit(2);
    }
    f << "t";
    for (int i = 0; i < 12; ++i) f << ",x" << i;
    for (int i = 0; i < 4; ++i) f << ",u" << i;
    f << ",primal_residual,dual_residual";
    f << "\n";
    for (size_t i = 0; i < t.size(); ++i) {
        f << t[i];
        for (int k = 0; k < 12; ++k) f << "," << x_hist[i][k];
        for (int k = 0; k < 4; ++k) f << "," << u_hist[i][k];
        f << "," << primal_res_hist[i];
        f << "," << dual_res_hist[i];
        f << "\n";
    }
}

}  // namespace

int main() {
    const SimConfig cfg = load_config();
    if (cfg.sim_freq <= 0.0 || cfg.sim_duration_s <= 0.0) {
        std::cerr << "Invalid simulation config (sim_freq/duration).\n";
        return 1;
    }
    std::cerr << "Yaw drift rate (rad/s): " << cfg.yaw_drift_rate_rad_s << "\n";
    std::cerr << "Plant realism: tau=" << cfg.motor_time_constant_s
              << " mass_scale=" << cfg.mass_scale
              << " thrust_scale=" << cfg.thrust_scale
              << " torque_scale=" << cfg.torque_scale
              << " drag_xy=" << cfg.linear_drag_xy
              << " drag_z=" << cfg.linear_drag_z
              << " drag_quad=" << cfg.quadratic_drag
              << " ang_damp=" << cfg.angular_damping
              << " rotor_imbalance=" << cfg.rotor_imbalance << "\n";
    const double dt = 1.0 / cfg.sim_freq;
    const int sim_steps = static_cast<int>(std::llround(cfg.sim_duration_s * cfg.sim_freq));

    constexpr int kStateSize = 12;
    constexpr int kInputSize = 4;
    constexpr int kInputOffset = STATE_SIZE;  // x = [x0(12), u0(4), x1(12), ...]
    const double kUHover = static_cast<double>(U_HOVER);

    std::array<double, 12> state = {};
    state[0] = cfg.step_x;
    state[1] = cfg.step_y;
    state[2] = cfg.step_z;
    state[5] = cfg.step_yaw;
    std::array<double, 4> control = {kUHover, kUHover, kUHover, kUHover};
    std::array<double, 4> prev_control = control;
    std::array<double, 4> actuator = control;
    const std::array<double, 4> motor_gains = {
        1.0 - cfg.rotor_imbalance,
        1.0 + cfg.rotor_imbalance,
        1.0 - 0.5 * cfg.rotor_imbalance,
        1.0 + 0.5 * cfg.rotor_imbalance,
    };
    std::vector<double> t_hist;
    std::vector<std::array<double, 12>> x_hist;
    std::vector<std::array<double, 4>> u_hist;
    std::vector<double> primal_res_hist;
    std::vector<double> dual_res_hist;
    t_hist.reserve(static_cast<size_t>(sim_steps) + 1);
    x_hist.reserve(static_cast<size_t>(sim_steps) + 1);
    u_hist.reserve(static_cast<size_t>(sim_steps) + 1);
    primal_res_hist.reserve(static_cast<size_t>(sim_steps) + 1);
    dual_res_hist.reserve(static_cast<size_t>(sim_steps) + 1);

    t_hist.push_back(0.0);
    x_hist.push_back(state);
    u_hist.push_back(control);
    primal_res_hist.push_back(0.0);
    dual_res_hist.push_back(0.0);

    bool terminated_early = false;
    std::string terminate_reason = "completed";
    int terminate_step = -1;

    for (int step = 0; step < sim_steps; ++step) {
        current_state_t current_state = {};
        for (int i = 0; i < kStateSize; ++i) {
            current_state.state[i] = static_cast<fp_t>(state[i]);
        }
        current_state.traj_cmd = 0;
        if (step == 0) {
            current_state.traj_cmd[1] = 1;
        }
        if (step == cfg.traj_start_step) {
            current_state.traj_cmd[0] = 1;
        }

        ap_uint<128> cmd_out_bits = 0;
        const double primal_residual_fp = 0.0;
        const double dual_residual_fp = 0.0;
        ADMM_solver(pack_current_state(current_state), cmd_out_bits);
        command_out_t cmd_out = unpack_command_out(cmd_out_bits);
        control[0] = static_cast<double>(cmd_out.u0);
        control[1] = static_cast<double>(cmd_out.u1);
        control[2] = static_cast<double>(cmd_out.u2);
        control[3] = static_cast<double>(cmd_out.u3);

        const double t_now = (step + 1) * dt;
        for (int i = 0; i < kInputSize; ++i) {
            if (!std::isfinite(control[i])) {
                terminated_early = true;
                terminate_reason = "control_non_finite";
                terminate_step = step;
                break;
            }
            if (control[i] < cfg.control_min || control[i] > cfg.control_max) {
                terminated_early = true;
                terminate_reason = "control_out_of_bounds";
                terminate_step = step;
                break;
            }
            if (std::abs(control[i] - prev_control[i]) > cfg.max_control_step) {
                terminated_early = true;
                terminate_reason = "control_step_too_large";
                terminate_step = step;
                break;
            }
        }
        if (terminated_early) {
            break;
        }
        prev_control = control;

        if (cfg.late_check_after_s >= 0.0 && t_now >= cfg.late_check_after_s) {
            for (int i = 0; i < kInputSize; ++i) {
                if (std::abs(control[i] - kUHover) > cfg.late_max_control_hover_error) {
                    terminated_early = true;
                    terminate_reason = "late_control_far_from_hover";
                    terminate_step = step;
                    break;
                }
            }
            if (terminated_early) {
                break;
            }
        }

        const double tau = cfg.motor_time_constant_s;
        const double alpha = (tau > 0.0) ? (dt / (tau + dt)) : 1.0;
        for (int i = 0; i < kInputSize; ++i) {
            actuator[i] = clamp(actuator[i] + alpha * (control[i] - actuator[i]), 0.0, 1.0);
        }

        state = step12(state, actuator, dt, cfg, motor_gains);
        // Inject a slow yaw drift disturbance for tuning.
        state[5] += cfg.yaw_drift_rate_rad_s * dt;

        for (int i = 0; i < kStateSize; ++i) {
            if (!std::isfinite(state[i])) {
                terminated_early = true;
                terminate_reason = "state_non_finite";
                terminate_step = step + 1;
                break;
            }
        }
        if (terminated_early) {
            break;
        }

        t_hist.push_back((step + 1) * dt);
        x_hist.push_back(state);
        u_hist.push_back(actuator);
        primal_res_hist.push_back(primal_residual_fp);
        dual_res_hist.push_back(dual_residual_fp);

        if (std::abs(state[0]) > cfg.max_abs_x || std::abs(state[1]) > cfg.max_abs_y ||
            std::abs(state[2]) > cfg.max_abs_z) {
            terminated_early = true;
            terminate_reason = "position_diverged";
            terminate_step = step + 1;
            break;
        }
        if (std::abs(state[3]) > cfg.max_abs_rp || std::abs(state[4]) > cfg.max_abs_rp ||
            std::abs(state[9]) > cfg.max_abs_rate || std::abs(state[10]) > cfg.max_abs_rate ||
            std::abs(state[11]) > cfg.max_abs_rate) {
            terminated_early = true;
            terminate_reason = "attitude_or_rate_diverged";
            terminate_step = step + 1;
            break;
        }
        if (cfg.late_check_after_s >= 0.0 && t_now >= cfg.late_check_after_s &&
            (std::abs(state[0]) > cfg.late_max_abs_x ||
             std::abs(state[1]) > cfg.late_max_abs_y ||
             std::abs(state[2]) > cfg.late_max_abs_z)) {
            terminated_early = true;
            terminate_reason = "late_position_error_too_large";
            terminate_step = step + 1;
            break;
        }
        if(step % 10 == 0)
         std::cout << step << "/" << sim_steps << std::endl;
    }

    write_traj_csv(cfg.traj_path, t_hist, x_hist, u_hist, primal_res_hist, dual_res_hist);
    if (terminated_early) {
        std::cerr << "EARLY_STOP step=" << terminate_step << " reason=" << terminate_reason << "\n";
        return cfg.fail_on_early_stop ? 1 : 0;
    } else {
        std::cerr << "EARLY_STOP step=-1 reason=completed\n";
    }
    return 0;
}
