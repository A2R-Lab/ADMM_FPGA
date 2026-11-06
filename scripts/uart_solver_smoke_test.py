#!/usr/bin/env python3
"""
Send one 12-state vector over UART to the FPGA ADMM solver and print the raw
and decoded 4-word response.
"""

import argparse
import struct
import sys

import numpy as np
import serial


FRAC_BITS = 22
N_STATE = 12
N_CMD = 4
START_BYTE = 0xFF


def float_to_fixed(value: float) -> int:
    return int(value * (2**FRAC_BITS)) & 0xFFFFFFFF


def fixed_to_float(value: int) -> float:
    if value & 0x80000000:
        value -= 0x100000000
    return float(value) / (2**FRAC_BITS)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", default="/dev/ttyUSB1")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument(
        "--state",
        type=float,
        nargs=N_STATE,
        default=[2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        help="12 state values in solver order: x y z roll pitch yaw vx vy vz wx wy wz",
    )
    p.add_argument("--timeout", type=float, default=5.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    state = np.asarray(args.state, dtype=float)
    if state.shape != (N_STATE,):
        raise ValueError(f"Expected {N_STATE} state values")

    print(f"Opening serial port {args.port} at {args.baud} baud...")
    ser = serial.Serial(
        port=args.port,
        baudrate=args.baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=args.timeout,
    )
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        tx_words = [float_to_fixed(v) for v in state]
        print("TX state floats:", state.tolist())
        print("TX state words :", [f"0x{w:08X}" for w in tx_words])

        ser.write(bytes([START_BYTE]))
        for word in tx_words:
            ser.write(struct.pack("<I", word))

        rx_words = []
        for i in range(N_CMD):
            data = ser.read(4)
            if len(data) != 4:
                print(f"Timed out waiting for command word {i}")
                return 1
            rx_words.append(struct.unpack("<I", data)[0])

        rx_floats = [fixed_to_float(w) for w in rx_words]
        print("RX cmd words   :", [f"0x{w:08X}" for w in rx_words])
        print("RX cmd floats  :", rx_floats)
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    sys.exit(main())
