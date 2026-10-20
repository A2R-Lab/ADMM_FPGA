`timescale 1ns/1ps
module benchmark_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,start=0,done=0,idle=1,valid=0;
    reg [127:0] result=0;
    wire [417:0] input_bits; wire go,active,finished,used;
    wire [1:0] phase;wire [63:0] tick,bc,lt,ac;
    wire [31:0] flags,n,overruns,checksum,lmin,lmax;wire [127:0] last;
    reg [31:0] period=0,wd=100;reg stall=0;
    integer remaining=0,calls=0;
    reg [31:0] expected=0;
    power_benchmark #(.RECORDS(2),.ROM_FILE("build/power/test_workload/power_workload.mem")) dut(.clk(clk),.rst(rst),.start(start),.adc_ready(1'b1),.adc_fault(1'b0),
        .capture_fault(1'b0),.capture_busy(1'b0),.solves(32'd5),.period_cycles(period),.settle_cycles(32'd10),
        .pre_cycles(32'd20),.post_cycles(32'd20),.watchdog_cycles(wd),.phase(phase),.tick(tick),.active(active),
        .finished(finished),.used(used),.flags(flags),.ap_start(go),.ap_idle(idle),.ap_done(done),.output_valid(valid),
        .solver_input(input_bits),.solver_output(result),.completed(n),.overruns(overruns),.checksum(checksum),
        .busy_cycles(bc),.latency_total(lt),.active_cycles(ac),.latency_min(lmin),.latency_max(lmax),.last_output(last));
    reg [417:0] rom[0:255];initial $readmemh("build/power/test_workload/power_workload.mem",rom);
    always @(posedge clk) begin
        done<=0; valid<=0;
        if(rst) begin idle<=1;remaining<=0;calls<=0;expected<=0; end
        else if(go) begin
            if(!idle || input_bits!==rom[calls%2]) $fatal(1,"overlap or wrong ROM input");
            idle<=0;remaining<=7;calls<=calls+1;
            result<=input_bits[127:0]^calls;
            expected<={expected[30:0],expected[31]}^input_bits[31:0]^input_bits[63:32]^input_bits[95:64]^input_bits[127:96]^calls;
        end else if(remaining!=0 && !stall) begin
            remaining<=remaining-1;
            if(remaining==1) begin done<=1;valid<=1;idle<=1;end
        end
    end
    task run(input integer p,input integer w,input integer hanging);
        begin
            @(negedge clk);rst=1;period=p;wd=w;stall=hanging;
            repeat(4) @(negedge clk);rst=0;
            repeat(4) @(negedge clk);start=1;
            @(negedge clk);start=0;
            wait(finished);@(negedge clk);
            if(hanging) begin if(flags!=1 || n!=0) $fatal(1,"watchdog");end
            else begin
                if(n!=5 || flags!=0 || checksum!==expected || lmin!=lmax) $fatal(1,"benchmark counters/output");
                if(p==3 && overruns==0) $fatal(1,"missing overrun");
                if(p==40 && overruns!=0) $fatal(1,"false overrun");
            end
        end
    endtask
    initial begin
        run(0,100,0);run(40,100,0);run(3,100,0);run(0,10,1);
        $display("PASS benchmark: ROM replay, outputs, periodic scheduling, overruns, watchdog");$finish;
    end
    initial begin #100000;$fatal(1,"timeout");end
endmodule
