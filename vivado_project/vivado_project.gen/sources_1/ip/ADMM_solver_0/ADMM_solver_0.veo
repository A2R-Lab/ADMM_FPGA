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

// The following must be inserted into your Verilog file for this
// core to be instantiated. Change the instance name and port connections
// (in parentheses) to your own signal names.

//----------- Begin Cut here for INSTANTIATION Template ---// INST_TAG
ADMM_solver_0 your_instance_name (
  .current_state_ce0(current_state_ce0),            // output wire current_state_ce0
  .x_ce0(x_ce0),                                    // output wire x_ce0
  .x_we0(x_we0),                                    // output wire x_we0
  .x_ce1(x_ce1),                                    // output wire x_ce1
  .ap_clk(ap_clk),                                  // input wire ap_clk
  .ap_rst(ap_rst),                                  // input wire ap_rst
  .ap_done(ap_done),                                // output wire ap_done
  .ap_idle(ap_idle),                                // output wire ap_idle
  .ap_ready(ap_ready),                              // output wire ap_ready
  .ap_start(ap_start),                              // input wire ap_start
  .current_state_address0(current_state_address0),  // output wire [3 : 0] current_state_address0
  .current_state_q0(current_state_q0),              // input wire [31 : 0] current_state_q0
  .x_address0(x_address0),                          // output wire [8 : 0] x_address0
  .x_d0(x_d0),                                      // output wire [31 : 0] x_d0
  .x_q0(x_q0),                                      // input wire [31 : 0] x_q0
  .x_address1(x_address1),                          // output wire [8 : 0] x_address1
  .x_q1(x_q1),                                      // input wire [31 : 0] x_q1
  .iters(iters)                                    // input wire [31 : 0] iters
);
// INST_TAG_END ------ End INSTANTIATION Template ---------

// You must compile the wrapper file ADMM_solver_0.v when simulating
// the core, ADMM_solver_0. When compiling the wrapper file, be sure to
// reference the Verilog simulation library.

