"""TinyMPC local-memory adapter for the existing Arty acquisition shell."""
import csv
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path


def prepare(work, horizon, env, log, run):
    hls = work/'vitis_projects/ADMM'
    generated = work/'build/tiny'
    run([sys.executable, str(work/'evaluation/tinympc_fpga/prepare.py'),
         '--generate-only', '--model-report', str(work/'evaluation/tinympc_fpga/model.json'),
         '--horizon', str(horizon), '--output', str(generated)], work, dict(env, ADMM_SOLVER_ARCH='staged_a'), log)
    for row in csv.DictReader((work/'scripts/power_synthetic_states.csv').open()):
        if int(row['constraints']) or int(row['traj_cmd']):
            raise ValueError('Tiny power adapter requires static bounds and zero reference')
    for name in ('tinympc_solver.cpp','tinympc_solver.h'):
        shutil.copy2(generated/name, hls/name)
    (hls/'ADMM.cpp').write_text('#include "tinympc_solver.cpp"\n')
    (hls/'data.h').write_text(f'#define HORIZON_LENGTH {horizon}\n')
    (hls/'admm_runtime_config.h').write_text('#define ADMM_USE_FLOAT 1\n#define ADMM_ENABLE_TRAJECTORY 0\n#define ADMM_ITERATIONS 10\n#define ADMM_SOLVER_ARCH_NAME "tinympc_fpga"\n')
    (hls/'hls_config.cfg').write_text('part=xc7a100t-csg324-1\n[hls]\nflow_target=vivado\nsyn.top=tinympc_solver\nclock=10ns\nsyn.file=ADMM.cpp\npackage.output.format=ip_catalog\npackage.output.syn=false\n')
    rtl = work/'vivado_project/vivado_project.srcs/sources_1/new'
    (rtl/'admm_autogen_params.vh').write_text('`define ADMM_ENABLE_TRAJECTORY 0\n`define ADMM_SOLVER_INPUT_WIDTH 418\n')
    header = (hls/'tinympc_solver.h').read_text()
    constants = dict(re.findall(r'#define (\w+) (\d+)',header))
    width = (int(constants['MAIN_MEMORY_SIZE'])-1).bit_length()
    offset = int(constants['U_OUT_OFFSET'])
    # One-cycle memory reads preserve the synthesized ap_memory contract. The
    # kernel still executes all original input/output loops. Reference is zero.
    (rtl/'power_tiny_adapter.sv').write_text(f'''module ADMM_solver(
 input wire ap_clk,ap_rst,ap_start,
 output wire ap_done,ap_idle,ap_ready,
 input wire [417:0] current_in_bits,
 output reg [127:0] command_out_bits=0,
 output wire command_out_bits_ap_vld);
 wire [{width-1}:0] address;
 wire ce,we;
 wire [31:0] data;
 reg [31:0] q=0;
 assign command_out_bits_ap_vld=ap_done;
 always @(posedge ap_clk) begin
   if(ap_rst) begin q<=0;command_out_bits<=0;end
   else if(ce) begin
     if(!we) q <= address < 12 ? current_in_bits[address*32 +: 32] : 32'b0;
     if(we && address >= {offset} && address < {offset+4})
       command_out_bits[(address-{offset})*32 +: 32] <= data;
   end
 end
 tinympc_solver core(.ap_clk(ap_clk),.ap_rst(ap_rst),.ap_start(ap_start),
 .ap_done(ap_done),.ap_idle(ap_idle),.ap_ready(ap_ready),
 .main_memory_address0(address),.main_memory_ce0(ce),.main_memory_we0(we),
 .main_memory_d0(data),.main_memory_q0(q));
endmodule
''')
    (work/'tests/solver_reference.cpp').write_text(r'''#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>
#include <cstring>
#include <cstdint>
#include "tinympc_solver.h"
int main(int argc,char**argv) {
 if(argc!=3)return 2;
 std::ifstream input(argv[1]);
 for(int n=0;n<std::stoi(argv[2]);++n){
  std::string line; if(!(input>>line))return 3;
  float memory[MAIN_MEMORY_SIZE]={0};
  for(int i=0;i<12;++i){uint32_t bits=std::stoul(line.substr(line.size()-8*(i+1),8),nullptr,16);std::memcpy(memory+i,&bits,4);}
  tinympc_solver(memory);
  for(int i=3;i>=0;--i){uint32_t bits;std::memcpy(&bits,memory+U_OUT_OFFSET+i,4);std::cout<<std::hex<<std::setw(8)<<std::setfill('0')<<bits;}
  std::cout<<'\n';
 }
}
''')
    # Generate workload without invoking AccelMPC header generation.
    run([sys.executable,str(work/'scripts/power_workload.py'),'--csv',str(work/'scripts/power_synthetic_states.csv'),
         '--config',str(hls/'admm_runtime_config.h'),'--output',str(work/'build/power')],work,env,log.with_name('workload.log'))


def validate_float_last(actual, expected):
    import math
    for a,b in zip(actual,expected):
        x=struct.unpack('<f',struct.pack('<I',a))[0]
        y=struct.unpack('<f',struct.pack('<I',b))[0]
        if not math.isfinite(x) or not math.isclose(x,y,rel_tol=2e-4,abs_tol=2e-5):
            raise ValueError(f'TinyMPC pilot output mismatch: {x} versus {y}')


def build_target(work, target, env, log, run):
    hls = work/'vitis_projects/ADMM'
    if target == 'headers':
        prepare(work, int(env['ADMM_HORIZON_LENGTH']), env, log, run)
    elif target == 'hls':
        run(['v++','-c','--mode','hls','--config','hls_config.cfg','--work_dir','ADMM'], hls, env, log)
        run(['vitis-run','--mode','hls','--package','--config','hls_config.cfg','--work_dir','ADMM'],hls,env,log.with_name('package.log'))
    elif target in ('vivado','bit'):
        stages = [('synth','top_uart_power','constraints_arty_power.xdc','post_synth_top_uart_power_arty-power.dcp'),
                  ('impl','post_synth_top_uart_power_arty-power.dcp','post_route_top_uart_power_arty-power.dcp')] if target=='vivado' else [
                  ('bitstream','top_uart_power','post_route_top_uart_power_arty-power.dcp')]
        for stage,*args in stages:
            run(['vivado','-mode','batch','-notrace','-source',str(work/f'scripts/{stage}.tcl'),'-tclargs',*args],work,env,log if stage!='synth' else log.with_name('synth.log'))
        if target=='bit':
            run([sys.executable,str(work/'scripts/power_build_manifest.py'),'--bitstream',str(work/'build/top_uart_power.bit')],work,env,log.with_name('manifest.log'))
