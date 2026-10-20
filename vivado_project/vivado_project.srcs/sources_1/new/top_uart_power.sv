`timescale 1ns/1ps
`include "power_workload.vh"
module top_uart_power(
    input wire clk, resetn, uart_rxd,
    output wire uart_txd,
    output wire [3:0] led,
    input wire vsns5v0_p, vsns5v0_n, isns5v0_p, isns5v0_n,
    input wire isns0v95_p, isns0v95_n, vsnsvu_p, vsnsvu_n
);
    // Arty BTN0 is active HIGH despite the historical resetn port name.
    reg [15:0] por=16'hffff;
    (* ASYNC_REG="TRUE" *) reg [1:0] reset_sync=3;
    always @(posedge clk) begin por<={por[14:0],1'b0}; reset_sync<={reset_sync[0],resetn}; end
    wire rst=|por || reset_sync[1];
    assign led=4'b0001;
    wire sample_valid, adc_ready, adc_fault;
    wire [11:0] vcore,icore,v5,i5,temperature;
    power_xadc sensor(.clk(clk),.rst(rst),.vsns5v0_p(vsns5v0_p),.vsns5v0_n(vsns5v0_n),
        .isns5v0_p(isns5v0_p),.isns5v0_n(isns5v0_n),.isns0v95_p(isns0v95_p),.isns0v95_n(isns0v95_n),
        .vsnsvu_p(vsnsvu_p),.vsnsvu_n(vsnsvu_n),.valid(sample_valid),.ready(adc_ready),.fault(adc_fault),
        .vcore(vcore),.icore(icore),.v5(v5),.i5(i5),.temperature(temperature));
    reg start=0;
    reg notified=0;
    reg [31:0] solves=1000, period_cycles=0, settle_cycles=200000000,
        pre_cycles=300000000, post_cycles=300000000, watchdog_cycles=1000000000;
    wire [1:0] phase;
    wire [63:0] tick,busy_cycles,latency_total,active_cycles;
    wire active,finished,used,capture_busy,capture_fault;
    wire [31:0] flags,completed,overruns,checksum,latency_min,latency_max;
    wire [127:0] last_output,solver_output;
    wire [417:0] solver_input;
    wire ap_start,ap_done,ap_idle,output_valid;
    ADMM_solver solver(.ap_clk(clk),.ap_rst(rst || flags!=0),.ap_start(ap_start),.ap_done(ap_done),
        .ap_idle(ap_idle),.ap_ready(),.current_in_bits(solver_input),.command_out_bits(solver_output),
        .command_out_bits_ap_vld(output_valid));
    power_benchmark #(.RECORDS(`POWER_WORKLOAD_COUNT)) benchmark(
        .clk(clk),.rst(rst),.start(start),.adc_ready(adc_ready),.adc_fault(adc_fault),
        .capture_fault(capture_fault),.capture_busy(capture_busy),.solves(solves),.period_cycles(period_cycles),
        .settle_cycles(settle_cycles),.pre_cycles(pre_cycles),.post_cycles(post_cycles),.watchdog_cycles(watchdog_cycles),
        .phase(phase),.tick(tick),.active(active),.finished(finished),.used(used),.flags(flags),
        .ap_start(ap_start),.ap_idle(ap_idle),.ap_done(ap_done),.output_valid(output_valid),
        .solver_input(solver_input),.solver_output(solver_output),.completed(completed),.overruns(overruns),
        .checksum(checksum),.busy_cycles(busy_cycles),.latency_total(latency_total),.active_cycles(active_cycles),
        .latency_min(latency_min),.latency_max(latency_max),.last_output(last_output));
    reg [10:0] read_addr=0;
    wire capture_read_enable;
    wire [511:0] read_data;
    wire [10:0] pre_count,active_count,post_count;
    power_capture capture(.clk(clk),.rst(rst),.phase(phase),.tick(tick),.sample_valid(sample_valid),
        .vcore(vcore),.icore(icore),.v5(v5),.i5(i5),.temperature(temperature),
        .read_addr(read_addr),.read_enable(capture_read_enable),.read_data(read_data),.pre_count(pre_count),.active_count(active_count),
        .post_count(post_count),.busy(capture_busy),.fault(capture_fault));
    wire request,uart_busy;
    wire [7:0] opcode;
    wire [15:0] length;
    wire [255:0] payload;
    reg response=0;
    reg [7:0] response_opcode=0;
    reg [15:0] response_length=0;
    reg [2047:0] response_payload=0;
    reg [3:0] read_wait=0;
    assign capture_read_enable=read_wait!=0;
    reg [31:0] start_delay=0;
    wire quiet=active || start_delay!=0;
    power_uart comm(.clk(clk),.rst(rst),.quiet(quiet),.uart_rxd(uart_rxd),.uart_txd(uart_txd),
        .request(request),.opcode(opcode),.length(length),.payload(payload),.response(response),
        .response_opcode(response_opcode),.response_length(response_length),.response_payload(response_payload),.busy(uart_busy));
    always @(posedge clk) begin
        response<=0; start<=0;
        if(rst) begin
            start_delay<=0; read_wait<=0; notified<=0;
            solves<=1000; period_cycles<=0; settle_cycles<=200000000;
            pre_cycles<=300000000; post_cycles<=300000000; watchdog_cycles<=1000000000;
        end else begin
            if(finished && !notified && !uart_busy) begin
                response<=1; response_opcode<=8'h86; response_length<=4;
                response_payload<=flags; notified<=1;
            end
            if(start_delay!=0) begin
                start_delay<=start_delay-1;
                if(start_delay==1) start<=1;
            end
            if(read_wait!=0) begin
                read_wait<=read_wait-1;
                if(read_wait==1) begin response_payload<=read_data; response_length<=64; response<=1; end
            end
            if(request && !quiet && read_wait==0) begin
                response<=1; response_opcode<=opcode|8'h80; response_length<=4; response_payload<=0;
                case(opcode)
                    1: if(length==0) begin
                        response_length<=48;
                        response_payload[31:0]<=100000000;
                        response_payload[63:32]<=`POWER_WORKLOAD_COUNT;
                        response_payload[95:64]<=`POWER_USE_FLOAT;
                        response_payload[127:96]<=64;
                        response_payload[383:128]<=`POWER_WORKLOAD_HASH;
                    end else response_payload<=1;
                    2: if(length!=24 || used || payload[31:0]==0 || payload[127:96]==0 || payload[159:128]==0 ||
                              payload[191:160]==0 || payload[95:64]>3000000000 || payload[127:96]>3000000000 ||
                              payload[159:128]>3000000000 || payload[191:160]>1000000000) response_payload<=1;
                       else begin
                           solves<=payload[31:0]; period_cycles<=payload[63:32]; settle_cycles<=payload[95:64];
                           pre_cycles<=payload[127:96]; post_cycles<=payload[159:128]; watchdog_cycles<=payload[191:160];
                       end
                    3: if(length!=0 || used || !adc_ready || adc_fault) response_payload<=1;
                       else start_delay<=1000000; // ACK drains before settling starts.
                    4: if(length==0) begin
                        response_length<=104;
                        response_payload[31:0]<={28'b0,adc_fault,adc_ready,finished,used};
                        response_payload[63:32]<=flags;
                        response_payload[95:64]<=completed;
                        response_payload[127:96]<=overruns;
                        response_payload[159:128]<=pre_count;
                        response_payload[191:160]<=active_count;
                        response_payload[223:192]<=post_count;
                        response_payload[255:224]<=checksum;
                        response_payload[319:256]<=busy_cycles;
                        response_payload[383:320]<=latency_total;
                        response_payload[447:384]<=active_cycles;
                        response_payload[479:448]<=latency_min;
                        response_payload[511:480]<=latency_max;
                        response_payload[639:512]<=last_output;
                        response_payload[703:640]<=tick;
                        response_payload[735:704]<=vcore;
                        response_payload[767:736]<=icore;
                        response_payload[799:768]<=v5;
                        response_payload[831:800]<=i5;
                    end else response_payload<=1;
                    5: if(length!=4 || !finished || payload[31:0]>=2048 ||
                            !((payload[31:0]<pre_count) ||
                              (payload[31:0]>=512 && payload[31:0]<512+active_count) ||
                              (payload[31:0]>=1536 && payload[31:0]<1536+post_count))) response_payload<=1;
                       else begin read_addr<=payload[10:0]; read_wait<=3; response<=0; end
                    default: response_payload<=1;
                endcase
            end
        end
    end
endmodule
