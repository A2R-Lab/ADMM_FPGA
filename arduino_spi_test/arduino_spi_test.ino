#include <SPI.h>

//--------------------------------------------------------------
// Configuration
//--------------------------------------------------------------
#define CS_PIN          10
#define N_STATE         12      // Number of 24-bit words to send
#define N_RESULT        4       // Number of 24-bit words to receive

// SPI Settings 
// 1MHz is good for validation. Increase later if signal integrity allows.
SPISettings spiSettings(50000000, MSBFIRST, SPI_MODE0);

// Data buffers
uint32_t state_data[N_STATE];
uint32_t result_data[N_RESULT];

//--------------------------------------------------------------
// Setup
//--------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    while (!Serial) {
        ; // Wait for serial port
    }
    
    pinMode(CS_PIN, OUTPUT);
    digitalWrite(CS_PIN, HIGH);
    
    SPI.begin();
    
    delay(100);  // Give FPGA time to initialize
    
    Serial.println("=================================");
    Serial.println("FPGA SPI Communication Test (Fixed 24-bit)");
    Serial.println("=================================");
    Serial.println("Commands:");
    Serial.println("  t - Run test transaction with sample data");
    Serial.println("  z - Run test with zeros");
    Serial.println("  r - Run repeated tests (10x)");
    Serial.println("  h - Show this help");
    Serial.println("=================================");
}

//--------------------------------------------------------------
// Main Loop
//--------------------------------------------------------------
void loop() {
    if (Serial.available() > 0) {
        char cmd = Serial.read();
        
        switch (cmd) {
            case 't':
                runTestTransaction();
                break;
            case 'z':
                runZeroTest();
                break;
            case 'r':
                runRepeatedTests(10);
                break;
            case 'h':
                printHelp();
                break;
            case '\n':
            case '\r':
                break;
            default:
                Serial.print("Unknown command: ");
                Serial.println(cmd);
                break;
        }
    }
}

//--------------------------------------------------------------
// Helper: Send 24-bit Word (3 Bytes)
//--------------------------------------------------------------
static inline void send_val_24bit(uint32_t v) {
    // If you need fixed point (e.g., Q16.8), multiply here:
     uint32_t val = (uint32_t)(v);

    // Send exactly 3 bytes (24 bits)
    SPI.transfer((val >> 0)  & 0xFF);  // LSB
    SPI.transfer((val >> 8)  & 0xFF);
    SPI.transfer((val >> 16) & 0xFF);  // MSB (of the 24-bit word)
}

//--------------------------------------------------------------
// Helper: Receive 24-bit Word (3 Bytes)
//--------------------------------------------------------------
// This is used for words 1 to N. Word 0 is handled specially in the transaction.
static inline uint32_t receive_val_24bit() {
    uint32_t val = 0;
    val |= ((uint32_t)SPI.transfer(0x00)) << 16;
    val |= ((uint32_t)SPI.transfer(0x00)) << 8;
    val |= ((uint32_t)SPI.transfer(0x00)) << 0;
    return val;
}
static inline uint32_t receive_val_24bit_from_buf(const uint8_t* p) {
    return ((uint32_t)p[0] << 16) |
           ((uint32_t)p[1] << 8)  |
           ((uint32_t)p[2] << 0);
}
bool transactWithFPGA(uint32_t* send_vals, uint32_t* recv_vals) {
    unsigned long start_time = micros();
    unsigned long send_done_time;
    unsigned long compute_done_time;

    SPI.beginTransaction(spiSettings);
    digitalWrite(CS_PIN, LOW);

    //----------------------------------------------------------
    // 1. SEND STATE DATA (BUFFERED)
    //----------------------------------------------------------
    const uint32_t TX_LEN = 3 + (3 * N_STATE);
    uint8_t tx_buf[TX_LEN];

    // Start sequence
    tx_buf[0] = 0x00;
    tx_buf[1] = 0x00;
    tx_buf[2] = 0xAA;

    // State words (24-bit, LSB first)
    for (int i = 0; i < N_STATE; i++) {
        uint32_t v = send_vals[i];
        tx_buf[3 + 3*i + 0] = (v >> 0)  & 0xFF;
        tx_buf[3 + 3*i + 1] = (v >> 8)  & 0xFF;
        tx_buf[3 + 3*i + 2] = (v >> 16) & 0xFF;
    }

    // Full buffered transmit
    SPI.transfer(tx_buf, TX_LEN);

    send_done_time = micros();

    //----------------------------------------------------------
    // 2. POLLING (UNCHANGED, BYTE-BY-BYTE)
    //----------------------------------------------------------
    uint8_t first_byte = 0;
    uint32_t poll_count = 0;
    const uint32_t MAX_POLLS = 100000;
    bool ready = false;

    while (poll_count < MAX_POLLS) {
        first_byte = SPI.transfer(0x00);
        poll_count++;

        if (first_byte == 0xFF) {
            ready = true;

            // Maintain exact behavior from your code
            SPI.transfer(0x00);
            SPI.transfer(0x00);
            break;
        }
    }

    compute_done_time = micros();

    if (!ready) {
        digitalWrite(CS_PIN, HIGH);
        SPI.endTransaction();
        Serial.println("ERROR: FPGA timeout - no data received");
        return false;
    }

    //----------------------------------------------------------
    // 3. RECEIVE RESULT DATA (BUFFERED)
    //----------------------------------------------------------
    const uint32_t RX_LEN = 3 * N_RESULT;
    uint8_t rx_buf[RX_LEN];
    memset(rx_buf, 0x00, RX_LEN); // clock SPI by sending 0x00
SPI.transfer(rx_buf, RX_LEN); // rx_buf now contains FPGA response
    
    digitalWrite(CS_PIN, HIGH);
    SPI.endTransaction();
    unsigned long end_time = micros();
    // Clock out all result bytes at once

    // Reassemble 24-bit words
    for (int i = 0; i < N_RESULT; i++) {
        recv_vals[i] = receive_val_24bit_from_buf(&rx_buf[3*i]);
    }

    //----------------------------------------------------------
    // 4. END TRANSACTION
    //----------------------------------------------------------
    

    

    //----------------------------------------------------------
    // TIMING
    //----------------------------------------------------------
    Serial.println("--- Timing ---");
    Serial.print("  Send time:      ");
    Serial.print(send_done_time - start_time);
    Serial.println(" us");

    Serial.print("  Compute+Poll:   ");
    Serial.print(compute_done_time - send_done_time);
    Serial.println(" us");

    Serial.print("  Poll count:     ");
    Serial.println(poll_count);

    Serial.print("  Receive time:   ");
    Serial.print(end_time - compute_done_time);
    Serial.println(" us");

    Serial.print("  Total time:     ");
    Serial.print(end_time - start_time);
    Serial.println(" us");

    return true;
}


//--------------------------------------------------------------
// Test Transactions
//--------------------------------------------------------------
void runTestTransaction() {
    Serial.println("\n========== TEST TRANSACTION ==========");
    
    // Fill with test data
    for (int i = 0; i < N_STATE; i++) {
        state_data[i] = (i + 1); // Simple integers 1, 2, 3...
    }
    
    // Print send data
    Serial.println("Sending state data:");
    for (int i = 0; i < N_STATE; i++) {
        Serial.print("  ["); Serial.print(i); Serial.print("] = ");
        Serial.println(state_data[i], 2);
    }
    
    // Execute transaction
    Serial.println("\nExecuting SPI transaction...");
    bool success = transactWithFPGA(state_data, result_data);
    
    if (success) {
        Serial.println("\nReceived result data:");
        for (int i = 0; i < N_RESULT; i++) {
            Serial.print("  ["); Serial.print(i); Serial.print("] = ");
            Serial.print(result_data[i], 2);
            
            Serial.print("   (Hex: 0x");
            Serial.print((uint32_t)result_data[i], HEX);
            Serial.println(")");
        }
        Serial.println("\nTransaction SUCCESS");
    } else {
        Serial.println("\nTransaction FAILED");
    }
    Serial.println("=======================================\n");
}

void runZeroTest() {
    Serial.println("\n========== ZERO TEST ==========");
    
    // Fill with zeros
    for (int i = 0; i < N_STATE; i++) {
        state_data[i] = 0.0f;
    }
    
    Serial.println("Sending all zeros...");
    bool success = transactWithFPGA(state_data, result_data);
    
    if (success) {
        Serial.println("Received results:");
        for (int i = 0; i < N_RESULT; i++) {
            Serial.print("  ["); Serial.print(i); Serial.print("] = ");
            Serial.println(result_data[i], 2);
        }
        Serial.println("SUCCESS");
    } else {
        Serial.println("FAILED");
    }
    Serial.println("================================\n");
}

void runRepeatedTests(int count) {
    Serial.print("\n========== REPEATED TESTS (");
    Serial.print(count);
    Serial.println("x) ==========");
    
    int successes = 0;
    unsigned long total_time = 0;
    
    for (int t = 0; t < count; t++) {
        // Generate varying test data
        for (int i = 0; i < N_STATE; i++) {
            state_data[i] = (t + i);
        }

        Serial.print("Test "); Serial.print(t + 1); Serial.print("/"); Serial.print(count); Serial.print(": ");
        
        unsigned long t_start = micros();
        bool success = transactWithFPGA(state_data, result_data);
        unsigned long t_end = micros();
        
        if (success) {
            successes++;
            total_time += (t_end - t_start);
            Serial.print("OK - Result[0] = ");
            Serial.println(result_data[0], 0);
        } else {
            Serial.println("FAIL");
        }
    }
    
    Serial.println("\n--- Summary ---");
    Serial.print("Success rate: "); Serial.print(successes); Serial.print("/"); Serial.println(count);
    
    if (successes > 0) {
        Serial.print("Average time: ");
        Serial.print(total_time / successes);
        Serial.println(" us");
    }
    Serial.println("==========================================\n");
}

void printHelp() {
    Serial.println("\n=================================");
    Serial.println("FPGA SPI Communication Test");
    Serial.println("=================================");
    Serial.println("Commands:");
    Serial.println("  t - Run test transaction with sample data");
    Serial.println("  z - Run test with zeros");
    Serial.println("  r - Run repeated tests (10x)");
    Serial.println("  h - Show this help");
    Serial.println("=================================\n");
}
