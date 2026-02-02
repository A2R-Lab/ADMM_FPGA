`timescale 1ns/1ps

module top (
    input  wire        clk,
    input  wire        resetn,
    input  wire        uart_rxd,
    output wire        uart_txd,
    output wire [3:0]  led
);

    //--------------------------------------------------------------
    // Parameters
    //--------------------------------------------------------------
    localparam N_STATE = 12;        // Size of current_state array
    localparam N_VAR = 332;         // Size of x array
    localparam DATA_WIDTH = 32;
    localparam CLK_HZ = 100_000_000;
    localparam BIT_RATE = 921600;
    localparam PAYLOAD_BITS = 8;
    localparam FIXED_ITERS = 32'd10;  // Fixed iteration count
    
    localparam STATE_LOG = $clog2(N_STATE);
    localparam VAR_LOG = $clog2(N_VAR);
    
    // State machine states
    localparam IDLE         = 3'd0;
    localparam RX_DATA      = 3'd1;
    localparam COMPUTE      = 3'd2;
    localparam TX_DATA      = 3'd3;
    localparam DONE         = 3'd4;
    
    //--------------------------------------------------------------
    // UART Signals
    //--------------------------------------------------------------
    wire [PAYLOAD_BITS-1:0] uart_rx_data;
    wire uart_rx_valid;
    wire uart_rx_break;
    wire uart_tx_busy;
    reg  [PAYLOAD_BITS-1:0] uart_tx_data;
    reg  uart_tx_en;
    
    //--------------------------------------------------------------
    // FSM and Control Signals
    //--------------------------------------------------------------
    reg [2:0] state;
    reg [3:0] rx_byte_count;      // Counts bytes within current word (0-3)
    reg [5:0] rx_word_count;      // Counts words (0 to N_STATE-1), needs to count up to 12
    reg [3:0] tx_byte_count;
    reg [9:0] tx_word_count;      // Counts words (0 to N_VAR-1), needs to count up to 332
    reg [31:0] rx_word_buffer;
    
    //--------------------------------------------------------------
    // HLS Module Signals
    //--------------------------------------------------------------
    reg ap_start;
    wire ap_done;
    wire ap_idle;
    wire ap_ready;
    
    // Memory arrays
    reg [DATA_WIDTH-1:0] current_state_mem [0:N_STATE-1];
    reg [DATA_WIDTH-1:0] x_mem [0:N_VAR-1];

    // current_state memory interface (read-only from HLS perspective)
    wire [STATE_LOG-1:0] current_state_address0;
    wire current_state_ce0;
    reg [DATA_WIDTH-1:0] current_state_q0;
    
    // x memory interface (read/write dual-port)
    wire [VAR_LOG-1:0] x_address0;
    wire x_ce0;
    wire x_we0;
    wire [DATA_WIDTH-1:0] x_d0;
    reg [DATA_WIDTH-1:0] x_q0;
    
    wire [VAR_LOG-1:0] x_address1;
    wire x_ce1;
    reg [DATA_WIDTH-1:0] x_q1;
    
    wire [31:0] iters;
    assign iters = FIXED_ITERS;
    
    //--------------------------------------------------------------
    // LED Status
    //--------------------------------------------------------------
    reg [3:0] led_reg;
    assign led = led_reg;
    
    // LED encoding:
    // 4'b0001: IDLE
    // 4'b0011: Receiving data
    // 4'b0111: Computing
    // 4'b1111: Transmitting
    // 4'b1000: Done
    
    always @(posedge clk) begin
        if (!resetn) begin
            led_reg <= 4'b0001;
        end else begin
            case (state)
                IDLE:    led_reg <= 4'b0001;
                RX_DATA: led_reg <= 4'b0011;
                COMPUTE: led_reg <= 4'b0111;
                TX_DATA: led_reg <= 4'b1111;
                DONE:    led_reg <= 4'b1000;
                default: led_reg <= 4'b0000;
            endcase
        end
    end
    
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
            tx_word_count <= 12;
            rx_word_buffer <= 0;
            ap_start <= 0;
            uart_tx_en <= 0;
            uart_tx_data <= 0;
            
            for (i = 0; i < N_STATE; i = i + 1) begin
                current_state_mem[i] <= 0;
            end
            
        end else begin
            // Default: pulse signals off
            uart_tx_en <= 0;
            
            case (state)
                //----------------------------------------------
                // IDLE: Wait for start signal (0xFF byte)
                //----------------------------------------------
                IDLE: begin
                    if (uart_rx_valid && uart_rx_data == 8'hFF) begin
                        state <= RX_DATA;
                        rx_byte_count <= 0;
                        rx_word_count <= 0;
                        rx_word_buffer <= 0;
                    end
                    ap_start <= 0;
                end
                
                //----------------------------------------------
                // RX_DATA: Receive N_STATE words (4 bytes each, little-endian)
                //----------------------------------------------
                RX_DATA: begin
                    if (uart_rx_valid) begin
                        // Build word byte by byte (little-endian)
                        case (rx_byte_count)
                            0: rx_word_buffer[7:0]   <= uart_rx_data;
                            1: rx_word_buffer[15:8]  <= uart_rx_data;
                            2: rx_word_buffer[23:16] <= uart_rx_data;
                            3: begin
                                rx_word_buffer[31:24] <= uart_rx_data;
                                // Store complete word
                                current_state_mem[rx_word_count] <= {uart_rx_data, rx_word_buffer[23:0]};
                            end
                        endcase
                        
                        if (rx_byte_count == 3) begin
                            // Word complete
                            rx_byte_count <= 0;
                            if (rx_word_count == N_STATE-1) begin
                                // All words received
                                state <= COMPUTE;
                            end else begin
                                rx_word_count <= rx_word_count + 1;
                            end
                        end else begin
                            rx_byte_count <= rx_byte_count + 1;
                        end
                    end
                end
                
                //----------------------------------------------
                // COMPUTE: Run HLS module
                //----------------------------------------------
                COMPUTE: begin
                    // Keep ap_start high until ready or done
                    ap_start <= 1;
                    
                    // Wait for completion (ap_ready or ap_done)
                    if (ap_ready || ap_done) begin
                        ap_start <= 0;
                        state <= TX_DATA;
                        tx_byte_count <= 0;
                        tx_word_count <= 12;
                    end
                end
                
                //----------------------------------------------
                // TX_DATA: Send N_VAR words back (4 bytes each, little-endian)
                //----------------------------------------------
                TX_DATA: begin
                    if (!uart_tx_busy && !uart_tx_en) begin
                        // Send next byte
                        case (tx_byte_count)
                            0: uart_tx_data <= x_mem[tx_word_count][7:0];
                            1: uart_tx_data <= x_mem[tx_word_count][15:8];
                            2: uart_tx_data <= x_mem[tx_word_count][23:16];
                            3: uart_tx_data <= x_mem[tx_word_count][31:24];
                        endcase
                        uart_tx_en <= 1;
                        
                        if (tx_byte_count == 3) begin
                            tx_byte_count <= 0;
                            if (tx_word_count == 16-1) begin
                                state <= DONE;
                            end else begin
                                tx_word_count <= tx_word_count + 1;
                            end
                        end else begin
                            tx_byte_count <= tx_byte_count + 1;
                        end
                    end
                end
                
                //----------------------------------------------
                // DONE: Wait for new transaction
                //----------------------------------------------
                DONE: begin
                    state <= IDLE;
                end
                
                default: state <= IDLE;
            endcase
        end
    end
    
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
        .iters(iters)
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
    // UART RX Module
    //--------------------------------------------------------------
    uart_rx #(
        .BIT_RATE(BIT_RATE),
        .PAYLOAD_BITS(PAYLOAD_BITS),
        .CLK_HZ(CLK_HZ)
    ) i_uart_rx (
        .clk(clk),
        .resetn(resetn),
        .uart_rxd(uart_rxd),
        .uart_rx_en(1'b1),
        .uart_rx_break(uart_rx_break),
        .uart_rx_valid(uart_rx_valid),
        .uart_rx_data(uart_rx_data)
    );
    
    //--------------------------------------------------------------
    // UART TX Module
    //--------------------------------------------------------------
    uart_tx #(
        .BIT_RATE(BIT_RATE),
        .PAYLOAD_BITS(PAYLOAD_BITS),
        .CLK_HZ(CLK_HZ)
    ) i_uart_tx (
        .clk(clk),
        .resetn(resetn),
        .uart_txd(uart_txd),
        .uart_tx_en(uart_tx_en),
        .uart_tx_busy(uart_tx_busy),
        .uart_tx_data(uart_tx_data)
    );

endmodule