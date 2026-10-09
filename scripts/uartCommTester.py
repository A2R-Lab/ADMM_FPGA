#!/usr/bin/env python3
"""
UART Communication Script for Forward Substitution Module
Sends b vector and receives x vector results
"""

import serial
import struct
import time
import sys

# Configuration
SERIAL_PORT = '/dev/ttyUSB2'  # Change to COM port on Windows (e.g., 'COM3')
BAUD_RATE = 115200
N = 10  # Number of elements
FRAC_BITS = 16  # Fixed point format 16.16

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
    time.sleep(0.01)
    
    # Send each element as 4 bytes (little-endian)
    for i, val in enumerate(vector):
        fixed_val = float_to_fixed(val)
        # Pack as little-endian unsigned int
        data = struct.pack('<I', fixed_val)
        for byte in data:
            ser.write(bytes([byte]))
            ser.flush()
            time.sleep(0.01)  # Small delay between bytes
        print(f"Sent b[{i}] = {val:10.6f} (0x{fixed_val:08X})")
        time.sleep(0.1)  # Small delay between words

def receive_vector(ser, n):
    """Receive n fixed-point words via UART and convert to floats"""
    results = []
    print("\nWaiting for results...")
    
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
        print(f"Received x[{i}] = {float_val:10.6f} (0x{fixed_val:08X})")
    
    return results

def main():
    # Golden test data
    b_vector = [
        2*0.88933784,
        0.04369664,
        -0.17067613,
        -0.47088876,
        0.54846740,
        -0.08769934,
        0.13686790,
        -0.96242040,
        0.23527099,
        0.22419144
    ]
    
    x_expected = [
        2*0.57420594,
        -0.04983041,
        -0.12166799,
        -0.21711090,
        0.39088538,
        -0.22341508,
        0.10425653,
        -0.47449887,
        0.10435311,
        0.02489335
    ]
    
    try:
        # Open serial port
        print(f"Opening serial port {SERIAL_PORT} at {BAUD_RATE} baud...")
        ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=10  # 10 second timeout
        )
        
        print("Port opened successfully\n")
        time.sleep(0.5)  # Wait for device to be ready
        
        # Clear any pending data
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        # Send input vector
        print("=== Sending Input Vector ===")
        send_vector(ser, b_vector)
        
        # Receive results
        print("\n=== Receiving Results ===")
        x_received = receive_vector(ser, N)
        
        if x_received is None:
            print("\nERROR: Failed to receive complete results")
            ser.close()
            return 1
        
        # Compare results
        print("\n=== Comparison with Expected Results ===")
        print("Index |    Received    |    Expected    |     Error      ")
        print("------|----------------|----------------|----------------")
        
        max_error = 0.0
        errors = 0
        
        for i in range(N):
            error = abs(x_received[i] - x_expected[i])
            max_error = max(max_error, error)
            
            status = "OK" if error < 0.001 else "FAIL"
            print(f"  {i:2d}  | {x_received[i]:13.6f} | {x_expected[i]:13.6f} | "
                  f"{error:13.6f} [{status}]")
            
            if error >= 0.001:
                errors += 1
        
        print(f"\n=== Summary ===")
        print(f"Maximum error: {max_error:.8f}")
        print(f"Failed elements: {errors}/{N}")
        
        if errors == 0:
            print("*** TEST PASSED ***")
        else:
            print("*** TEST FAILED ***")
        
        ser.close()
        print("\nSerial port closed")
        
        return 0 if errors == 0 else 1
        
    except serial.SerialException as e:
        print(f"Serial port error: {e}")
        print(f"\nMake sure the device is connected to {SERIAL_PORT}")
        print("On Linux, you may need: sudo chmod 666 /dev/ttyUSB0")
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
