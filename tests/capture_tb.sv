`timescale 1ns/1ps
module capture_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst=1; reg [1:0] phase=0; reg [63:0] tick=0;
    reg [10:0] addr=0;
    wire [511:0] data; wire [10:0] n1,n2,n3; wire busy,fault;
    always @(posedge clk) if(!rst) tick<=tick+1;
    power_capture #(.BIN_CYCLES(100),.PRE_CAP(4),.ACTIVE_CAP(8),.POST_CAP(4)) dut(
        .clk(clk),.rst(rst),.phase(phase),.tick(tick),.sample_valid(1'b1),
        .vcore(12'd1000),.icore(12'd500),.v5(12'd3000),.i5(12'd400),.temperature(12'd2400),
        .read_addr(addr),.read_enable(1'b1),.read_data(data),.pre_count(n1),.active_count(n2),.post_count(n3),.busy(busy),.fault(fault));
    integer i,tot1=0,tot2=0,tot3=0;
    reg [63:0] end_tick=0;
    task inspect(input integer base,input integer n,input integer ph);
        integer j;
        begin
            for(j=0;j<n;j=j+1) begin
                @(negedge clk);addr=base+j; repeat(2) @(negedge clk);
                if(data[471:464]!=ph || data[463:456]!=0) $fatal(1,"phase/flags");
                if(data[127:96]!=data[95:64]) $fatal(1,"sample loss");
                if(data[191:128]!=data[127:96]*64'd500000 || data[255:192]!=data[127:96]*64'd1200000) $fatal(1,"products/compaction");
                if(data[63:0]!=end_tick && end_tick!=0) $fatal(1,"time gap");
                end_tick=data[63:0]+data[95:64];
                case(ph) 1:tot1=tot1+data[95:64];2:tot2=tot2+data[95:64];3:tot3=tot3+data[95:64];endcase
            end
        end
    endtask
    initial begin
        repeat(5) @(negedge clk);rst=0; phase=1;
        repeat(1733) @(negedge clk);phase=2;
        repeat(4527) @(negedge clk);phase=3;
        repeat(1431) @(negedge clk);phase=0;
        repeat(100) @(negedge clk);
        if(busy||fault) $fatal(1,"capture did not drain");
        inspect(0,n1,1);inspect(4,n2,2);inspect(12,n3,3);
        if(tot1!=1733 || tot2!=4527 || tot3!=1431) $fatal(1,"duration mismatch %d %d %d",tot1,tot2,tot3);
        $display("PASS capture: compaction, phase boundaries, weighted sums, complete coverage");$finish;
    end
    initial begin #1000000;$fatal(1,"timeout");end
endmodule
