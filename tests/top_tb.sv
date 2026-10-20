`timescale 1ns/1ps
// Register-bank integration test. The separate uart_tb exercises physical framing.
module top_tb;
    reg clk=0;always #5 clk=~clk;
    wire tx;wire [3:0] led;
    reg inject_request=0;
    reg [7:0] inject_opcode=0;
    reg [15:0] inject_length=0;
    reg [255:0] inject_payload=0;
    reg [2047:0] answer;
    reg [15:0] answer_length;
    top_uart_power dut(.clk(clk),.resetn(1'b0),.uart_rxd(1'b1),.uart_txd(tx),.led(led),
        .vsns5v0_p(1'b0),.vsns5v0_n(1'b0),.isns5v0_p(1'b0),.isns5v0_n(1'b0),
        .isns0v95_p(1'b0),.isns0v95_n(1'b0),.vsnsvu_p(1'b0),.vsnsvu_n(1'b0));
    defparam dut.sensor.CAL_CYCLES=100000;
    defparam dut.sensor.SIM_MONITOR_FILE="../../../tests/xadc_analog.txt";
    defparam dut.benchmark.ROM_FILE="../test_workload/power_workload.mem";
    always @(negedge clk) if(dut.active && tx!==1'b1) $fatal(1,"UART TX activity during measurement");
    task command(input [7:0] op,input [15:0] len,input [255:0] data);
        begin
            wait(!dut.uart_busy);repeat(3) @(negedge clk);
            inject_opcode=op;inject_length=len;inject_payload=data;inject_request=1;
            @(negedge clk);inject_request=0;
            wait(dut.response);#1;answer=dut.response_payload;answer_length=dut.response_length;
            @(negedge clk);
        end
    endtask
    initial begin
        force dut.request=inject_request;
        force dut.opcode=inject_opcode;
        force dut.length=inject_length;
        force dut.payload=inject_payload;
        wait(dut.adc_ready);@(negedge clk);
        command(1,0,0);
        if(answer_length!=48 || answer[31:0]!=100000000 || answer[63:32]!=256) $fatal(1,"capabilities");
        command(2,24,{64'd0,32'd1000000,32'd10000,32'd10000,32'd0,32'd0,32'd5});
        if(answer!=0) $fatal(1,"configure rejected");
        command(3,0,0);
        if(answer!=0) $fatal(1,"start rejected");
        wait(dut.finished);@(negedge clk);wait(dut.notified);wait(!dut.uart_busy);repeat(3) @(negedge clk);
        command(4,0,0);
        if(answer_length!=104 || answer[63:32]!=0 || answer[95:64]!=5 || !answer[1]) $fatal(1,"completion status");
        command(5,4,0);
        if(answer_length!=64 || answer[471:464]!=1 || answer[127:96]==0) $fatal(1,"idle trace readout");
        command(5,4,512);
        if(answer_length!=64 || answer[471:464]!=2 || answer[127:96]==0) $fatal(1,"active trace readout");
        command(5,4,1536);
        if(answer_length!=64 || answer[471:464]!=3 || answer[127:96]==0) $fatal(1,"post trace readout");
        command(3,0,0);
        if(answer_length!=4 || answer[31:0]!=1) $fatal(1,"repeat start not rejected");
        $display("PASS top integration: configuration, quiet capture, real HLS/XADC, BRAM readout, completion");$finish;
    end
    initial begin #50000000;$fatal(1,"top integration timeout");end
endmodule
