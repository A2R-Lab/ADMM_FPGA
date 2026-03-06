`timescale 1ns/1ps
`include "admm_autogen_params.vh"

module top_spi (
    input  wire        clk,
    input  wire        resetn,
    input  wire        spi_cf_sck,
    input  wire        spi_cf_mosi,
    output wire        spi_cf_miso,
    input  wire        spi_cs_n,
    output wire        io2,          // IRQ: assert when results ready (Crazyflie IO2)
    output wire        led1,
    output wire        led2
);

    //--------------------------------------------------------------
    // Parameters
    //--------------------------------------------------------------
    localparam N_STATE = `ADMM_N_STATE;
    localparam N_CTRL_TX = 4;
    localparam X_MEM_DEPTH = `ADMM_N_VAR;
    localparam DATA_WIDTH = 32;
    
    // Packet Headers
    localparam RX_HEADER = 32'h000000AA;       // Master must send 0xAA in lowest byte
    localparam START_TRAJ_MASK = 32'h00000100; // Header bit for trajectory start
    localparam TX_HEADER = 32'hFFFFFFFF; // FPGA sends 0xFF as Ready signal
    
    localparam STATE_LOG = $clog2(N_STATE);
    localparam VAR_LOG = $clog2(X_MEM_DEPTH);
    localparam CTRL_TX_BASE = N_STATE + (`ADMM_STAGE_SIZE * `ADMM_DELAY_STEPS);
    
    // States
    localparam IDLE         = 3'd0;
    localparam CHECK_HEADER = 3'd1; // New State: Verify 0xAA
    localparam RX_DATA      = 3'd2;
    localparam COMPUTE      = 3'd3;
    localparam WAIT_RAM     = 3'd4;
    localparam TX_DATA      = 3'd5;
    localparam DONE         = 3'd6;
    
    //--------------------------------------------------------------
    // SPI Signals
    //--------------------------------------------------------------
    wire [DATA_WIDTH-1:0] spi_rx_data;
    wire spi_rx_valid;
    wire spi_tx_ready;
    reg  [DATA_WIDTH-1:0] spi_tx_data;
    reg  spi_tx_load;
    wire slave_miso_out;

    // HANDSHAKE: MISO=0 during COMPUTE/WAIT to indicate Busy
    assign spi_cf_miso = ((state == COMPUTE) || (state == WAIT_RAM)) ? 1'b0 : slave_miso_out;

    // IRQ: assert when results ready (rising edge triggers Crazyflie); clear when CS high
    reg irq_reg;
    assign io2 = irq_reg;

    //--------------------------------------------------------------
    // Internal Signals
    //--------------------------------------------------------------
    reg [2:0] state;
    reg [5:0] rx_word_count;      
    reg [9:0] tx_word_count;      
    
    // HLS Signals
    reg ap_start;
    wire ap_done;
    wire ap_idle;
    wire ap_ready;
    
    // Memory
    reg [31:0] current_state_mem [0:N_STATE-1];  
    reg [31:0] x_mem [0:X_MEM_DEPTH-1];
    
    // Memory Ports
    wire [STATE_LOG-1:0] current_state_address0;
    wire current_state_ce0;
    reg [31:0] current_state_q0;
    
    wire [VAR_LOG-1:0] x_address0;
    wire x_ce0;
    wire x_we0;
    wire [31:0] x_d0;
    reg [31:0] x_q0;
    
    wire [VAR_LOG-1:0] x_address1;
    wire x_ce1;
    reg [31:0] x_q1;

    reg [31:0] start_traj_reg;
    
    //--------------------------------------------------------------
    // LEDs:
    // - led1: solver busy (COMPUTE/WAIT_RAM)
    // - led2: trajectory mode latched
    //--------------------------------------------------------------
    assign led1 = ((state == COMPUTE) || (state == WAIT_RAM));
    assign led2 = start_traj_reg[0];

    //--------------------------------------------------------------
    // Main FSM
    //--------------------------------------------------------------
    integer i;
    
    always @(posedge clk) begin
        if (!resetn) begin
            state <= IDLE;
            rx_word_count <= 0;
            tx_word_count <= 0;
            ap_start <= 0;
            spi_tx_load <= 1;  // Load zero on reset
            spi_tx_data <= 0;
            irq_reg <= 0;
            start_traj_reg <= 32'd0;
            for (i = 0; i < N_STATE; i = i + 1) current_state_mem[i] <= 0;
        end else begin
            spi_tx_load <= 0; // Default
            
            // Clear IRQ when CS goes high (so next completion can generate rising edge)
            if (spi_cs_n) irq_reg <= 0;
            
            // GLOBAL RESET on CS_N HIGH
            // This is crucial for reliability. If CS goes high, we reset to IDLE.
            if (spi_cs_n && state != IDLE) begin
                state <= IDLE;
                ap_start <= 0;
                // Clear SPI transmit buffer to zero when entering IDLE
                spi_tx_data <= 0;
                spi_tx_load <= 1;
            end else begin
            
                case (state)
                    // 1. Wait for CS Low
                    IDLE: begin
                        if (!spi_cs_n) begin
                            state <= CHECK_HEADER;
                        end
                        // Ensure SPI transmit buffer is zero while in IDLE
                        if (spi_cs_n) begin
                            spi_tx_data <= 0;
                            spi_tx_load <= 1;
                        end
                        ap_start <= 0;
                    end
                    
                    // 2. SAFETY CHECK: Verify header and decode optional start bit
                    CHECK_HEADER: begin
                        if (spi_rx_valid) begin
                            // Use mask 0xFF to check only the lowest byte (0xAA)
                            if ((spi_rx_data & 32'h000000FF) == 32'h000000AA) begin
                                // Latch start command from header bit (stays high once set)
                                if ((spi_rx_data & START_TRAJ_MASK) != 0) begin
                                    start_traj_reg <= 32'd1;
                                end
                                state <= RX_DATA;
                                rx_word_count <= 0;
                            end else begin
                                // Bad Header! Ignore packet.
                                // Stay here or go to dummy state until CS high.
                                state <= DONE; 
                            end
                        end
                    end
                    
                    // 3. Receive Data
                    RX_DATA: begin
                        if (spi_rx_valid) begin
                            current_state_mem[rx_word_count] <= spi_rx_data;
                            if (rx_word_count == N_STATE-1) state <= COMPUTE;
                            else rx_word_count <= rx_word_count + 1;
                        end
                    end
                    
                    // 4. Compute
                    COMPUTE: begin
                        ap_start <= 1;
                        if (ap_ready || ap_done) begin
                            ap_start <= 0;
                            state <= WAIT_RAM;
                            
                            // LOAD HEADER (0xFFFFFF) for Polling
                            spi_tx_data <= TX_HEADER; 
                            spi_tx_load <= 1;
                            tx_word_count <= 0;
                            
                        end
                    end
    
                    // 5. RAM Latency Compensation
                    WAIT_RAM: begin
                        irq_reg <= 1;  // IRQ: result ready (Crazyflie IO2)
                        state <= TX_DATA;
                    end
                    
                    // 6. Transmit Results
                    TX_DATA: begin
                        if (spi_tx_ready) begin
                            // The Header (or previous word) is gone.
                            if (tx_word_count < N_CTRL_TX) begin
                                // spi_tx_data <= {8'hD0, 8'h0D, tx_word_count[7:0]};
                                spi_tx_data <= x_mem[CTRL_TX_BASE + tx_word_count][31:0];
                                spi_tx_load <= 1;
                                tx_word_count <= tx_word_count + 1;
                            end else begin
                                state <= DONE;
                            end
                        end
                    end
                    
                    DONE: begin
                        // Wait for CS to go high (handled by Global Reset logic above)
                    end
                    
                    default: state <= IDLE;
                endcase
            end
        end
    end
    
    //--------------------------------------------------------------
    // Instantiations
    //--------------------------------------------------------------
    ADMM_solver dut (
        .ap_clk(clk), .ap_rst(!resetn), .ap_start(ap_start), .ap_done(ap_done),
        .ap_idle(ap_idle), .ap_ready(ap_ready),
        .current_state_address0(current_state_address0), .current_state_ce0(current_state_ce0),
        .current_state_q0(current_state_q0),
        .x_address0(x_address0), .x_ce0(x_ce0), .x_we0(x_we0), .x_d0(x_d0), .x_q0(x_q0),
        .x_address1(x_address1), .x_ce1(x_ce1), .x_q1(x_q1),
        .start_traj(start_traj_reg)
    );
    
    // RAM Models
    always @(posedge clk) if (current_state_ce0) current_state_q0 <= current_state_mem[current_state_address0];
    always @(posedge clk) if (x_ce0) begin if(x_we0) x_mem[x_address0] <= x_d0; x_q0 <= x_mem[x_address0]; end
    always @(posedge clk) if (x_ce1) x_q1 <= x_mem[x_address1];
    
    spi_slave_word #(.WORD_WIDTH(DATA_WIDTH)) i_spi_slave (
        .clk(clk), .resetn(resetn),
        .spi_sck(spi_cf_sck), .spi_mosi(spi_cf_mosi), .spi_miso(slave_miso_out), .spi_cs_n(spi_cs_n),
        .rx_data(spi_rx_data), .rx_valid(spi_rx_valid),
        .tx_data(spi_tx_data), .tx_load(spi_tx_load), .tx_ready(spi_tx_ready)
    );

endmodule
