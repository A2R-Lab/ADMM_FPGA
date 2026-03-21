`timescale 1ns/1ps
`include "admm_autogen_params.vh"

module top_uart (
    input  wire        clk,
    input  wire        resetn,
    input  wire        uart_rxd,
    output wire        uart_txd,
    output wire [3:0]  led
);

    localparam N_STATE = `ADMM_N_STATE;
    localparam N_CMD = 4;
    localparam DATA_WIDTH = 32;
    localparam TRAJ_CMD_WIDTH = 2;
    localparam CURRENT_IN_WIDTH = N_STATE * DATA_WIDTH + TRAJ_CMD_WIDTH;
    localparam CLK_HZ = 100_000_000;
    localparam BIT_RATE = 921600;
    localparam PAYLOAD_BITS = 8;

    localparam IDLE = 3'd0;
    localparam RX_DATA = 3'd1;
    localparam START_COMPUTE = 3'd2;
    localparam WAIT_DONE = 3'd3;
    localparam TX_DATA = 3'd4;
    localparam DONE = 3'd5;

    wire [PAYLOAD_BITS-1:0] uart_rx_data;
    wire uart_rx_valid;
    wire uart_rx_break;
    wire uart_tx_busy;
    reg  [PAYLOAD_BITS-1:0] uart_tx_data;
    reg  uart_tx_en;

    reg [2:0] state;
    reg [3:0] rx_byte_count;
    reg [5:0] rx_word_count;
    reg [3:0] tx_byte_count;
    reg [1:0] tx_word_count;
    reg [31:0] rx_word_buffer;

    reg ap_start;
    wire ap_done;
    wire ap_idle;
    wire ap_ready;

    reg [CURRENT_IN_WIDTH-1:0] current_in_reg;
    wire [127:0] command_out;
    wire command_out_ap_vld;
    reg [127:0] command_out_latch;

    reg [3:0] led_reg;
    assign led = led_reg;

    always @(posedge clk) begin
        if (resetn) begin
            led_reg <= 4'b0001;
        end else begin
            case (state)
                IDLE:    led_reg <= 4'b0001;
                RX_DATA: led_reg <= 4'b0011;
                START_COMPUTE: led_reg <= 4'b0111;
                WAIT_DONE: led_reg <= 4'b1110;
                TX_DATA: led_reg <= 4'b1111;
                DONE:    led_reg <= 4'b1000;
                default: led_reg <= 4'b0000;
            endcase
        end
    end

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
                        current_in_reg[N_STATE * DATA_WIDTH +: TRAJ_CMD_WIDTH] <= 2'b00;
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
                                current_in_reg[rx_word_count * DATA_WIDTH +: DATA_WIDTH] <= {uart_rx_data, rx_word_buffer[23:0]};
                            end
                        endcase

                        if (rx_byte_count == 3) begin
                            rx_byte_count <= 0;
                            if (rx_word_count == N_STATE - 1) begin
                                state <= START_COMPUTE;
                            end else begin
                                rx_word_count <= rx_word_count + 1;
                            end
                        end else begin
                            rx_byte_count <= rx_byte_count + 1;
                        end
                    end
                end

                START_COMPUTE: begin
                    ap_start <= 1;
                    state <= WAIT_DONE;
                end

                WAIT_DONE: begin
                    ap_start <= 0;
                    if (command_out_ap_vld) begin
                        command_out_latch <= command_out;
                        state <= TX_DATA;
                        tx_byte_count <= 0;
                        tx_word_count <= 0;
                    end
                end

                TX_DATA: begin
                    if (!uart_tx_busy && !uart_tx_en) begin
                        case (tx_byte_count)
                            0: uart_tx_data <= command_out_latch[tx_word_count * 32 +  0 +: 8];
                            1: uart_tx_data <= command_out_latch[tx_word_count * 32 +  8 +: 8];
                            2: uart_tx_data <= command_out_latch[tx_word_count * 32 + 16 +: 8];
                            3: uart_tx_data <= command_out_latch[tx_word_count * 32 + 24 +: 8];
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

    ADMM_solver dut (
        .ap_clk(clk),
        .ap_rst(resetn),
        .ap_start(ap_start),
        .ap_done(ap_done),
        .ap_idle(ap_idle),
        .ap_ready(ap_ready),
        .current_in_bits(current_in_reg),
        .command_out_bits(command_out),
        .command_out_bits_ap_vld(command_out_ap_vld)
    );

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
