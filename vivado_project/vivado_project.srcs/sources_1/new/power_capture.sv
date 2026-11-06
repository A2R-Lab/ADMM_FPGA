`timescale 1ns/1ps
// Trace record, little-endian bit fields (512 bits):
// t0[63:0], cycles[95:64], count[127:96], core_product_sum[191:128],
// five_product_sum[255:192], vcore/icore/v5/i5/temp sums (40 bits each),
// flags[463:456], phase[471:464], reserved[511:472].
module power_capture #(
    parameter BIN_CYCLES=100000,
    parameter PRE_CAP=512, ACTIVE_CAP=1024, POST_CAP=512
)(
    input wire clk, rst,
    input wire [1:0] phase, // 0=off, 1=idle before, 2=active, 3=idle after
    input wire [63:0] tick,
    input wire sample_valid,
    input wire [11:0] vcore, icore, v5, i5, temperature,
    input wire [10:0] read_addr,
    input wire read_enable,
    output wire [511:0] read_data,
    output reg [10:0] pre_count=0, active_count=0, post_count=0,
    output wire busy,
    output reg fault=0
);
    (* ram_style="block" *) reg [511:0] mem[0:PRE_CAP+ACTIVE_CAP+POST_CAP-1];
    reg [511:0] acc=0, left_rec=0;
    reg [1:0] acc_phase=0;
    reg [31:0] widths[1:3];
    reg [3:0] state=0;
    reg [511:0] queue[0:3];
    reg [1:0] wp=0, rp=0;
    reg [2:0] queued=0;
    wire pending_valid=queued!=0;
    wire [511:0] pending=queue[rp];
    wire flush_bin=(phase!=acc_phase || (acc_phase!=0 && acc[95:64]>=widths[acc_phase])) && acc_phase!=0 && acc[95:64]!=0;
    wire pop_bin=state==8;
    always @(posedge clk) begin
        if(rst) begin wp<=0; rp<=0; queued<=0; end
        else begin
            if(flush_bin && (queued<4 || pop_bin)) begin queue[wp]<=acc; queue[wp][457]<=acc[457] || acc[127:96]==0; wp<=wp+1; end
            if(pop_bin) rp<=rp+1;
            case({flush_bin && (queued<4 || pop_bin),pop_bin})
                2'b10: queued<=queued+1;
                2'b01: queued<=queued-1;
            endcase
        end
    end
    reg [10:0] base=0, capacity=0, used=0, pair_idx=0;
    reg [1:0] store_phase=0;
    reg [10:0] ram_addr=0;
    reg [511:0] ram_q;
    wire [23:0] pc=vcore*icore, p5=v5*i5;
    wire saturated=(&vcore)||(&icore)||(&v5)||(&i5);
    assign busy=pending_valid || state!=0 || acc_phase!=0;
    // UART reads only after acquisition. Share its port with compaction to
    // infer one simple dual-port BRAM, rather than duplicating the trace RAM.
    wire [10:0] selected_read_addr=(state>=2 && state<=6)?ram_addr:read_addr;
    assign read_data=ram_q;
    always @(posedge clk)
        if(read_enable || (state>=2 && state<=6)) ram_q<=mem[selected_read_addr];
    function automatic [511:0] merge(input [511:0] a,b);
        reg [511:0] r;
        integer j;
        begin
            r=a;
            r[95:64]=a[95:64]+b[95:64];
            r[127:96]=a[127:96]+b[127:96];
            r[191:128]=a[191:128]+b[191:128];
            r[255:192]=a[255:192]+b[255:192];
            for(j=0;j<5;j=j+1) r[256+j*40+:40]=a[256+j*40+:40]+b[256+j*40+:40];
            r[463:456]=a[463:456]|b[463:456];
            merge=r;
        end
    endfunction
    // The collector continues during compaction; four queued bins cover phase transitions:
    // worst-case 512 pairs * 7 clocks < 1 ms at 100 MHz.
    always @(posedge clk) begin : collect
        reg [511:0] next_acc;
        if(rst) begin
            acc<=0; acc_phase<=0; state<=0; fault<=0;
            pre_count<=0; active_count<=0; post_count<=0;
            widths[1]<=BIN_CYCLES; widths[2]<=BIN_CYCLES; widths[3]<=BIN_CYCLES;
        end else begin
            if(phase!=acc_phase || (acc_phase!=0 && acc[95:64]>=widths[acc_phase])) begin
                if(acc_phase!=0 && acc[95:64]!=0) begin
                    if(queued==4 && !pop_bin) fault<=1;
                end
                next_acc=0;
                next_acc[63:0]=tick;
                next_acc[471:464]={6'b0,phase};
                acc_phase<=phase;
            end else next_acc=acc;
            if(phase!=0) begin
                next_acc[95:64]=next_acc[95:64]+1;
                if(sample_valid) begin
                    next_acc[127:96]=next_acc[127:96]+1;
                    next_acc[191:128]=next_acc[191:128]+pc;
                    next_acc[255:192]=next_acc[255:192]+p5;
                    next_acc[295:256]=next_acc[295:256]+vcore;
                    next_acc[335:296]=next_acc[335:296]+icore;
                    next_acc[375:336]=next_acc[375:336]+v5;
                    next_acc[415:376]=next_acc[415:376]+i5;
                    next_acc[455:416]=next_acc[455:416]+temperature;
                    next_acc[456]=next_acc[456]|saturated;
                end
            end
            acc<=next_acc;
            case(state)
                0: if(pending_valid) begin
                    store_phase<=pending[465:464];
                    case(pending[465:464])
                        1: begin base<=0; capacity<=PRE_CAP; used<=pre_count; end
                        2: begin base<=PRE_CAP; capacity<=ACTIVE_CAP; used<=active_count; end
                        3: begin base<=PRE_CAP+ACTIVE_CAP; capacity<=POST_CAP; used<=post_count; end
                    endcase
                    state<=1;
                end
                1: if(used==capacity) begin
                    pair_idx<=0; ram_addr<=base; widths[store_phase]<=widths[store_phase]<<1; state<=2;
                end else state<=8;
                2: state<=3;
                3: begin left_rec<=ram_q; ram_addr<=base+2*pair_idx+1; state<=4; end
                4: state<=5;
                5: begin mem[base+pair_idx]<=merge(left_rec,ram_q); state<=6; end
                6: if(pair_idx+1==capacity/2) begin used<=capacity/2; state<=8; end
                   else begin pair_idx<=pair_idx+1; ram_addr<=base+2*(pair_idx+1); state<=2; end
                8: begin
                    mem[base+used]<=pending;
                    case(store_phase)
                        1: pre_count<=used+1;
                        2: active_count<=used+1;
                        3: post_count<=used+1;
                    endcase
                    state<=0;
                end
            endcase
        end
    end
endmodule
