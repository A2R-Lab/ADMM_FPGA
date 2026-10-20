`timescale 1ns/1ps
module xadc_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst=1;wire valid,ready,fault;
    wire [11:0] vc,ic,v5,i5,temp;
    power_xadc #(.CAL_CYCLES(100000),.SIM_MONITOR_FILE("tests/xadc_analog.txt")) dut(
        .clk(clk),.rst(rst),.vsns5v0_p(1'b0),.vsns5v0_n(1'b0),.isns5v0_p(1'b0),.isns5v0_n(1'b0),
        .isns0v95_p(1'b0),.isns0v95_n(1'b0),.vsnsvu_p(1'b0),.vsnsvu_n(1'b0),
        .valid(valid),.ready(ready),.fault(fault),.vcore(vc),.icore(ic),.v5(v5),.i5(i5),.temperature(temp));
    integer samples=0;
    initial begin repeat(20) @(negedge clk);rst=0;end
    always @(negedge clk) if(valid) begin
        if(fault || !ready) $fatal(1,"ADC fault");
        if(vc<1360 || vc>1370 || ic<1020 || ic>1028 || v5<3272 || v5>3280 || i5<508 || i5>516 || temp<2418 || temp>2428)
            $fatal(1,"ADC scaling/channel mismatch vc=%d ic=%d v5=%d i5=%d temp=%d",vc,ic,v5,i5,temp);
        samples=samples+1;
        if(samples==20) begin $display("PASS XADC: real UNISIM calibration, sequencer, DRP, channel values");$finish;end
    end
    initial begin #3000000;$fatal(1,"ADC timeout");end
endmodule
