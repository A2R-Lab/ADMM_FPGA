#!/usr/bin/env python3
"""
UART Communication Script for ADMM Solver Module
Sends initial_state vector and receives x vector results
"""

import serial
import struct
import time
import sys
import numpy as np
import matplotlib.pyplot as plt

from crazyloihimodel import CrazyLoihiModel

# Configuration
SERIAL_PORT = '/dev/ttyUSB1'  # Change to COM port on Windows (e.g., 'COM3')
BAUD_RATE = 921600
N_STATE = 12   # Number of state elements
N_VAR = 4    # Number of output variables

def float_to_word(f):
    """Convert Python float to IEEE754 float32 raw bytes (little-endian)."""
    return struct.pack('<f', float(f))

def word_to_float(data):
    """Convert 4 raw bytes (little-endian IEEE754 float32) to Python float."""
    return struct.unpack('<f', data)[0]

def send_vector(ser, vector):
    """Send vector of floats as float32 words via UART."""
    # Send start command
    ser.write(bytes([0xFF]))
    
    # Send each element as 4 bytes (little-endian float32)
    for i, val in enumerate(vector):
        data = float_to_word(val)
        for byte in data:
            ser.write(bytes([byte]))
            ser.flush()
        # print(f"Sent initial_state[{i:2d}] = {val:10.6f}")

def receive_vector(ser, n):
    """Receive n float32 words via UART and convert to floats."""
    results = []
    # print("\nWaiting for results...")
    # print("This may take a while for 332 values...")
    
    for i in range(n):
        # Read 4 bytes
        data = ser.read(4)
        if len(data) < 4:
            print(f"ERROR: Timeout or incomplete data at element {i}")
            return None
        
        float_val = word_to_float(data)
        results.append(float_val)
        
        # Print progress every 20 elements to avoid spam
        # if i % 20 == 0 or i == n - 1:
        # print(f"Received x[{i:3d}] = {float_val:10.6f}")
    
    return results

def get_control(ser, state):
    send_vector(ser, state)
    x_received = receive_vector(ser, N_VAR)
    
    control = np.array(x_received)
    print("Received control:", control)
    return control

def main():
    # Open serial port
    print(f"Opening serial port {SERIAL_PORT} at {BAUD_RATE} baud...")
    ser = serial.Serial(
        port=SERIAL_PORT,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=30  # 30 second timeout (increased for large data)
    )
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    model = CrazyLoihiModel(freq=200)

    state = np.zeros(model.nx)
    state[0] = 2.0
    state[1] = 0
    state[2] = 0
    control = np.copy(model.hover_thrust)
    print("Initial control:", control)
    print("Initial state:", state)

    state_hist = []
    control_hist = []

    state_hist.append(state.copy())
    control_hist.append(control.copy())


    dt = 1.0 / model.freq
    T = 10 * model.freq  # total time steps

    for i in range(T):
        print(f"\n=== Time step {i+1}/{T} ===")
        control = get_control(ser, state) #+ model.hover_thrust
        state = model.step(state, control)
        print("Next state:", state)
        state_hist.append(state.copy())
        control_hist.append(control.copy())
    
    state_hist = np.array(state_hist)      # shape: (T+1, nx)
    control_hist = np.array(control_hist)  # shape: (T+1, nu)
    time = np.arange(T + 1) * dt

    # state_labels = [
    #     "x", "y", "z",
    #     "roll", "pitch", "yaw",
    #     "vx", "vy", "vz",
    #     "wx", "wy", "wz"
    # ]

    # fig, axs = plt.subplots(4, 3, figsize=(14, 10), sharex=True)
    # axs = axs.flatten()

    # for i in range(state_hist.shape[1]):
    #     axs[i].plot(time, state_hist[:, i])
    #     axs[i].set_title(state_labels[i])
    #     axs[i].grid(True)

    # axs[-1].set_xlabel("Time [s]")
    # plt.tight_layout()
    # plt.show()


    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 0.7], hspace=0.3)

    # --- Position ---
    ax_pos = fig.add_subplot(gs[0, 0])
    ax_pos.plot(time, state_hist[:, 0:3])
    ax_pos.set_title("Position [x y z]")
    ax_pos.set_ylabel("m")
    ax_pos.legend(["x", "y", "z"])
    ax_pos.grid(True)

    # --- Orientation ---
    ax_att = fig.add_subplot(gs[0, 1])
    ax_att.plot(time, state_hist[:, 3:6])
    ax_att.set_title("Orientation [roll pitch yaw]")
    ax_att.set_ylabel("rad")
    ax_att.legend(["roll", "pitch", "yaw"])
    ax_att.grid(True)

    # --- Linear Velocity ---
    ax_vel = fig.add_subplot(gs[1, 0])
    ax_vel.plot(time, state_hist[:, 6:9])
    ax_vel.set_title("Linear Velocity")
    ax_vel.set_ylabel("m/s")
    ax_vel.legend(["vx", "vy", "vz"])
    ax_vel.grid(True)

    # --- Angular Velocity ---
    ax_angvel = fig.add_subplot(gs[1, 1])
    ax_angvel.plot(time, state_hist[:, 9:12])
    ax_angvel.set_title("Angular Velocity")
    ax_angvel.set_ylabel("rad/s")
    ax_angvel.legend(["wx", "wy", "wz"])
    ax_angvel.grid(True)

    # --- Controls (full-width) ---
    ax_u = fig.add_subplot(gs[2, :])
    ax_u.plot(time, control_hist)
    ax_u.set_title("Control Inputs")
    ax_u.set_xlabel("Time [s]")
    ax_u.set_ylabel("Control")
    ax_u.legend([f"u{i}" for i in range(control_hist.shape[1])])
    ax_u.grid(True)

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
