// (c) Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// (c) Copyright 2022-2025 Advanced Micro Devices, Inc. All rights reserved.
// 
// This file contains confidential and proprietary information
// of AMD and is protected under U.S. and international copyright
// and other intellectual property laws.
// 
// DISCLAIMER
// This disclaimer is not a license and does not grant any
// rights to the materials distributed herewith. Except as
// otherwise provided in a valid license issued to you by
// AMD, and to the maximum extent permitted by applicable
// law: (1) THESE MATERIALS ARE MADE AVAILABLE "AS IS" AND
// WITH ALL FAULTS, AND AMD HEREBY DISCLAIMS ALL WARRANTIES
// AND CONDITIONS, EXPRESS, IMPLIED, OR STATUTORY, INCLUDING
// BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, NON-
// INFRINGEMENT, OR FITNESS FOR ANY PARTICULAR PURPOSE; and
// (2) AMD shall not be liable (whether in contract or tort,
// including negligence, or under any other theory of
// liability) for any loss or damage of any kind or nature
// related to, arising under or in connection with these
// materials, including for any direct, or any indirect,
// special, incidental, or consequential loss or damage
// (including loss of data, profits, goodwill, or any type of
// loss or damage suffered as a result of any action brought
// by a third party) even if such damage or loss was
// reasonably foreseeable or AMD had been advised of the
// possibility of the same.
// 
// CRITICAL APPLICATIONS
// AMD products are not designed or intended to be fail-
// safe, or for use in any application requiring fail-safe
// performance, such as life-support or safety devices or
// systems, Class III medical devices, nuclear facilities,
// applications related to the deployment of airbags, or any
// other applications that could lead to death, personal
// injury, or severe property or environmental damage
// (individually and collectively, "Critical
// Applications"). Customer assumes the sole risk and
// liability of any use of AMD products in Critical
// Applications, subject only to applicable laws and
// regulations governing limitations on product liability.
// 
// THIS COPYRIGHT NOTICE AND DISCLAIMER MUST BE RETAINED AS
// PART OF THIS FILE AT ALL TIMES.
// 
// DO NOT MODIFY THIS FILE.


// IP VLNV: xilinx.com:hls:ADMM_solver:1.0
// IP Revision: 2114393920

(* X_CORE_INFO = "ADMM_solver,Vivado 2025.2" *)
(* CHECK_LICENSE_TYPE = "ADMM_solver_0,ADMM_solver,{}" *)
(* CORE_GENERATION_INFO = "ADMM_solver_0,ADMM_solver,{x_ipProduct=Vivado 2025.2,x_ipVendor=xilinx.com,x_ipLibrary=hls,x_ipName=ADMM_solver,x_ipVersion=1.0,x_ipCoreRevision=2114393920,x_ipLanguage=VERILOG,x_ipSimLanguage=MIXED}" *)
(* IP_DEFINITION_SOURCE = "HLS" *)
(* DowngradeIPIdentifiedWarnings = "yes" *)
module ADMM_solver_0 (
  current_state_ce0,
  x_ce0,
  x_we0,
  x_ce1,
  ap_clk,
  ap_rst,
  ap_done,
  ap_idle,
  ap_ready,
  ap_start,
  current_state_address0,
  current_state_q0,
  x_address0,
  x_d0,
  x_q0,
  x_address1,
  x_q1,
  iters
);

output wire current_state_ce0;
output wire x_ce0;
output wire x_we0;
output wire x_ce1;
(* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 ap_clk CLK" *)
(* X_INTERFACE_MODE = "slave" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME ap_clk, ASSOCIATED_RESET ap_rst, FREQ_HZ 100000000, FREQ_TOLERANCE_HZ 0, PHASE 0.0, INSERT_VIP 0" *)
input wire ap_clk;
(* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 ap_rst RST" *)
(* X_INTERFACE_MODE = "slave" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME ap_rst, POLARITY ACTIVE_HIGH, INSERT_VIP 0" *)
input wire ap_rst;
(* X_INTERFACE_INFO = "xilinx.com:interface:acc_handshake:1.0 ap_ctrl done" *)
(* X_INTERFACE_MODE = "slave" *)
output wire ap_done;
(* X_INTERFACE_INFO = "xilinx.com:interface:acc_handshake:1.0 ap_ctrl idle" *)
output wire ap_idle;
(* X_INTERFACE_INFO = "xilinx.com:interface:acc_handshake:1.0 ap_ctrl ready" *)
output wire ap_ready;
(* X_INTERFACE_INFO = "xilinx.com:interface:acc_handshake:1.0 ap_ctrl start" *)
input wire ap_start;
(* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 current_state_address0 DATA" *)
(* X_INTERFACE_MODE = "master" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME current_state_address0, LAYERED_METADATA undef" *)
output wire [3 : 0] current_state_address0;
(* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 current_state_q0 DATA" *)
(* X_INTERFACE_MODE = "slave" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME current_state_q0, LAYERED_METADATA undef" *)
input wire [31 : 0] current_state_q0;
(* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_address0 DATA" *)
(* X_INTERFACE_MODE = "master" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_address0, LAYERED_METADATA undef" *)
output wire [8 : 0] x_address0;
(* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_d0 DATA" *)
(* X_INTERFACE_MODE = "master" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_d0, LAYERED_METADATA undef" *)
output wire [31 : 0] x_d0;
(* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_q0 DATA" *)
(* X_INTERFACE_MODE = "slave" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_q0, LAYERED_METADATA undef" *)
input wire [31 : 0] x_q0;
(* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_address1 DATA" *)
(* X_INTERFACE_MODE = "master" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_address1, LAYERED_METADATA undef" *)
output wire [8 : 0] x_address1;
(* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 x_q1 DATA" *)
(* X_INTERFACE_MODE = "slave" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME x_q1, LAYERED_METADATA undef" *)
input wire [31 : 0] x_q1;
(* X_INTERFACE_INFO = "xilinx.com:signal:data:1.0 iters DATA" *)
(* X_INTERFACE_MODE = "slave" *)
(* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME iters, LAYERED_METADATA undef" *)
input wire [31 : 0] iters;

(* SDX_KERNEL = "true" *)
(* SDX_KERNEL_TYPE = "hls" *)
(* SDX_KERNEL_SYNTH_INST = "inst" *)
  ADMM_solver inst (
    .current_state_ce0(current_state_ce0),
    .x_ce0(x_ce0),
    .x_we0(x_we0),
    .x_ce1(x_ce1),
    .ap_clk(ap_clk),
    .ap_rst(ap_rst),
    .ap_done(ap_done),
    .ap_idle(ap_idle),
    .ap_ready(ap_ready),
    .ap_start(ap_start),
    .current_state_address0(current_state_address0),
    .current_state_q0(current_state_q0),
    .x_address0(x_address0),
    .x_d0(x_d0),
    .x_q0(x_q0),
    .x_address1(x_address1),
    .x_q1(x_q1),
    .iters(iters)
  );
endmodule
