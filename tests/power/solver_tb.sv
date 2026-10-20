`timescale 1ns/1ps
module solver_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,start=0;
    wire go,done,idle,valid,finished;
    wire [417:0] input_bits;wire [127:0] result;
    wire [31:0] flags,n,lmin,lmax;
    reg [127:0] golden[0:4];integer seen=0;
    initial $readmemh("../golden.mem",golden);
    ADMM_solver solver(.ap_clk(clk),.ap_rst(rst),.ap_start(go),.ap_done(done),.ap_idle(idle),.ap_ready(),
        .current_in_bits(input_bits),.command_out_bits(result),.command_out_bits_ap_vld(valid));
    power_benchmark #(.ROM_FILE("../test_workload/power_workload.mem"),.RECORDS(256)) dut(
        .clk(clk),.rst(rst),.start(start),.adc_ready(1'b1),.adc_fault(1'b0),.capture_fault(1'b0),.capture_busy(1'b0),
        .solves(32'd5),.period_cycles(32'd0),.settle_cycles(32'd10),.pre_cycles(32'd20),.post_cycles(32'd20),
        .watchdog_cycles(32'd1000000),.phase(),.tick(),.active(),.finished(finished),.used(),.flags(flags),
        .ap_start(go),.ap_idle(idle),.ap_done(done),.output_valid(valid),.solver_input(input_bits),.solver_output(result),
        .completed(n),.overruns(),.checksum(),.busy_cycles(),.latency_total(),.active_cycles(),
        .latency_min(lmin),.latency_max(lmax),.last_output());
    always @(negedge clk) if(valid) begin
        if(result!==golden[seen]) $fatal(1,"HLS mismatch solve %d got %h expected %h",seen,result,golden[seen]);
        seen=seen+1;
    end
    initial begin
        repeat(20) @(negedge clk);rst=0;repeat(10) @(negedge clk);start=1;
        @(negedge clk);start=0;wait(finished);@(negedge clk);
        if(flags || n!=5 || seen!=5 || lmin!=lmax) $fatal(1,"HLS completion/latency");
        $display("PASS real HLS: five warm-started solves match C++ bit-for-bit; latency=%d clocks",lmin);$finish;
    end
    initial begin #50000000;$fatal(1,"HLS simulation timeout");end
endmodule
