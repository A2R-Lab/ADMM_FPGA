`timescale 1ns/1ps
module uart_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,rx=1,quiet=0,response=0;
    wire tx,req,busy;wire [7:0] op;wire [15:0] len;wire [255:0] payload;
    wire out_valid;wire [7:0] out_byte;
    reg [7:0] received[0:31];integer nr=0,requests=0;
    power_uart dut(.clk(clk),.rst(rst),.quiet(quiet),.uart_rxd(rx),.uart_txd(tx),.request(req),
        .opcode(op),.length(len),.payload(payload),.response(response),.response_opcode(8'h82),
        .response_length(16'd3),.response_payload(2048'h332211),.busy(busy));
    uart_rx #(.CLK_HZ(100000000),.BIT_RATE(921600)) monitor(.clk(clk),.resetn(!rst),.uart_rxd(tx),
        .uart_rx_en(1'b1),.uart_rx_break(),.uart_rx_valid(out_valid),.uart_rx_data(out_byte));
    always @(posedge clk) begin
        response<=0;
        if(req) begin
            requests<=requests+1;
            if(op!=2 || len!=3 || payload[23:0]!=24'h332211) $fatal(1,"request decode");
            response<=1;
        end
        if(out_valid) begin received[nr]<=out_byte;nr<=nr+1;end
    end
    function [15:0] crc(input [15:0] c0,input [7:0] b);
        reg [15:0] c;integer j;
        begin c=c0^{b,8'h00};for(j=0;j<8;j=j+1)c=c[15]?(c<<1)^16'h1021:c<<1;crc=c;end
    endfunction
    task sendbyte(input [7:0] b);
        integer j;
        begin
            @(negedge clk);rx=0;repeat(108) @(negedge clk);
            for(j=0;j<8;j=j+1)begin rx=b[j];repeat(108) @(negedge clk);end
            rx=1;repeat(108) @(negedge clk);
        end
    endtask
    task packet(input integer corrupt);
        reg [15:0] c;
        begin
            c=16'hffff;sendbyte(8'ha5);sendbyte(8'h5a);
            sendbyte(1);c=crc(c,1);sendbyte(2);c=crc(c,2);sendbyte(3);c=crc(c,3);sendbyte(0);c=crc(c,0);
            sendbyte(8'h11);c=crc(c,8'h11);sendbyte(8'h22);c=crc(c,8'h22);sendbyte(8'h33);c=crc(c,8'h33);
            sendbyte(c[7:0]^corrupt);sendbyte(c[15:8]);
        end
    endtask
    integer j;reg [15:0] expected;
    initial begin
        repeat(20) @(negedge clk);rst=0;
        packet(1);repeat(1000) @(negedge clk);if(requests!=0)$fatal(1,"bad CRC accepted");
        quiet=1;packet(0);quiet=0;repeat(1000) @(negedge clk);if(requests!=0)$fatal(1,"quiet RX accepted");
        packet(0);wait(nr==11);repeat(100) @(negedge clk);
        if(requests!=1 || received[0]!=8'ha5 || received[1]!=8'h5a || received[2]!=1 || received[3]!=8'h82 || received[4]!=3 || received[5]!=0 || received[6]!=8'h11 || received[7]!=8'h22 || received[8]!=8'h33)$fatal(1,"response framing");
        expected=16'hffff;for(j=2;j<9;j=j+1)expected=crc(expected,received[j]);
        if({received[10],received[9]}!=expected)$fatal(1,"response CRC");
        $display("PASS UART: physical serial framing, CRC rejection, quiet mode, response");$finish;
    end
    initial begin #3000000;$fatal(1,"UART timeout requests=%d bytes=%d",requests,nr);end
endmodule
