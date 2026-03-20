`timescale 1ns/1ps
`include "admm_autogen_params.vh"

module top_spi (
    input  wire        clk,
    input  wire        resetn,
    input  wire        spi_cf_sck,
    input  wire        spi_cf_mosi,
    output wire        spi_cf_miso,
    input  wire        spi_cs_n,
    output wire        io2,
    output wire        led1,
    output wire        led2
);

    localparam N_STATE = `ADMM_N_STATE;
    localparam N_CMD = 4;
    localparam DATA_WIDTH = 32;
    localparam TRAJ_CMD_WIDTH = 2;
    localparam CURRENT_IN_WIDTH = N_STATE * DATA_WIDTH + TRAJ_CMD_WIDTH;

    localparam RX_HEADER = 32'h000000AA;
    localparam START_TRAJ_MASK = 32'h00000100;
    localparam RESET_TRAJ_MASK = 32'h00000200;
    localparam TX_HEADER = 32'hFFFFFFFF;

    localparam IDLE = 3'd0;
    localparam CHECK_HEADER = 3'd1;
    localparam RX_DATA = 3'd2;
    localparam COMPUTE = 3'd3;
    localparam WAIT_RAM = 3'd4;
    localparam TX_DATA = 3'd5;
    localparam DONE = 3'd6;

    wire [DATA_WIDTH-1:0] spi_rx_data;
    wire spi_rx_valid;
    wire spi_tx_ready;
    reg  [DATA_WIDTH-1:0] spi_tx_data;
    reg  spi_tx_load;
    wire slave_miso_out;

    assign spi_cf_miso = ((state == COMPUTE) || (state == WAIT_RAM)) ? 1'b0 : slave_miso_out;

    reg irq_reg;
    assign io2 = irq_reg;

    reg [2:0] state;
    reg [5:0] rx_word_count;
    reg [1:0] tx_word_count;

    reg ap_start;
    wire ap_done;
    wire ap_idle;
    wire ap_ready;

    reg [CURRENT_IN_WIDTH-1:0] current_in_reg;
    wire [127:0] command_out;
    wire command_out_ap_vld;
    reg [127:0] command_out_latch;

    reg led1_reg, led2_reg;
    assign led1 = led1_reg;
    assign led2 = led2_reg;

    always @(posedge clk) begin
        if (!resetn) begin
            led1_reg <= 1'b0;
            led2_reg <= 1'b0;
        end else begin
            case (state)
                IDLE:         begin led1_reg <= 1'b0; led2_reg <= 1'b0; end
                CHECK_HEADER: begin led1_reg <= 1'b0; led2_reg <= current_in_reg[N_STATE * DATA_WIDTH]; end
                RX_DATA:      begin led1_reg <= 1'b0; led2_reg <= current_in_reg[N_STATE * DATA_WIDTH]; end
                COMPUTE:      begin led1_reg <= 1'b1; led2_reg <= current_in_reg[N_STATE * DATA_WIDTH]; end
                WAIT_RAM:     begin led1_reg <= 1'b1; led2_reg <= current_in_reg[N_STATE * DATA_WIDTH]; end
                TX_DATA:      begin led1_reg <= 1'b1; led2_reg <= current_in_reg[N_STATE * DATA_WIDTH]; end
                DONE:         begin led1_reg <= 1'b1; led2_reg <= current_in_reg[N_STATE * DATA_WIDTH]; end
                default:      begin led1_reg <= 1'b0; led2_reg <= 1'b0; end
            endcase
        end
    end

    always @(posedge clk) begin
        if (!resetn) begin
            state <= IDLE;
            rx_word_count <= 0;
            tx_word_count <= 0;
            ap_start <= 0;
            spi_tx_load <= 1;
            spi_tx_data <= 0;
            irq_reg <= 0;
            current_in_reg <= 0;
            command_out_latch <= 0;
        end else begin
            spi_tx_load <= 0;

            if (spi_cs_n) irq_reg <= 0;

            if (spi_cs_n && state != IDLE) begin
                state <= IDLE;
                ap_start <= 0;
                spi_tx_data <= 0;
                spi_tx_load <= 1;
            end else begin
                case (state)
                    IDLE: begin
                        if (!spi_cs_n) begin
                            state <= CHECK_HEADER;
                        end
                        if (spi_cs_n) begin
                            spi_tx_data <= 0;
                            spi_tx_load <= 1;
                        end
                        ap_start <= 0;
                    end

                    CHECK_HEADER: begin
                        if (spi_rx_valid) begin
                            if ((spi_rx_data & 32'h000000FF) == RX_HEADER) begin
                                current_in_reg[N_STATE * DATA_WIDTH + 0] <= ((spi_rx_data & START_TRAJ_MASK) != 0);
                                current_in_reg[N_STATE * DATA_WIDTH + 1] <= ((spi_rx_data & RESET_TRAJ_MASK) != 0);
                                state <= RX_DATA;
                                rx_word_count <= 0;
                            end else begin
                                state <= DONE;
                            end
                        end
                    end

                    RX_DATA: begin
                        if (spi_rx_valid) begin
                            current_in_reg[rx_word_count * DATA_WIDTH +: DATA_WIDTH] <= spi_rx_data;
                            if (rx_word_count == N_STATE - 1) begin
                                state <= COMPUTE;
                            end else begin
                                rx_word_count <= rx_word_count + 1;
                            end
                        end
                    end

                    COMPUTE: begin
                        ap_start <= 1;
                        if (ap_ready || ap_done) begin
                            ap_start <= 0;
                            if (command_out_ap_vld) begin
                                command_out_latch <= command_out;
                            end
                            state <= WAIT_RAM;
                            spi_tx_data <= TX_HEADER;
                            spi_tx_load <= 1;
                            tx_word_count <= 0;
                        end
                    end

                    WAIT_RAM: begin
                        irq_reg <= 1;
                        state <= TX_DATA;
                    end

                    TX_DATA: begin
                        if (spi_tx_ready) begin
                            if (tx_word_count < N_CMD) begin
                                spi_tx_data <= command_out_latch[tx_word_count * 32 +: 32];
                                spi_tx_load <= 1;
                                tx_word_count <= tx_word_count + 1;
                            end else begin
                                state <= DONE;
                            end
                        end
                    end

                    DONE: begin
                    end

                    default: state <= IDLE;
                endcase
            end
        end
    end

    ADMM_solver dut (
        .ap_clk(clk),
        .ap_rst(!resetn),
        .ap_start(ap_start),
        .ap_done(ap_done),
        .ap_idle(ap_idle),
        .ap_ready(ap_ready),
        .current_in(current_in_reg),
        .command_out(command_out),
        .command_out_ap_vld(command_out_ap_vld)
    );

    spi_slave_word #(.WORD_WIDTH(DATA_WIDTH)) i_spi_slave (
        .clk(clk),
        .resetn(resetn),
        .spi_sck(spi_cf_sck),
        .spi_mosi(spi_cf_mosi),
        .spi_miso(slave_miso_out),
        .spi_cs_n(spi_cs_n),
        .rx_data(spi_rx_data),
        .rx_valid(spi_rx_valid),
        .tx_data(spi_tx_data),
        .tx_load(spi_tx_load),
        .tx_ready(spi_tx_ready)
    );

endmodule
