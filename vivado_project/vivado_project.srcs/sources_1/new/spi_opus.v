`timescale 1ns/1ps

module SPI_Slave_opus #(
    parameter SPI_MODE = 0
)(
    // Control/Data Signals
    input            i_Rst_L,       // FPGA Reset, active low
    input            i_Clk,         // FPGA Clock
    output reg       o_RX_DV,       // Data Valid pulse (1 clock cycle)
    output reg [7:0] o_RX_Byte,     // Byte received on MOSI
    input            i_TX_DV,       // Data Valid pulse to register i_TX_Byte
    input  [7:0]     i_TX_Byte,     // Byte to serialize to MISO
    output reg       o_TX_Ready,    // Ready to accept new TX byte
    
    // SPI Interface
    input            i_SPI_Clk,
    output           o_SPI_MISO,
    input            i_SPI_MOSI,
    input            i_SPI_CS_n     // active low
);

    // SPI Mode decoding
    wire w_CPOL = (SPI_MODE == 2) | (SPI_MODE == 3);
    wire w_CPHA = (SPI_MODE == 1) | (SPI_MODE == 3);
    
    // Clock edge selection based on mode
    wire w_SPI_Clk_Rx = w_CPHA ? ~i_SPI_Clk : i_SPI_Clk;   // Sample edge
    wire w_SPI_Clk_Tx = w_CPHA ? i_SPI_Clk : ~i_SPI_Clk;   // Shift edge
    
    // RX signals (SPI clock domain)
    reg [2:0] r_RX_Bit_Count;
    reg [7:0] r_Temp_RX_Byte;
    reg [7:0] r_RX_Byte;
    reg       r_RX_Done;
    
    // TX signals (SPI clock domain)
    reg [2:0] r_TX_Bit_Count;
    reg [7:0] r_TX_Byte;
    reg       r_SPI_MISO_Bit;
    reg       r_TX_Loaded;
    
    // Clock domain crossing for RX
    reg r2_RX_Done, r3_RX_Done;
    
    // Clock domain crossing for TX load
    reg [7:0] r_TX_Byte_Sync;
    reg       r_TX_DV_Sync1, r_TX_DV_Sync2;
    reg       r_TX_Load_Pending;
    
    // CS synchronization
    reg r_CS_Sync1, r_CS_Sync2, r_CS_Sync3;
    wire w_CS_Fall, w_CS_Rise;
    
    // Synchronize CS to FPGA clock domain
    always @(posedge i_Clk or negedge i_Rst_L) begin
        if (~i_Rst_L) begin
            r_CS_Sync1 <= 1'b1;
            r_CS_Sync2 <= 1'b1;
            r_CS_Sync3 <= 1'b1;
        end else begin
            r_CS_Sync1 <= i_SPI_CS_n;
            r_CS_Sync2 <= r_CS_Sync1;
            r_CS_Sync3 <= r_CS_Sync2;
        end
    end
    
    assign w_CS_Fall = r_CS_Sync3 & ~r_CS_Sync2;
    assign w_CS_Rise = ~r_CS_Sync3 & r_CS_Sync2;

    //--------------------------------------------------------------------------
    // RX: Receive data from master (SPI Clock Domain)
    //--------------------------------------------------------------------------
    always @(posedge w_SPI_Clk_Rx or posedge i_SPI_CS_n) begin
        if (i_SPI_CS_n) begin
            r_RX_Bit_Count <= 3'd0;
            r_RX_Done      <= 1'b0;
            r_Temp_RX_Byte <= 8'd0;
        end else begin
            // Shift in MSB first
            r_Temp_RX_Byte <= {r_Temp_RX_Byte[6:0], i_SPI_MOSI};
            r_RX_Bit_Count <= r_RX_Bit_Count + 1'b1;
            
            if (r_RX_Bit_Count == 3'd7) begin
                r_RX_Done <= 1'b1;
                r_RX_Byte <= {r_Temp_RX_Byte[6:0], i_SPI_MOSI};
            end else if (r_RX_Bit_Count == 3'd2) begin
                r_RX_Done <= 1'b0;
            end
        end
    end

    //--------------------------------------------------------------------------
    // RX: Cross to FPGA clock domain
    //--------------------------------------------------------------------------
    always @(posedge i_Clk or negedge i_Rst_L) begin
        if (~i_Rst_L) begin
            r2_RX_Done <= 1'b0;
            r3_RX_Done <= 1'b0;
            o_RX_DV    <= 1'b0;
            o_RX_Byte  <= 8'h00;
        end else begin
            r2_RX_Done <= r_RX_Done;
            r3_RX_Done <= r2_RX_Done;
            
            // Rising edge detection
            if (~r3_RX_Done && r2_RX_Done) begin
                o_RX_DV   <= 1'b1;
                o_RX_Byte <= r_RX_Byte;
            end else begin
                o_RX_DV <= 1'b0;
            end
        end
    end

    //--------------------------------------------------------------------------
    // TX: Load byte from FPGA clock domain
    //--------------------------------------------------------------------------
    always @(posedge i_Clk or negedge i_Rst_L) begin
        if (~i_Rst_L) begin
            r_TX_Byte_Sync   <= 8'h00;
            r_TX_Load_Pending <= 1'b0;
            o_TX_Ready       <= 1'b1;
        end else begin
            if (i_TX_DV && o_TX_Ready) begin
                r_TX_Byte_Sync    <= i_TX_Byte;
                r_TX_Load_Pending <= 1'b1;
                o_TX_Ready        <= 1'b0;
            end
            
            // Ready for new byte after current one starts transmitting
            if (r_TX_Bit_Count == 3'd0 && !i_SPI_CS_n) begin
                o_TX_Ready <= 1'b1;
                r_TX_Load_Pending <= 1'b0;
            end
            
            // Also ready when CS goes high
            if (w_CS_Rise) begin
                o_TX_Ready <= 1'b1;
            end
        end
    end

    //--------------------------------------------------------------------------
    // TX: Transmit data to master (SPI Clock Domain - falling edge for Mode 0)
    //--------------------------------------------------------------------------
    always @(negedge w_SPI_Clk_Rx or posedge i_SPI_CS_n) begin
        if (i_SPI_CS_n) begin
            r_TX_Bit_Count <= 3'd7;
            r_TX_Byte      <= r_TX_Byte_Sync;  // Preload
            r_SPI_MISO_Bit <= r_TX_Byte_Sync[7];
        end else begin
            if (r_TX_Bit_Count == 3'd0) begin
                // Load next byte
                r_TX_Byte      <= r_TX_Byte_Sync;
                r_TX_Bit_Count <= 3'd7;
                r_SPI_MISO_Bit <= r_TX_Byte_Sync[7];
            end else begin
                r_TX_Bit_Count <= r_TX_Bit_Count - 1'b1;
                r_SPI_MISO_Bit <= r_TX_Byte[r_TX_Bit_Count - 1'b1];
            end
        end
    end

    // Tri-state MISO when CS is high
    assign o_SPI_MISO = i_SPI_CS_n ? 1'bZ : r_SPI_MISO_Bit;

endmodule