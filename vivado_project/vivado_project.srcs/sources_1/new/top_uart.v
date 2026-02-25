`timescale 1ns/1ps

module top (
    input  wire        sys_clk_i,
    input  wire        resetn,      // Active-high reset from BTN0
    input  wire        uart_rxd,
    output wire        uart_txd,
    output wire [3:0]  led,

    // Arty A7 DDR3 interface (matches MIG XDC naming)
    output wire [13:0] ddr3_addr,
    output wire [2:0]  ddr3_ba,
    output wire        ddr3_cas_n,
    output wire [0:0]  ddr3_ck_n,
    output wire [0:0]  ddr3_ck_p,
    output wire [0:0]  ddr3_cke,
    output wire [0:0]  ddr3_cs_n,
    output wire [1:0]  ddr3_dm,
    inout  wire [15:0] ddr3_dq,
    inout  wire [1:0]  ddr3_dqs_n,
    inout  wire [1:0]  ddr3_dqs_p,
    output wire [0:0]  ddr3_odt,
    output wire        ddr3_ras_n,
    output wire        ddr3_reset_n,
    output wire        ddr3_we_n,

    // QSPI flash pins used by AXI Quad SPI XIP
    inout  wire        qspi_io0_io,
    inout  wire        qspi_io1_io,
    inout  wire [0:0]  qspi_ss_io
);

    localparam integer N_STATE = 12;
    localparam integer N_CMD = 4;
    localparam integer PAYLOAD_BITS = 8;

    // MIG ui_clk is derived from DDR timing (Arty default is ~81.25 MHz)
    localparam integer UI_CLK_HZ = 81_250_000;
    localparam integer BIT_RATE = 921_600;

    localparam [3:0] BOOT_WAIT_MIG    = 4'd0;
    localparam [3:0] BOOT_START_LOADER= 4'd1;
    localparam [3:0] BOOT_WAIT_LOADER = 4'd2;
    localparam [3:0] IDLE             = 4'd3;
    localparam [3:0] RX_DATA          = 4'd4;
    localparam [3:0] SOLVER_START     = 4'd5;
    localparam [3:0] SOLVER_WAIT      = 4'd6;
    localparam [3:0] TX_DATA          = 4'd7;
    localparam [3:0] DONE             = 4'd8;

    localparam [63:0] FLASH_BLOB_BASE = 64'h0000_0000_0060_0000;
    localparam [63:0] DDR_BLOB_BASE   = 64'h0000_0000_8000_0000;
    localparam [31:0] MATRIX_WORD_COUNT = 32'd120900;
    localparam [31:0] LOADER_CHECKSUM_EXPECTED = 32'hFCA3_3EC8;
    localparam [23:0] LOADER_CHECKSUM_TIMEOUT = 24'd16000000; // ~0.2s at ~81.25 MHz

    // ------------------------------------------------------------
    // BD wrapper ports/signals
    // ------------------------------------------------------------
    wire ui_clk_0;
    wire ui_clk_sync_rst_0;
    wire init_calib_complete_0;

    reg  ap_ctrl_0_start;
    wire ap_ctrl_0_done;
    wire ap_ctrl_0_idle;
    wire ap_ctrl_0_ready;

    reg  ap_ctrl_1_start;
    wire ap_ctrl_1_done;
    wire ap_ctrl_1_idle;
    wire ap_ctrl_1_ready;

    reg  [383:0] current_in_0;
    wire [127:0] command_out_0;
    wire command_out_ap_vld_0;

    wire [31:0] checksum_out_0;
    wire checksum_out_ap_vld_0;

    wire [63:0] flash_blob_0 = FLASH_BLOB_BASE;
    wire [63:0] ddr_blob_0   = DDR_BLOB_BASE;
    wire [31:0] word_count_0 = MATRIX_WORD_COUNT;
    wire [63:0] matrix_blob_0 = DDR_BLOB_BASE;

    // STARTUP interface outputs are unused at top level.
    wire startup_cfgclk_unused;
    wire startup_cfgmclk_unused;
    wire startup_eos_unused;
    wire startup_preq_unused;

    // ------------------------------------------------------------
    // UART signals (running in MIG ui_clk domain)
    // ------------------------------------------------------------
    wire [PAYLOAD_BITS-1:0] uart_rx_data;
    wire uart_rx_valid;
    wire uart_rx_break;
    wire uart_tx_busy;
    reg  [PAYLOAD_BITS-1:0] uart_tx_data;
    reg  uart_tx_en;

    // ------------------------------------------------------------
    // FSM/transport registers
    // ------------------------------------------------------------
    reg [3:0]  state;
    reg [3:0]  rx_byte_count;
    reg [5:0]  rx_word_count;
    reg [3:0]  tx_byte_count;
    reg [1:0]  tx_word_count;
    reg [31:0] rx_word_buffer;
    reg [127:0] command_out_latch;

    reg [31:0] loader_checksum_reg;
    reg loader_checksum_valid;
    reg loader_done_seen;
    reg [23:0] loader_checksum_wait_ctr;
    reg loader_done_ok;
    reg boot_done;

    reg [3:0] led_reg;
    assign led = led_reg;

    wire core_reset = ui_clk_sync_rst_0 | resetn;
    wire core_resetn = ~core_reset;

    // ------------------------------------------------------------
    // LED status
    // ------------------------------------------------------------
    always @(posedge ui_clk_0) begin
        if (core_reset) begin
            led_reg <= 4'b0001;
        end else begin
            if (boot_done && !loader_done_ok) begin
                led_reg <= 4'b1000;
            end else begin
                case (state)
                    BOOT_WAIT_MIG:     led_reg <= 4'b0001;
                    BOOT_START_LOADER: led_reg <= 4'b0010;
                    BOOT_WAIT_LOADER:  led_reg <= 4'b0011;
                    IDLE:              led_reg <= 4'b0100;
                    RX_DATA:           led_reg <= 4'b0111;
                    SOLVER_START:      led_reg <= 4'b1110;
                    SOLVER_WAIT:       led_reg <= 4'b1110;
                    TX_DATA:           led_reg <= 4'b1111;
                    DONE:              led_reg <= 4'b0101;
                    default:           led_reg <= 4'b0000;
                endcase
            end
        end
    end

    // ------------------------------------------------------------
    // Main FSM
    // ------------------------------------------------------------
    always @(posedge ui_clk_0) begin
        if (core_reset) begin
            state <= BOOT_WAIT_MIG;
            rx_byte_count <= 0;
            rx_word_count <= 0;
            tx_byte_count <= 0;
            tx_word_count <= 0;
            rx_word_buffer <= 32'd0;
            current_in_0 <= 384'd0;
            command_out_latch <= 128'd0;

            ap_ctrl_0_start <= 1'b0;
            ap_ctrl_1_start <= 1'b0;

            uart_tx_en <= 1'b0;
            uart_tx_data <= 8'd0;

            loader_checksum_reg <= 32'd0;
            loader_checksum_valid <= 1'b0;
            loader_done_seen <= 1'b0;
            loader_checksum_wait_ctr <= 24'd0;
            loader_done_ok <= 1'b0;
            boot_done <= 1'b0;
        end else begin
            ap_ctrl_0_start <= 1'b0;
            ap_ctrl_1_start <= 1'b0;
            uart_tx_en <= 1'b0;

            if (checksum_out_ap_vld_0) begin
                loader_checksum_reg <= checksum_out_0;
                loader_checksum_valid <= 1'b1;
            end

            case (state)
                BOOT_WAIT_MIG: begin
                    if (init_calib_complete_0) begin
                        state <= BOOT_START_LOADER;
                    end
                end

                BOOT_START_LOADER: begin
                    loader_checksum_valid <= 1'b0;
                    loader_done_seen <= 1'b0;
                    loader_checksum_wait_ctr <= 24'd0;
                    ap_ctrl_1_start <= 1'b1;
                    // Keep ap_start asserted until the HLS block accepts it.
                    if (ap_ctrl_1_ready) begin
                        state <= BOOT_WAIT_LOADER;
                    end
                end

                BOOT_WAIT_LOADER: begin
                    if (ap_ctrl_1_done) begin
                        loader_done_seen <= 1'b1;
                    end

                    if (loader_done_seen && !loader_checksum_valid &&
                        loader_checksum_wait_ctr != LOADER_CHECKSUM_TIMEOUT) begin
                        loader_checksum_wait_ctr <= loader_checksum_wait_ctr + 1'b1;
                    end

                    // Resolve loader status once done is seen and checksum is valid.
                    // If checksum valid never arrives, fall back after timeout.
                    if (loader_done_seen &&
                        (loader_checksum_valid || (loader_checksum_wait_ctr == LOADER_CHECKSUM_TIMEOUT))) begin
                        boot_done <= 1'b1;
                        if (loader_checksum_valid) begin
                            loader_done_ok <= (loader_checksum_reg == LOADER_CHECKSUM_EXPECTED);
                        end else begin
                            loader_done_ok <= (checksum_out_0 == LOADER_CHECKSUM_EXPECTED);
                        end
                        state <= IDLE;
                    end
                end

                IDLE: begin
                    // Allow runtime testing even if loader checksum flag is false.
                    // The LED error indication is still preserved for diagnostics.
                    if (uart_rx_valid && uart_rx_data == 8'hFF) begin
                        state <= RX_DATA;
                        rx_byte_count <= 0;
                        rx_word_count <= 0;
                        rx_word_buffer <= 32'd0;
                    end
                end

                RX_DATA: begin
                    if (uart_rx_valid) begin
                        case (rx_byte_count)
                            0: rx_word_buffer[7:0]   <= uart_rx_data;
                            1: rx_word_buffer[15:8]  <= uart_rx_data;
                            2: rx_word_buffer[23:16] <= uart_rx_data;
                            3: begin
                                rx_word_buffer[31:24] <= uart_rx_data;
                                current_in_0[rx_word_count*32 +: 32] <= {uart_rx_data, rx_word_buffer[23:0]};
                            end
                            default: rx_word_buffer <= rx_word_buffer;
                        endcase

                        if (rx_byte_count == 3) begin
                            rx_byte_count <= 0;
                            if (rx_word_count == N_STATE-1) begin
                                state <= SOLVER_START;
                            end else begin
                                rx_word_count <= rx_word_count + 1'b1;
                            end
                        end else begin
                            rx_byte_count <= rx_byte_count + 1'b1;
                        end
                    end
                end

                SOLVER_START: begin
                    ap_ctrl_0_start <= 1'b1;
                    // Keep ap_start asserted until the HLS block accepts it.
                    if (ap_ctrl_0_ready) begin
                        state <= SOLVER_WAIT;
                    end
                end

                SOLVER_WAIT: begin
                    if (ap_ctrl_0_done || command_out_ap_vld_0) begin
                        command_out_latch <= command_out_0;
                        tx_byte_count <= 0;
                        tx_word_count <= 0;
                        state <= TX_DATA;
                    end
                end

                TX_DATA: begin
                    if (!uart_tx_busy && !uart_tx_en) begin
                        case (tx_byte_count)
                            0: uart_tx_data <= command_out_latch[tx_word_count*32 +: 8];
                            1: uart_tx_data <= command_out_latch[tx_word_count*32 + 8 +: 8];
                            2: uart_tx_data <= command_out_latch[tx_word_count*32 + 16 +: 8];
                            3: uart_tx_data <= command_out_latch[tx_word_count*32 + 24 +: 8];
                            default: uart_tx_data <= 8'd0;
                        endcase
                        uart_tx_en <= 1'b1;

                        if (tx_byte_count == 3) begin
                            tx_byte_count <= 0;
                            if (tx_word_count == N_CMD-1) begin
                                state <= DONE;
                            end else begin
                                tx_word_count <= tx_word_count + 1'b1;
                            end
                        end else begin
                            tx_byte_count <= tx_byte_count + 1'b1;
                        end
                    end
                end

                DONE: begin
                    state <= IDLE;
                end

                default: begin
                    state <= BOOT_WAIT_MIG;
                end
            endcase
        end
    end

    // ------------------------------------------------------------
    // DDR+AXI system wrapper (MIG + loader + solver)
    // ------------------------------------------------------------
    admm_ddr_system_wrapper u_ddr_system (
        .DDR3_0_addr(ddr3_addr),
        .DDR3_0_ba(ddr3_ba),
        .DDR3_0_cas_n(ddr3_cas_n),
        .DDR3_0_ck_n(ddr3_ck_n),
        .DDR3_0_ck_p(ddr3_ck_p),
        .DDR3_0_cke(ddr3_cke),
        .DDR3_0_cs_n(ddr3_cs_n),
        .DDR3_0_dm(ddr3_dm),
        .DDR3_0_dq(ddr3_dq),
        .DDR3_0_dqs_n(ddr3_dqs_n),
        .DDR3_0_dqs_p(ddr3_dqs_p),
        .DDR3_0_odt(ddr3_odt),
        .DDR3_0_ras_n(ddr3_ras_n),
        .DDR3_0_reset_n(ddr3_reset_n),
        .DDR3_0_we_n(ddr3_we_n),

        .SPI_0_0_io0_io(qspi_io0_io),
        .SPI_0_0_io1_io(qspi_io1_io),
        .SPI_0_0_ss_io(qspi_ss_io),

        .ddr_ref_clk(sys_clk_i),
        .ddr_sys_rst(resetn),
        .init_calib_complete_0(init_calib_complete_0),
        .ui_clk_0(ui_clk_0),
        .ui_clk_sync_rst_0(ui_clk_sync_rst_0),

        .ap_ctrl_0_start(ap_ctrl_0_start),
        .ap_ctrl_0_done(ap_ctrl_0_done),
        .ap_ctrl_0_idle(ap_ctrl_0_idle),
        .ap_ctrl_0_ready(ap_ctrl_0_ready),

        .ap_ctrl_1_start(ap_ctrl_1_start),
        .ap_ctrl_1_done(ap_ctrl_1_done),
        .ap_ctrl_1_idle(ap_ctrl_1_idle),
        .ap_ctrl_1_ready(ap_ctrl_1_ready),

        .current_in_0(current_in_0),
        .command_out_0(command_out_0),
        .command_out_ap_vld_0(command_out_ap_vld_0),

        .flash_blob_0(flash_blob_0),
        .ddr_blob_0(ddr_blob_0),
        .word_count_0(word_count_0),
        .checksum_out_0(checksum_out_0),
        .checksum_out_ap_vld_0(checksum_out_ap_vld_0),

        .matrix_blob_0(matrix_blob_0),

        .STARTUP_IO_0_cfgclk(startup_cfgclk_unused),
        .STARTUP_IO_0_cfgmclk(startup_cfgmclk_unused),
        .STARTUP_IO_0_eos(startup_eos_unused),
        .STARTUP_IO_0_preq(startup_preq_unused)
    );

    // ------------------------------------------------------------
    // UART RX/TX
    // ------------------------------------------------------------
    uart_rx #(
        .BIT_RATE(BIT_RATE),
        .PAYLOAD_BITS(PAYLOAD_BITS),
        .CLK_HZ(UI_CLK_HZ)
    ) u_uart_rx (
        .clk(ui_clk_0),
        .resetn(core_resetn),
        .uart_rxd(uart_rxd),
        .uart_rx_en(1'b1),
        .uart_rx_break(uart_rx_break),
        .uart_rx_valid(uart_rx_valid),
        .uart_rx_data(uart_rx_data)
    );

    uart_tx #(
        .BIT_RATE(BIT_RATE),
        .PAYLOAD_BITS(PAYLOAD_BITS),
        .CLK_HZ(UI_CLK_HZ)
    ) u_uart_tx (
        .clk(ui_clk_0),
        .resetn(core_resetn),
        .uart_txd(uart_txd),
        .uart_tx_en(uart_tx_en),
        .uart_tx_busy(uart_tx_busy),
        .uart_tx_data(uart_tx_data)
    );

endmodule
