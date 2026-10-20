`timescale 1ns/1ps
// A5 5A, version=1, opcode, uint16 payload bytes, payload, CRC16-CCITT LE.
// CRC covers version through payload, init FFFF, polynomial 1021.
module power_uart #(parameter CLK_HZ=100000000, BAUD=921600)(
    input wire clk, rst, quiet, uart_rxd,
    output wire uart_txd,
    output reg request=0,
    output reg [7:0] opcode=0,
    output reg [15:0] length=0,
    output reg [255:0] payload=0,
    input wire response,
    input wire [7:0] response_opcode,
    input wire [15:0] response_length,
    input wire [2047:0] response_payload,
    output wire busy
);
    function automatic [15:0] crc_byte(input [15:0] crc,input [7:0] b);
        reg [15:0] c; integer j;
        begin c=crc^{b,8'b0}; for(j=0;j<8;j=j+1) c=c[15]?(c<<1)^16'h1021:c<<1; crc_byte=c; end
    endfunction
    wire rx_valid, tx_busy;
    wire [7:0] rx;
    reg tx_en=0; reg [7:0] tx_byte=0;
    uart_rx #(.CLK_HZ(CLK_HZ),.BIT_RATE(BAUD)) receiver(
        .clk(clk),.resetn(!rst),.uart_rxd(uart_rxd),.uart_rx_en(1'b1),
        .uart_rx_break(),.uart_rx_valid(rx_valid),.uart_rx_data(rx));
    uart_tx #(.CLK_HZ(CLK_HZ),.BIT_RATE(BAUD)) transmitter(
        .clk(clk),.resetn(!rst),.uart_txd(uart_txd),.uart_tx_en(tx_en),
        .uart_tx_data(tx_byte),.uart_tx_busy(tx_busy));
    reg [3:0] rx_state=0;
    reg [15:0] rx_crc=16'hffff;
    reg [7:0] crc_low=0;
    reg [5:0] rx_index=0;
    reg [31:0] timeout_count=0;
    reg sending=0;
    reg [15:0] tx_index=0, tx_length=0, tx_crc=16'hffff;
    reg [7:0] tx_opcode=0;
    reg [2047:0] tx_payload=0;
    reg [7:0] next_byte;
    assign busy=sending||tx_busy||tx_en;
    always @* begin
        case(tx_index)
            0: next_byte=8'ha5;
            1: next_byte=8'h5a;
            2: next_byte=1;
            3: next_byte=tx_opcode;
            4: next_byte=tx_length[7:0];
            5: next_byte=tx_length[15:8];
            default: if(tx_index<tx_length+6) next_byte=tx_payload[(tx_index-6)*8+:8];
                else if(tx_index==tx_length+6) next_byte=tx_crc[7:0];
                else next_byte=tx_crc[15:8];
        endcase
    end
    always @(posedge clk) begin
        request<=0; tx_en<=0;
        if(rst) begin rx_state<=0; sending<=0; timeout_count<=0; end
        else begin
            if(response && !busy) begin
                sending<=1; tx_index<=0; tx_length<=response_length;
                tx_opcode<=response_opcode; tx_payload<=response_payload; tx_crc<=16'hffff;
            end
            if(sending && !tx_busy && !tx_en) begin
                tx_byte<=next_byte; tx_en<=1;
                if(tx_index>=2 && tx_index<tx_length+6) tx_crc<=crc_byte(tx_crc,next_byte);
                if(tx_index==tx_length+7) sending<=0;
                else tx_index<=tx_index+1;
            end
            if(quiet || busy) begin rx_state<=0; timeout_count<=0; end
            else if(rx_valid) begin
                timeout_count<=0;
                case(rx_state)
                    0: if(rx==8'ha5) rx_state<=1;
                    1: if(rx==8'h5a) rx_state<=2; else if(rx!=8'ha5) rx_state<=0;
                    2: if(rx==1) begin rx_crc<=crc_byte(16'hffff,rx); rx_state<=3; end else rx_state<=0;
                    3: begin opcode<=rx; rx_crc<=crc_byte(rx_crc,rx); rx_state<=4; end
                    4: begin length[7:0]<=rx; rx_crc<=crc_byte(rx_crc,rx); rx_state<=5; end
                    5: begin
                        length[15:8]<=rx; rx_crc<=crc_byte(rx_crc,rx); rx_index<=0; payload<=0;
                        if(rx!=0 || length[7:0]>32) rx_state<=0;
                        else rx_state<=(length[7:0]==0)?7:6;
                    end
                    6: begin
                        payload[rx_index*8+:8]<=rx; rx_crc<=crc_byte(rx_crc,rx);
                        if(rx_index+1==length) rx_state<=7; else rx_index<=rx_index+1;
                    end
                    7: begin crc_low<=rx; rx_state<=8; end
                    8: begin if({rx,crc_low}==rx_crc) request<=1; rx_state<=0; end
                endcase
            end else if(rx_state!=0) begin
                timeout_count<=timeout_count+1;
                if(timeout_count==CLK_HZ/10) begin rx_state<=0; timeout_count<=0; end
            end
        end
    end
endmodule
