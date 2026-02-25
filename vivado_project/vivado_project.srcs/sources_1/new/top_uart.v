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
    localparam N_STATE = 12;        // Size of current_state (input)
    localparam N_CMD   = 4;         // Number of command outputs (u0..u3)
    localparam DATA_WIDTH = 32;
    localparam CLK_HZ = 100_000_000;
    localparam BIT_RATE = 921600;
    localparam PAYLOAD_BITS = 8;

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
    reg [3:0] rx_byte_count;
    reg [5:0] rx_word_count;
    reg [3:0] tx_byte_count;
    reg [1:0] tx_word_count;       // 0..3 for 4 command words
    reg [31:0] rx_word_buffer;

    //--------------------------------------------------------------
    // HLS interface: current_in (384 = 12 x 32), command_out (128 = 4 x 32)
    //--------------------------------------------------------------
    reg ap_start;
    wire ap_done;
    wire ap_idle;
    wire ap_ready;

    reg [383:0] current_in_reg;   // 12 x 32-bit state, LSB = state[0]
    wire [127:0] command_out;     // 4 x 32-bit: [31:0]=u0, [63:32]=u1, [95:64]=u2, [127:96]=u3
    wire command_out_ap_vld;

    reg [127:0] command_out_latch; // Capture when ap_done so we can TX after core goes idle

    //--------------------------------------------------------------
    // LED Status
    //--------------------------------------------------------------
    reg [3:0] led_reg;
    assign led = led_reg;

    always @(posedge clk) begin
        if (resetn) begin
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
        if (resetn) begin
            state <= IDLE;
            rx_byte_count <= 0;
            rx_word_count <= 0;
            tx_byte_count <= 0;
            tx_word_count <= 0;
            rx_word_buffer <= 0;
            ap_start <= 0;
            uart_tx_en <= 0;
            uart_tx_data <= 0;
            current_in_reg <= 0;
            command_out_latch <= 0;
        end else begin
            uart_tx_en <= 0;

            case (state)
                IDLE: begin
                    if (uart_rx_valid && uart_rx_data == 8'hFF) begin
                        state <= RX_DATA;
                        rx_byte_count <= 0;
                        rx_word_count <= 0;
                        rx_word_buffer <= 0;
                    end
                    ap_start <= 0;
                end

                RX_DATA: begin
                    if (uart_rx_valid) begin
                        case (rx_byte_count)
                            0: rx_word_buffer[7:0]   <= uart_rx_data;
                            1: rx_word_buffer[15:8]  <= uart_rx_data;
                            2: rx_word_buffer[23:16] <= uart_rx_data;
                            3: begin
                                rx_word_buffer[31:24] <= uart_rx_data;
                                current_in_reg[rx_word_count*32 +: 32] <= {uart_rx_data, rx_word_buffer[23:0]};
                            end
                        endcase

                        if (rx_byte_count == 3) begin
                            rx_byte_count <= 0;
                            if (rx_word_count == N_STATE-1) begin
                                state <= COMPUTE;
                            end else begin
                                rx_word_count <= rx_word_count + 1;
                            end
                        end else begin
                            rx_byte_count <= rx_byte_count + 1;
                        end
                    end
                end

                COMPUTE: begin
                    ap_start <= 1;
                    if (ap_ready || ap_done) begin
                        ap_start <= 0;
                        if (command_out_ap_vld)
                            command_out_latch <= command_out;  // HLS drives command_out valid with ap_done
                        state <= TX_DATA;
                        tx_byte_count <= 0;
                        tx_word_count <= 0;
                    end
                end

                TX_DATA: begin
                    if (!uart_tx_busy && !uart_tx_en) begin
                        case (tx_byte_count)
                            0: uart_tx_data <= command_out_latch[tx_word_count*32 +: 8];
                            1: uart_tx_data <= command_out_latch[tx_word_count*32 + 8 +: 8];
                            2: uart_tx_data <= command_out_latch[tx_word_count*32 + 16 +: 8];
                            3: uart_tx_data <= command_out_latch[tx_word_count*32 + 24 +: 8];
                        endcase
                        uart_tx_en <= 1;

                        if (tx_byte_count == 3) begin
                            tx_byte_count <= 0;
                            if (tx_word_count == N_CMD - 1) begin
                                state <= DONE;
                            end else begin
                                tx_word_count <= tx_word_count + 1;
                            end
                        end else begin
                            tx_byte_count <= tx_byte_count + 1;
                        end
                    end
                end

                DONE: begin
                    state <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

    //--------------------------------------------------------------
    // HLS Module Instantiation (struct interface: current_in, command_out)
    //--------------------------------------------------------------
    ADMM_solver dut (
        .ap_clk(clk),
        .ap_rst(resetn),
        .ap_start(ap_start),
        .ap_done(ap_done),
        .ap_idle(ap_idle),
        .ap_ready(ap_ready),
        .current_in(current_in_reg),
        .command_out(command_out),
        .command_out_ap_vld(command_out_ap_vld)
    );

    //--------------------------------------------------------------
    // UART RX/TX
    //--------------------------------------------------------------
    uart_rx #(
        .BIT_RATE(BIT_RATE),
        .PAYLOAD_BITS(PAYLOAD_BITS),
        .CLK_HZ(CLK_HZ)
    ) i_uart_rx (
        .clk(clk),
        .resetn(!resetn),
        .uart_rxd(uart_rxd),
        .uart_rx_en(1'b1),
        .uart_rx_break(uart_rx_break),
        .uart_rx_valid(uart_rx_valid),
        .uart_rx_data(uart_rx_data)
    );

    uart_tx #(
        .BIT_RATE(BIT_RATE),
        .PAYLOAD_BITS(PAYLOAD_BITS),
        .CLK_HZ(CLK_HZ)
    ) i_uart_tx (
        .clk(clk),
        .resetn(!resetn),
        .uart_txd(uart_txd),
        .uart_tx_en(uart_tx_en),
        .uart_tx_busy(uart_tx_busy),
        .uart_tx_data(uart_tx_data)
    );

endmodule
