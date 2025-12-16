// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2025 Advanced Micro Devices, Inc. All Rights Reserved.
// --------------------------------------------------------------------------------
// Tool Version: Vivado v.2025.2 (lin64) Build 6299465 Fri Nov 14 12:34:56 MST 2025
// Date        : Tue Dec 16 12:46:13 2025
// Host        : ag-think running 64-bit Debian GNU/Linux 12 (bookworm)
// Command     : write_verilog -force -mode synth_stub
//               /home/andrea/ADMM_FPGA/vivado_project/vivado_project.gen/sources_1/ip/ADMM_solver_0/ADMM_solver_0_stub.v
// Design      : ADMM_solver_0
// Purpose     : Stub declaration of top-level module interface
// Device      : xc7a100tcsg324-1
// --------------------------------------------------------------------------------

// This empty module with port declaration file causes synthesis tools to infer a black box for IP.
// The synthesis directives are for Synopsys Synplify support to prevent IO buffer insertion.
// Please paste the declaration into a Verilog source file or add the file as an additional source.
(* CHECK_LICENSE_TYPE = "ADMM_solver_0,ADMM_solver,{}" *) (* CORE_GENERATION_INFO = "ADMM_solver_0,ADMM_solver,{x_ipProduct=Vivado 2025.2,x_ipVendor=xilinx.com,x_ipLibrary=hls,x_ipName=ADMM_solver,x_ipVersion=1.0,x_ipCoreRevision=2114393920,x_ipLanguage=VERILOG,x_ipSimLanguage=MIXED}" *) (* DowngradeIPIdentifiedWarnings = "yes" *) 
(* IP_DEFINITION_SOURCE = "HLS" *) (* X_CORE_INFO = "ADMM_solver,Vivado 2025.2" *) (* hls_module = "yes" *) 
module ADMM_solver_0(current_state_ce0, x_ce0, x_we0, x_ce1, ap_clk, 
  ap_rst, ap_done, ap_idle, ap_ready, ap_start, current_state_address0, current_state_q0, 
  x_address0, x_d0, x_q0, x_address1, x_q1, iters)
/* synthesis syn_black_box black_box_pad_pin="current_state_ce0,x_ce0,x_we0,x_ce1,ap_rst,ap_done,ap_idle,ap_ready,ap_start,current_state_address0[3:0],current_state_q0[31:0],x_address0[8:0],x_d0[31:0],x_q0[31:0],x_address1[8:0],x_q1[31:0],iters[31:0]" */
/* synthesis syn_force_seq_prim="ap_clk" */;
  output current_state_ce0;
  output x_ce0;
  output x_we0;
  output x_ce1;
  (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 ap_clk CLK" *) (* X_INTERFACE_MODE = "slave" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME ap_clk, ASSOCIATED_RESET ap_rst, FREQ_HZ 100000000, FREQ_TOLERANCE_HZ 0, PHASE 0.0, INSERT_VIP 0" *) input ap_clk /* synthesis syn_isclock = 1 */;
  (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 ap_rst RST" *) (* X_INTERFACE_MODE = "slave" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME ap_rst, POLARITY ACTIVE_HIGH, INSERT_VIP 0" *) input ap_rst;
  (* X_INTERFACE_INFO = "xilinx.com:interface:acc_handshake:1.0 ap_ctrl done" *) (* X_INTERFACE_MODE = "slave" *) output ap_done;
  (* X_INTERFACE_INFO = "xilinx.com:interface:acc_handshake:1.0 ap_ctrl idle" *) output ap_idle;
  (* X_INTERFACE_INFO = "xilinx.com:interface:acc_handshake:1.0 ap_ctrl ready" *) output ap_ready;
  (* X_INTERFACE_INFO = "xilinx.com:interface:acc_handshake:1.0 ap_ctrl start" *) input ap_start;
  (* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 current_state_address0 DATA" *) (* X_INTERFACE_MODE = "master" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME current_state_address0, LAYERED_METADATA undef" *) output [3:0]current_state_address0;
  (* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 current_state_q0 DATA" *) (* X_INTERFACE_MODE = "slave" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME current_state_q0, LAYERED_METADATA undef" *) input [31:0]current_state_q0;
  (* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_address0 DATA" *) (* X_INTERFACE_MODE = "master" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_address0, LAYERED_METADATA undef" *) output [8:0]x_address0;
  (* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_d0 DATA" *) (* X_INTERFACE_MODE = "master" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_d0, LAYERED_METADATA undef" *) output [31:0]x_d0;
  (* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_q0 DATA" *) (* X_INTERFACE_MODE = "slave" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_q0, LAYERED_METADATA undef" *) input [31:0]x_q0;
  (* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_address1 DATA" *) (* X_INTERFACE_MODE = "master" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_address1, LAYERED_METADATA undef" *) output [8:0]x_address1;
  (* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_q1 DATA" *) (* X_INTERFACE_MODE = "slave" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_q1, LAYERED_METADATA undef" *) input [31:0]x_q1;
  (* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 iters DATA" *) (* X_INTERFACE_MODE = "slave" *) (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME iters, LAYERED_METADATA undef" *) input [31:0]iters;
endmodule
