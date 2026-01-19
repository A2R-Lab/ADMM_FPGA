`timescale 1ns/1ps

module top_opus (
    input  wire        clk,
    input  wire        resetn,
    
    // SPI Interface
    input  wire        spi_sck,
    input  wire        spi_cs_n,
    input  wire        spi_mosi,
    output wire        spi_miso,
    
    output wire [3:0]  led
);

    //--------------------------------------------------------------
    // Parameters
    //--------------------------------------------------------------
    localparam N_STATE      = 12;
    localparam N_VAR        = 332;
    localparam DATA_WIDTH   = 32;
    localparam FIXED_ITERS  = 32'd10;
    
    localparam STATE_LOG    = $clog2(N_STATE);
    localparam VAR_LOG      = $clog2(N_VAR);
    
    // TX: Result data - 4 words * 4 bytes = 16 bytes (words 12-15)
    localparam TX_START_WORD  = 12;
    localparam TX_END_WORD    = 16;

    // State machine states
    localparam [2:0] IDLE           = 3'd0;
    localparam [2:0] RX_DATA        = 3'd1;
    localparam [2:0] COMPUTE        = 3'd2;
    localparam [2:0] WAIT_POLL      = 3'd3;
    localparam [2:0] TX_READY_BYTE  = 3'd4;
    localparam [2:0] TX_DATA        = 3'd5;
    localparam [2:0] DONE           = 3'd6;

    //--------------------------------------------------------------
    // SPI Signals
    //--------------------------------------------------------------
    wire [7:0] spi_rx_byte;
    wire       spi_rx_valid;
    reg  [7:0] spi_tx_byte;
    reg        spi_tx_valid;
    wire       spi_tx_ready;
    
    // CS edge detection in FPGA clock domain
    reg  [2:0] cs_sync;
    wire       cs_falling, cs_rising;
    wire       cs_active;
    
    always @(posedge clk or negedge resetn) begin
        if (!resetn)
            cs_sync <= 3'b111;
        else
            cs_sync <= {cs_sync[1:0], spi_cs_n};
    end
    
    assign cs_falling = cs_sync[2] & ~cs_sync[1];
    assign cs_rising  = ~cs_sync[2] & cs_sync[1];
    assign cs_active  = ~cs_sync[1];

    //--------------------------------------------------------------
    // FSM and Control Signals
    //--------------------------------------------------------------
    reg [2:0]  state;
    reg [1:0]  rx_byte_count;      // Counts bytes within current word (0-3)
    reg [5:0]  rx_word_count;      // Counts words (0 to N_STATE-1)
    reg [1:0]  tx_byte_count;      // Counts bytes within current word (0-3)
    reg [9:0]  tx_word_count;      // Counts words
    reg [31:0] rx_word_buffer;
    reg        computation_done;   // Flag indicating computation complete
    reg        ready_byte_sent;    // Flag indicating ready byte was sent

    //--------------------------------------------------------------
    // HLS Module Signals
    //--------------------------------------------------------------
    reg        ap_start;
    wire       ap_done;
    wire       ap_idle;
    wire       ap_ready;

    // Memory arrays
    reg [DATA_WIDTH-1:0] current_state_mem [0:N_STATE-1];
    reg [DATA_WIDTH-1:0] x_mem [0:N_VAR-1];

    // current_state memory interface
    wire [STATE_LOG-1:0]   current_state_address0;
    wire                   current_state_ce0;
    reg  [DATA_WIDTH-1:0]  current_state_q0;

    // x memory interface
    wire [VAR_LOG-1:0]     x_address0;
    wire                   x_ce0;
    wire                   x_we0;
    wire [DATA_WIDTH-1:0]  x_d0;
    reg  [DATA_WIDTH-1:0]  x_q0;
    wire [VAR_LOG-1:0]     x_address1;
    wire                   x_ce1;
    reg  [DATA_WIDTH-1:0]  x_q1;

    wire [31:0] iters;
    assign iters = FIXED_ITERS;

    //--------------------------------------------------------------
    // LED Status
    //--------------------------------------------------------------
    reg [3:0] led_reg;
    assign led = led_reg;

    always @(posedge clk) begin
        if (!resetn) begin
            led_reg <= 4'b0001;
        end else begin
            case (state)
                IDLE:          led_reg <= 4'b0001;
                RX_DATA:       led_reg <= 4'b0011;
                COMPUTE:       led_reg <= 4'b0111;
                WAIT_POLL:     led_reg <= 4'b1011;
                TX_READY_BYTE: led_reg <= 4'b1101;
                TX_DATA:       led_reg <= 4'b1111;
                DONE:          led_reg <= 4'b1000;
                default:       led_reg <= 4'b0000;
            endcase
        end
    end

    //--------------------------------------------------------------
    // Main FSM
    //--------------------------------------------------------------
    integer i;
    
    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            state            <= IDLE;
            rx_byte_count    <= 2'd0;
            rx_word_count    <= 6'd0;
            tx_byte_count    <= 2'd0;
            tx_word_count    <= TX_START_WORD;
            rx_word_buffer   <= 32'd0;
            ap_start         <= 1'b0;
            spi_tx_valid     <= 1'b0;
            spi_tx_byte      <= 8'h00;
            computation_done <= 1'b0;
            ready_byte_sent  <= 1'b0;
            
            for (i = 0; i < N_STATE; i = i + 1) begin
                current_state_mem[i] <= 32'd0;
            end
            
        end else begin
            // Default: clear pulse signals
            spi_tx_valid <= 1'b0;
            
            // Handle CS going high (transaction end/abort)
            if (cs_rising && state != IDLE && state != COMPUTE) begin
                state <= IDLE;
                computation_done <= 1'b0;
                ready_byte_sent  <= 1'b0;
            end else begin
            
                case (state)
                    //----------------------------------------------
                    // IDLE: Wait for CS to go low and start byte (0xFF)
                    //----------------------------------------------
                    IDLE: begin
                        ap_start         <= 1'b0;
                        computation_done <= 1'b0;
                        ready_byte_sent  <= 1'b0;
                        rx_byte_count    <= 2'd0;
                        rx_word_count    <= 6'd0;
                        tx_byte_count    <= 2'd0;
                        tx_word_count    <= TX_START_WORD;
                        
                        // Preload TX with 0x00 (not ready response)
                        if (spi_tx_ready && !spi_tx_valid) begin
                            spi_tx_byte  <= 8'h00;
                            spi_tx_valid <= 1'b1;
                        end
                        
                        // Wait for start byte
                        if (spi_rx_valid && spi_rx_byte == 8'hFF) begin
                            state <= RX_DATA;
                        end
                    end

                    //----------------------------------------------
                    // RX_DATA: Receive N_STATE words (4 bytes each, little-endian)
                    //----------------------------------------------
                    RX_DATA: begin
                        // Keep sending 0x00 while receiving (slave must output something)
                        if (spi_tx_ready && !spi_tx_valid) begin
                            spi_tx_byte  <= 8'h00;
                            spi_tx_valid <= 1'b1;
                        end
                        
                        if (spi_rx_valid) begin
                            // Build word byte by byte (little-endian)
                            case (rx_byte_count)
                                2'd0: rx_word_buffer[7:0]   <= spi_rx_byte;
                                2'd1: rx_word_buffer[15:8]  <= spi_rx_byte;
                                2'd2: rx_word_buffer[23:16] <= spi_rx_byte;
                                2'd3: begin
                                    // Store complete word directly
                                    current_state_mem[rx_word_count] <= {spi_rx_byte, rx_word_buffer[23:0]};
                                end
                            endcase
                            
                            if (rx_byte_count == 2'd3) begin
                                rx_byte_count <= 2'd0;
                                
                                if (rx_word_count == N_STATE - 1) begin
                                    // All words received, start computation
                                    state <= COMPUTE;
                                end else begin
                                    rx_word_count <= rx_word_count + 1'b1;
                                end
                            end else begin
                                rx_byte_count <= rx_byte_count + 1'b1;
                            end
                        end
                    end

                    //----------------------------------------------
                    // COMPUTE: Run HLS module
                    //----------------------------------------------
                    COMPUTE: begin
                        ap_start <= 1'b1;
                        
                        // Wait for completion
                        if (ap_done || ap_ready) begin
                            ap_start         <= 1'b0;
                            computation_done <= 1'b1;
                            state            <= WAIT_POLL;
                        end
                    end

                    //----------------------------------------------
                    // WAIT_POLL: Wait for master to poll, respond with 0x00
                    //----------------------------------------------
                    WAIT_POLL: begin
                        // Respond with 0x00 until we detect a poll byte
                        if (spi_tx_ready && !spi_tx_valid) begin
                            spi_tx_byte  <= 8'h00;
                            spi_tx_valid <= 1'b1;
                        end
                        
                        // When we receive a poll byte from master, prepare ready response
                        if (spi_rx_valid) begin
                            state <= TX_READY_BYTE;
                        end
                    end

                    //----------------------------------------------
                    // TX_READY_BYTE: Send ready indicator (0xFF)
                    //----------------------------------------------
                    TX_READY_BYTE: begin
                        if (spi_tx_ready && !spi_tx_valid) begin
                            spi_tx_byte  <= 8'hFF;  // Ready indicator
                            spi_tx_valid <= 1'b1;
                            ready_byte_sent <= 1'b1;
                        end
                        
                        // After master clocks in the ready byte, move to data transmission
                        if (ready_byte_sent && spi_rx_valid) begin
                            state           <= TX_DATA;
                            tx_byte_count   <= 2'd0;
                            tx_word_count   <= TX_START_WORD;
                            ready_byte_sent <= 1'b0;
                        end
                    end

                    //----------------------------------------------
                    // TX_DATA: Send result data (little-endian)
                    //----------------------------------------------
                    TX_DATA: begin
                        if (spi_tx_ready && !spi_tx_valid) begin
                            // Select byte from current word (little-endian)
                            case (tx_byte_count)
                                2'd0: spi_tx_byte <= x_mem[tx_word_count][7:0];
                                2'd1: spi_tx_byte <= x_mem[tx_word_count][15:8];
                                2'd2: spi_tx_byte <= x_mem[tx_word_count][23:16];
                                2'd3: spi_tx_byte <= x_mem[tx_word_count][31:24];
                            endcase
                            spi_tx_valid <= 1'b1;
                        end
                        
                        // Advance counters when master clocks in a byte
                        if (spi_rx_valid) begin
                            if (tx_byte_count == 2'd3) begin
                                tx_byte_count <= 2'd0;
                                
                                if (tx_word_count == TX_END_WORD - 1) begin
                                    // All data sent
                                    state <= DONE;
                                end else begin
                                    tx_word_count <= tx_word_count + 1'b1;
                                end
                            end else begin
                                tx_byte_count <= tx_byte_count + 1'b1;
                            end
                        end
                    end

                    //----------------------------------------------
                    // DONE: Transaction complete, wait for CS high
                    //----------------------------------------------
                    DONE: begin
                        // Send 0x00 padding if master keeps clocking
                        if (spi_tx_ready && !spi_tx_valid) begin
                            spi_tx_byte  <= 8'h00;
                            spi_tx_valid <= 1'b1;
                        end
                        
                        // Return to IDLE when CS goes high (handled above)
                        // Or if CS is already high
                        if (!cs_active) begin
                            state <= IDLE;
                        end
                    end

                    //----------------------------------------------
                    // Default
                    //----------------------------------------------
                    default: begin
                        state <= IDLE;
                    end
                    
                endcase
            end
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
    // Memory Interface: current_state (read-only from HLS)
    //--------------------------------------------------------------
    always @(posedge clk) begin
        if (current_state_ce0)
            current_state_q0 <= current_state_mem[current_state_address0];
    end

    //--------------------------------------------------------------
    // Memory Interface: x memory - dual-port
    //--------------------------------------------------------------
    // Port 0: Read/Write
    always @(posedge clk) begin
        if (x_ce0) begin
            if (x_we0) begin
                x_mem[x_address0] <= x_d0;
            end
            x_q0 <= x_mem[x_address0];
        end
    end

    // Port 1: Read-only
    always @(posedge clk) begin
        if (x_ce1)
            x_q1 <= x_mem[x_address1];
    end

    //--------------------------------------------------------------
    // SPI Slave Module Instantiation
    //--------------------------------------------------------------
    SPI_Slave_opus #(
        .SPI_MODE(0)
    ) spi_slave_inst (
        .i_Rst_L      (resetn),
        .i_Clk        (clk),
        .o_RX_DV      (spi_rx_valid),
        .o_RX_Byte    (spi_rx_byte),
        .i_TX_DV      (spi_tx_valid),
        .i_TX_Byte    (spi_tx_byte),
        .o_TX_Ready   (spi_tx_ready),
        .i_SPI_Clk    (spi_clk),
        .o_SPI_MISO   (spi_miso),
        .i_SPI_MOSI   (spi_mosi),
        .i_SPI_CS_n   (spi_cs_n)
    );

endmodule