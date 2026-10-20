`timescale 1ns/1ps
module power_benchmark #(
    parameter ROM_FILE="build/power/power_workload.mem", RECORDS=256,
    parameter MAX_CYCLES=64'd60000000000
)(
    input wire clk, rst, start, adc_ready, adc_fault, capture_fault, capture_busy,
    input wire [31:0] solves, period_cycles, settle_cycles, pre_cycles, post_cycles, watchdog_cycles,
    output reg [1:0] phase=0,
    output reg [63:0] tick=0,
    output wire active,
    output reg finished=0, used=0,
    output reg [31:0] flags=0,
    output reg ap_start=0,
    input wire ap_idle, ap_done, output_valid,
    output reg [417:0] solver_input=0,
    input wire [127:0] solver_output,
    output reg [31:0] completed=0, overruns=0, checksum=0,
    output reg [63:0] busy_cycles=0, latency_total=0, active_cycles=0,
    output reg [31:0] latency_min=32'hffffffff, latency_max=0,
    output reg [127:0] last_output=0
);
    (* rom_style="block" *) reg [417:0] rom[0:255];
    initial $readmemh(ROM_FILE,rom);
    reg [7:0] rom_addr=0;
    reg rom_fetch=1;
    always @(posedge clk) if(rom_fetch) solver_input<=rom[rom_addr];
    reg [2:0] state=0;
    reg [63:0] deadline=0, next_launch=0, launched_at=0;
    reg running=0, have_output=0;
    wire [63:0] latency=tick-launched_at+1;
    assign active=(state!=0 && state!=5);
    always @(posedge clk) begin
        ap_start<=0; rom_fetch<=0;
        if(rst) begin
            state<=0; phase<=0; tick<=0; flags<=0; used<=0; finished<=0;
            completed<=0; overruns<=0; checksum<=0; busy_cycles<=0; latency_total<=0;
            active_cycles<=0; latency_min<=32'hffffffff; latency_max<=0;
            running<=0; have_output<=0; rom_addr<=0; rom_fetch<=1; last_output<=0;
        end else begin
            if(active) tick<=tick+1;
            case(state)
                0: if(start && !used) begin
                    used<=1; tick<=0;
                    if(adc_ready && !adc_fault) begin state<=1; deadline<=settle_cycles; end
                    else begin flags<=2; state<=4; end
                end
                1: if(tick>=deadline) begin state<=2; phase<=1; deadline<=tick+pre_cycles; end
                2: if(tick>=deadline) begin state<=3; phase<=2; next_launch<=tick+1; end
                3: begin
                    active_cycles<=active_cycles+1;
                    if(running) busy_cycles<=busy_cycles+1;
                    if(period_cycles!=0 && tick>=next_launch) begin
                        next_launch<=next_launch+period_cycles;
                        if(running || !ap_idle) overruns<=overruns+1;
                    end
                    if(!running && ap_idle && (period_cycles==0 || tick>=next_launch)) begin
                        ap_start<=1; running<=1; have_output<=0; launched_at<=tick+1;
                    end
                    if(running && output_valid) begin last_output<=solver_output; have_output<=1; end
                    if(running && ap_done) begin
                        if(!have_output && !output_valid) begin flags<=flags|32'h10; state<=4; phase<=0; end
                        else begin
                            completed<=completed+1; running<=0;
                            latency_total<=latency_total+latency;
                            if(latency<latency_min) latency_min<=latency[31:0];
                            if(latency>latency_max) latency_max<=latency[31:0];
                            checksum<={checksum[30:0],checksum[31]} ^
                                (output_valid ? (solver_output[31:0]^solver_output[63:32]^solver_output[95:64]^solver_output[127:96]) :
                                (last_output[31:0]^last_output[63:32]^last_output[95:64]^last_output[127:96]));
                            rom_addr<=(rom_addr==RECORDS-1)?0:rom_addr+1; rom_fetch<=1;
                            if(completed+1==solves) begin state<=6; phase<=3; deadline<=tick+post_cycles; end
                        end
                    end
                    if(running && tick-launched_at>=watchdog_cycles && tick>=launched_at) begin flags<=flags|1; state<=4; phase<=0; end
                end
                6: if(tick>=deadline) begin phase<=0; state<=4; end
                4: if(!capture_busy) begin state<=5; finished<=1; end
            endcase
            if(active && state!=4 && (adc_fault || capture_fault || tick>=MAX_CYCLES)) begin
                flags<=flags | (adc_fault?32'h2:0) | (capture_fault?32'h4:0) | (tick>=MAX_CYCLES?32'h8:0);
                phase<=0; state<=4; running<=0;
            end
        end
    end
endmodule
