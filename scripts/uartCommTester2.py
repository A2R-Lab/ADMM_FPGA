#!/usr/bin/env python3
"""
UART Communication Script for ADMM Solver Module
Sends current_state vector and receives x vector results
"""

import serial
import struct
import time
import sys
import numpy as np

# Configuration
SERIAL_PORT = '/dev/ttyUSB1'  # Change to COM port on Windows (e.g., 'COM3')
BAUD_RATE = 921600
N_STATE = 12   # Number of state elements
N_VAR = 4    # Number of output variables
FRAC_BITS = 22  # Fixed point format 16.16

def float_to_fixed(f):
    """Convert float to 16.16 fixed point (signed 32-bit)"""
    return int(f * (2 ** FRAC_BITS)) & 0xFFFFFFFF

def fixed_to_float(fx):
    """Convert 16.16 fixed point to float"""
    # Handle sign extension
    if fx & 0x80000000:
        fx = fx - 0x100000000
    return float(fx) / (2 ** FRAC_BITS)

def send_vector(ser, vector):
    """Send vector of floats as fixed-point words via UART"""
    # Send start command
    ser.write(bytes([0xFF]))
    print("Sent start command: 0xFF")
    # time.sleep(0.001)
    
    # Send each element as 4 bytes (little-endian)
    for i, val in enumerate(vector):
        fixed_val = float_to_fixed(val)
        # Pack as little-endian unsigned int
        data = struct.pack('<I', fixed_val)
        for byte in data:
            ser.write(bytes([byte]))
            ser.flush()
            # time.sleep(0.001)  # Small delay between bytes
        print(f"Sent current_state[{i:2d}] = {val:10.6f} (0x{fixed_val:08X})")

def receive_vector(ser, n):
    """Receive n fixed-point words via UART and convert to floats"""
    results = []
    print("\nWaiting for results...")
    print("This may take a while for 332 values...")
    
    for i in range(n):
        # Read 4 bytes
        data = ser.read(4)
        if len(data) < 4:
            print(f"ERROR: Timeout or incomplete data at element {i}")
            return None
        
        # Unpack as little-endian unsigned int
        fixed_val = struct.unpack('<I', data)[0]
        float_val = fixed_to_float(fixed_val)
        results.append(float_val)
        
        # Print progress every 20 elements to avoid spam
        # if i % 20 == 0 or i == n - 1:
        print(f"Received x[{i:3d}] = {float_val:10.6f} (0x{fixed_val:08X})")
    
    return results

def main():
    # Example test data for current_state
    # This represents [x, y, z, vx, vy, vz, roll, pitch, yaw, roll_rate, pitch_rate, yaw_rate]
    # You should replace this with your actual test data
    current_state = [
        0.1,      # x position
        0.1,      # y position
        -0.1,      # z position (hovering at 1m)
        0.0,      # vx
        0.0,      # vy
        0.0,      # vz
        0.0,      # roll
        0.0,      # pitch
        0.0,      # yaw
        0.0,      # roll rate
        0.0,      # pitch rate
        0.0       # yaw rate
    ]
    
    # Verify we have exactly N_STATE elements
    if len(current_state) != N_STATE:
        print(f"ERROR: current_state should have {N_STATE} elements, got {len(current_state)}")
        return 1
    
    try:
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
        
        print("Port opened successfully\n")
        
        # Clear any pending data
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        # Send input vector
        print("=== Sending Current State Vector ===")
        start_time = time.time()
        send_vector(ser, current_state)
        
        # Receive results
        print("\n=== Receiving Results ===")
        print(f"Expecting {N_VAR} values (1328 bytes)...")
        
        x_received = receive_vector(ser, N_VAR)
        
        elapsed_time = time.time() - start_time
        
        if x_received is None:
            print("\nERROR: Failed to receive complete results")
            ser.close()
            return 1
        
        print(f"\nReceived all {N_VAR} values in {elapsed_time:.2f} seconds")
        
        # Display summary statistics
        print("\n=== Results Summary ===")
        x_array = np.array(x_received)
        # print(f"Mean:     {np.mean(x_array):10.6f}")
        # print(f"Std Dev:  {np.std(x_array):10.6f}")
        # print(f"Min:      {np.min(x_array):10.6f}")
        # print(f"Max:      {np.max(x_array):10.6f}")
        
        # Display first and last few values
        print("\nFirst 10 results:")
        for i in range(min(10, len(x_received))):
            print(f"x[{i:3d}] = {x_received[i]:10.6f}")
        
        
        # Save results to file
        output_file = "admm_results.txt"
        with open(output_file, 'w') as f:
            f.write("# ADMM Solver Results\n")
            f.write(f"# Input state: {current_state}\n")
            f.write(f"# Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("\n")
            for i, val in enumerate(x_received):
                f.write(f"{i:3d} {val:15.8f}\n")
        
        print(f"\n*** Results saved to {output_file} ***")
        
        ser.close()
        print("Serial port closed")
        
        return 0
        
    except serial.SerialException as e:
        print(f"Serial port error: {e}")
        print(f"\nMake sure the device is connected to {SERIAL_PORT}")
        print("On Linux, you may need: sudo chmod 666 /dev/ttyUSB2")
        return 1
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
