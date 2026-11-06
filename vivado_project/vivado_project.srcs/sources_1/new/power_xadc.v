`timescale 1ns/1ps
// UG480: default-mode calibration followed by simultaneous pairs 1/9, 2/10.
// Each EOS snapshot is read before the next conversion can update the registers.
module power_xadc #(
    parameter CAL_CYCLES=2000000,
    parameter SIM_MONITOR_FILE="design.txt"
)(
    input wire clk, rst,
    input wire vsns5v0_p, vsns5v0_n, isns5v0_p, isns5v0_n,
    input wire isns0v95_p, isns0v95_n, vsnsvu_p, vsnsvu_n,
    output reg valid=0, ready=0, fault=0,
    output reg [11:0] v5=0, i5=0, icore=0, vcore=0, temperature=0
);
    wire [15:0] vp = {5'b0,isns0v95_p,isns5v0_p,6'b0,vsnsvu_p,vsns5v0_p,1'b0};
    wire [15:0] vn = {5'b0,isns0v95_n,isns5v0_n,6'b0,vsnsvu_n,vsns5v0_n,1'b0};
    wire eos, drdy;
    wire [15:0] dout;
    reg den=0, dwe=0;
    reg [6:0] addr=0;
    reg [31:0] timer=0;
    reg [2:0] state=0, index=0;
    reg [1:0] discard=0;
    function [6:0] channel_addr(input [2:0] i);
        case(i)
            0: channel_addr=7'h11;
            1: channel_addr=7'h19;
            2: channel_addr=7'h1a;
            3: channel_addr=7'h01;
            default: channel_addr=7'h00;
        endcase
    endfunction
    XADC #(.SIM_MONITOR_FILE(SIM_MONITOR_FILE), .INIT_40(16'h0000), .INIT_41(16'h0ef0), .INIT_42(16'h0400),
        .INIT_48(16'h0300), .INIT_49(16'h0006),
        .INIT_4A(16'h0000), .INIT_4B(16'h0000),
        .INIT_4C(16'h0000), .INIT_4D(16'h0000),
        .INIT_4E(16'h0000), .INIT_4F(16'h0006)) adc (
        .DCLK(clk), .RESET(rst), .DADDR(addr), .DEN(den), .DWE(dwe),
        .DI(16'h4ef0), .DO(dout), .DRDY(drdy), .EOS(eos),
        .VAUXP(vp), .VAUXN(vn), .VP(1'b0), .VN(1'b0),
        .CONVST(1'b0), .CONVSTCLK(1'b0), .ALM(), .BUSY(), .CHANNEL(),
        .EOC(), .MUXADDR(), .JTAGBUSY(), .JTAGLOCKED(), .JTAGMODIFIED(), .OT()
    );
    always @(posedge clk) begin
        valid<=0; den<=0; dwe<=0;
        if(rst) begin
            state<=0; timer<=0; ready<=0; fault<=0; discard<=0;
        end else begin
            timer<=timer+1;
            case(state)
                0: if(timer==CAL_CYCLES-1) begin
                    addr<=7'h41; den<=1; dwe<=1; state<=1; timer<=0;
                end
                1: if(drdy) begin state<=2; timer<=0; end
                2: if(eos) begin
                    timer<=0;
                    if(discard<2) discard<=discard+1;
                    else begin index<=0; state<=3; end
                end
                3: begin addr<=channel_addr(index); den<=1; state<=4; end
                4: if(drdy) begin
                    case(index)
                        0: v5<=dout[15:4];
                        1: i5<=dout[15:4];
                        2: icore<=dout[15:4];
                        3: vcore<=dout[15:4];
                        4: temperature<=dout[15:4];
                    endcase
                    if(index==4) begin valid<=1; ready<=1; state<=2; timer<=0; end
                    else begin index<=index+1; state<=3; end
                end
            endcase
            if(state!=0 && timer==1000000) begin fault<=1; ready<=0; end
        end
    end
endmodule
