`timescale 1ns/1ps

module top_spi_2 (
    input  wire       clk,
    input  wire       resetn,
    // SPI Interface
    input  wire       spi_sck,
    input  wire       spi_mosi,
    output wire       spi_miso,
    input  wire       spi_cs_n,
    
    output wire [3:0] led
);

    //--------------------------------------------------------------
    // Parameters
    //--------------------------------------------------------------
    localparam N_STATE    = 12;
    localparam N_VAR      = 332;
    localparam DATA_WIDTH = 32;
    localparam FIXED_ITERS = 32'd10;
    
    localparam STATE_LOG = $clog2(N_STATE);
    localparam VAR_LOG   = $clog2(N_VAR);
    
    // FSM States
    localparam IDLE          = 3'd0;
    localparam RX_DATA       = 3'd1;
    localparam COMPUTE       = 3'd2;
    localparam WAIT_FOR_POLL = 3'd3; // New: Wait for Master to start polling
    localparam TX_DATA       = 3'd4;
    localparam DONE          = 3'd5;

    //--------------------------------------------------------------
    // SPI Signals
    //--------------------------------------------------------------
    wire [7:0] spi_rx_byte;
    wire       spi_rx_dv;
    reg  [7:0] spi_tx_byte;
    reg        spi_tx_dv;
    
    //--------------------------------------------------------------
    // FSM and Control Signals
    //--------------------------------------------------------------
    reg [2:0]  state;
    reg [1:0]  rx_byte_count;   // 0-3 for 32-bit words
    reg [5:0]  rx_word_count;   // 0 to N_STATE-1
    reg [1:0]  tx_byte_count;   // 0-3 for 32-bit words
    reg [9:0]  tx_word_count;   // 0 to N_VAR-1
    reg [31:0] rx_word_buffer;
    
    //--------------------------------------------------------------
    // HLS Module Signals
    //--------------------------------------------------------------
    reg ap_start;
    wire ap_done, ap_idle, ap_ready;
    
    reg [DATA_WIDTH-1:0] current_state_mem [0:N_STATE-1];
    reg [DATA_WIDTH-1:0] x_mem [0:N_VAR-1];

    wire [STATE_LOG-1:0] current_state_address0;
    wire current_state_ce0;
    reg  [DATA_WIDTH-1:0] current_state_q0;
    
    wire [VAR_LOG-1:0] x_address0;
    wire x_ce0, x_we0;
    wire [DATA_WIDTH-1:0] x_d0;
    reg  [DATA_WIDTH-1:0] x_q0;
    
    wire [VAR_LOG-1:0] x_address1;
    wire x_ce1;
    reg  [DATA_WIDTH-1:0] x_q1;


    reg [1:0] next_byte_idx;
    reg [9:0] next_word_idx;
    

    //--------------------------------------------------------------
    // Main FSM
    //--------------------------------------------------------------
    integer i;
    
    always @(posedge clk) begin
        if (!resetn) begin
            state <= IDLE;
            rx_byte_count <= 0;
            rx_word_count <= 0;
            tx_byte_count <= 0;
            tx_word_count <= 0;
            ap_start <= 0;
            spi_tx_dv <= 0;
            spi_tx_byte <= 8'h00;
        end else begin
            spi_tx_dv <= 0; // Default pulse

            case (state)
                IDLE: begin
                    // In SPI, we start as soon as CS goes low and we get data.
                    // If your Arduino sends a dummy 0xFF start byte, keep this:
                    if (spi_rx_dv && spi_rx_byte == 8'hFF) begin
                        state <= RX_DATA;
                        rx_byte_count <= 0;
                        rx_word_count <= 0;
                    end
                end

                RX_DATA: begin
                    if (spi_rx_dv) begin
                        case (rx_byte_count)
                            0: rx_word_buffer[7:0]   <= spi_rx_byte;
                            1: rx_word_buffer[15:8]  <= spi_rx_byte;
                            2: rx_word_buffer[23:16] <= spi_rx_byte;
                            3: begin
                                current_state_mem[rx_word_count] <= {spi_rx_byte, rx_word_buffer[23:0]};
                            end
                        endcase
                        
                        if (rx_byte_count == 3) begin
                            rx_byte_count <= 0;
                            if (rx_word_count == N_STATE-1)
                                state <= COMPUTE;
                            else
                                rx_word_count <= rx_word_count + 1;
                        end else begin
                            rx_byte_count <= rx_byte_count + 1;
                        end
                    end
                end

                COMPUTE: begin
                    ap_start <= 1;
                    if (ap_ready || ap_done) begin
                        ap_start <= 0;
                        state <= WAIT_FOR_POLL;
                        // Prepare the "Ready" byte (0xAB or any != 0)
                        spi_tx_byte <= 8'hAB; 
                        spi_tx_dv   <= 1;
                    end
                end

                WAIT_FOR_POLL: begin
                    // The master is doing while(!SPI.transfer(0x00))
                    // When the master sends a byte, spi_rx_dv triggers.
                    if (spi_rx_dv) begin
                        // Master just received our 0xAB. 
                        // Now load the first actual data byte for the next transfer.
                        state <= TX_DATA;
                        tx_word_count <= 0;
                        tx_byte_count <= 0;
                        // Pre-load first byte of data
                        spi_tx_byte <= x_mem[0][7:0];
                        spi_tx_dv   <= 1;
                    end
                end

                TX_DATA: begin
                    if (spi_rx_dv) begin
                        // Master just finished reading the byte we set in the PREVIOUS cycle.
                        // Logic to figure out what the NEXT byte should be.

                        if (tx_byte_count == 3) begin
                            next_byte_idx = 0;
                            next_word_idx = tx_word_count + 1;
                        end else begin
                            next_byte_idx = tx_byte_count + 1;
                            next_word_idx = tx_word_count;
                        end

                        if (tx_word_count == N_VAR-1 && tx_byte_count == 3) begin
                            state <= DONE;
                        end else begin
                            // Load next byte for the master to shift out
                            case (next_byte_idx)
                                0: spi_tx_byte <= x_mem[next_word_idx][7:0];
                                1: spi_tx_byte <= x_mem[next_word_idx][15:8];
                                2: spi_tx_byte <= x_mem[next_word_idx][23:16];
                                3: spi_tx_byte <= x_mem[next_word_idx][31:24];
                            endcase
                            spi_tx_dv <= 1;
                            tx_byte_count <= next_byte_idx;
                            tx_word_count <= next_word_idx;
                        end
                    end
                end

                DONE: begin
                    if (spi_cs_n) state <= IDLE;
                end
            endcase
        end
    end

    //--------------------------------------------------------------
    // SPI Slave Instantiation
    //--------------------------------------------------------------
    SPI_Slave #(.SPI_MODE(0)) i_spi_slave (
        .i_Clk(clk),
        .i_Rst_L(resetn),
        // Data Interface
        .o_RX_DV(spi_rx_dv),
        .o_RX_Byte(spi_rx_byte),
        .i_TX_DV(spi_tx_dv),
        .i_TX_Byte(spi_tx_byte),
        // Physical Pins
        .i_SPI_Clk(spi_sclk),
        .o_SPI_MISO(spi_miso),
        .i_SPI_MOSI(spi_mosi),
        .i_SPI_CS_n(spi_cs_n)
    );
 //--------------------------------------------------------------
    // HLS Module Instantiation
    //--------------------------------------------------------------
    ADMM_solver_0 dut (
        .ap_clk(clk),
        .ap_rst(!resetn),
        .ap_start(ap_start),
        .ap_done(ap_done),
        .ap_idle(ap_idle),
        .ap_ready(ap_ready),
        .current_state_address0(current_state_address0),
        .current_state_ce0(current_state_ce0),
        .current_state_q0(current_state_q0),
        .x_address0(x_address0),
        .x_ce0(x_ce0),
        .x_we0(x_we0),
        .x_d0(x_d0),
        .x_q0(x_q0),
        .x_address1(x_address1),
        .x_ce1(x_ce1),
        .x_q1(x_q1),
        .iters(FIXED_ITERS)
    );
    
    //--------------------------------------------------------------
    // Memory Models
    //--------------------------------------------------------------
    // current_state memory - registered read
    always @(posedge clk) begin
        if (current_state_ce0)
            current_state_q0 <= current_state_mem[current_state_address0];
    end
    
    // x memory - dual-port with synchronous write on port 0
    always @(posedge clk) begin
        if (x_ce0) begin
            if (x_we0) begin
                x_mem[x_address0] <= x_d0;
            end
            x_q0 <= x_mem[x_address0];
        end
    end
    
    // x memory - port 1 (read-only)
    always @(posedge clk) begin
        if (x_ce1)
            x_q1 <= x_mem[x_address1];
    end
    
    
    
    
        //--------------------------------------------------------------
    // Debug LED Logic
    //--------------------------------------------------------------
    reg [23:0] led_stretch_counter; // To make the activity LED visible
    reg        activity_led;

    // Pulse stretcher for LED[3]
    // Whenever a byte is received (spi_rx_dv) or sent (spi_tx_dv), 
    // we turn on the LED and hold it for ~160,000 cycles (visible flicker)
    always @(posedge clk) begin
        if (!resetn) begin
            led_stretch_counter <= 0;
            activity_led <= 0;
        end else begin
            if (spi_rx_dv || spi_tx_dv) begin
                led_stretch_counter <= 24'd160000; 
                activity_led <= 1;
            end else if (led_stretch_counter > 0) begin
                led_stretch_counter <= led_stretch_counter - 1;
                activity_led <= 1;
            end else begin
                activity_led <= 0;
            end
        end
    end

    // Map FSM states to LED[2:0] and Activity to LED[3]
    // LED 000: IDLE
    // LED 001: RX_DATA
    // LED 010: COMPUTE
    // LED 011: WAIT_FOR_POLL
    // LED 100: TX_DATA
    // LED 101: DONE
    assign led = {activity_led, state};
    
endmodule