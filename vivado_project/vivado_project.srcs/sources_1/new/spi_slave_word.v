`timescale 1ns/1ps

module spi_slave_word #(
    parameter WORD_WIDTH = 24
)(
    input  wire clk,
    input  wire resetn,
    
    // SPI interface
    input  wire spi_sck,
    input  wire spi_mosi,
    output reg  spi_miso,
    input  wire spi_cs_n,
    
    // Received data interface
    output reg [WORD_WIDTH-1:0] rx_data,
    output reg rx_valid,
    
    // Transmit data interface
    input  wire [WORD_WIDTH-1:0] tx_data,
    input  wire tx_load,
    output reg tx_ready
);

    //--------------------------------------------------------------
    // Synchronizers for SPI signals
    //--------------------------------------------------------------
    reg sck_sync1, sck_sync2, sck_sync3;
    reg mosi_sync1, mosi_sync2;
    reg cs_sync1, cs_sync2;
    
    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            {sck_sync3, sck_sync2, sck_sync1} <= 3'b000;
            {mosi_sync2, mosi_sync1} <= 2'b00;
            {cs_sync2, cs_sync1} <= 2'b11;
        end else begin
            {sck_sync3, sck_sync2, sck_sync1} <= {sck_sync2, sck_sync1, spi_sck};
            {mosi_sync2, mosi_sync1} <= {mosi_sync1, spi_mosi};
            {cs_sync2, cs_sync1} <= {cs_sync1, spi_cs_n};
        end
    end
    
    // Edge detection
    wire sck_rising  = sck_sync2 && !sck_sync3;
    wire sck_falling = !sck_sync2 && sck_sync3;
    wire cs_active   = !cs_sync2;
    
    //--------------------------------------------------------------
    // Buffers and Shift Registers
    //--------------------------------------------------------------
    reg [WORD_WIDTH-1:0] rx_shift;
    reg [WORD_WIDTH-1:0] tx_shift;
    reg [WORD_WIDTH-1:0] tx_buffer; // Shadow register per trasmissione sicura
    reg [$clog2(WORD_WIDTH):0] bit_cnt;
    
    //--------------------------------------------------------------
    // TX Buffer Logic (Shadow Register)
    //--------------------------------------------------------------
    // Carichiamo il buffer in qualsiasi momento la FSM lo richieda.
    // Questo non disturba la trasmissione in corso.
    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            tx_buffer <= 0;
        end else begin
            if (tx_load) begin
                tx_buffer <= tx_data;
            end
        end
    end

    //--------------------------------------------------------------
    // Main SPI Logic
    //--------------------------------------------------------------
    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            rx_shift <= 0;
            tx_shift <= 0;
            bit_cnt <= 0;
            rx_data <= 0;
            rx_valid <= 0;
            tx_ready <= 0;
            spi_miso <= 0;
        end else begin
            // Default signals
            rx_valid <= 0;
            tx_ready <= 0;
            
            if (!cs_active) begin
                // CS inactive - reset counters and preload first word
                bit_cnt <= 0;
                // Quando CS non è attivo, prepariamo il registro shift con il dato corrente nel buffer
                // così siamo pronti per il primissimo bit appena CS va basso.
                tx_shift <= tx_buffer; 
            end else begin
                // CS active - shift data
                
                if (sck_rising) begin
                    // Shift in on rising edge (SPI Mode 0/3 sampling)
                    rx_shift <= {rx_shift[WORD_WIDTH-2:0], mosi_sync2};
                    bit_cnt <= bit_cnt + 1;
                    
                    // Word complete logic
                    if (bit_cnt == WORD_WIDTH-1) begin
                        // 1. Output received data
                        rx_data <= {rx_shift[WORD_WIDTH-2:0], mosi_sync2};
                        rx_valid <= 1;
                        
                        // 2. Reset counter for next word
                        bit_cnt <= 0;
                        
                        // 3. Signal FSM that we are done with this word
                        tx_ready <= 1;  
                        
                        // 4. LOAD NEXT WORD: Trasferiamo dal buffer allo shift register
                        // tra una parola e l'altra. Questo è il momento sicuro.
                        tx_shift <= tx_buffer;
                    end
                end
                
                if (sck_falling) begin
                    // Shift out on falling edge
                    spi_miso <= tx_shift[WORD_WIDTH-1];
                    tx_shift <= {tx_shift[WORD_WIDTH-2:0], 1'b0};
                end
            end
        end
    end

endmodule