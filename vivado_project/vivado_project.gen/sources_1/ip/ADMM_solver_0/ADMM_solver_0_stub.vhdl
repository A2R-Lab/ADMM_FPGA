-- Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
-- Copyright 2022-2025 Advanced Micro Devices, Inc. All Rights Reserved.
-- --------------------------------------------------------------------------------
-- Tool Version: Vivado v.2025.2 (lin64) Build 6299465 Fri Nov 14 12:34:56 MST 2025
-- Date        : Mon Dec 15 23:56:37 2025
-- Host        : ag-think running 64-bit Debian GNU/Linux 12 (bookworm)
-- Command     : write_vhdl -force -mode synth_stub
--               /home/andrea/ADMM_FPGA/vivado_project/vivado_project.gen/sources_1/ip/ADMM_solver_0/ADMM_solver_0_stub.vhdl
-- Design      : ADMM_solver_0
-- Purpose     : Stub declaration of top-level module interface
-- Device      : xc7a100tcsg324-1
-- --------------------------------------------------------------------------------
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity ADMM_solver_0 is
  Port ( 
    current_state_ce0 : out STD_LOGIC;
    x_ce0 : out STD_LOGIC;
    x_we0 : out STD_LOGIC;
    x_ce1 : out STD_LOGIC;
    ap_clk : in STD_LOGIC;
    ap_rst : in STD_LOGIC;
    ap_done : out STD_LOGIC;
    ap_idle : out STD_LOGIC;
    ap_ready : out STD_LOGIC;
    ap_start : in STD_LOGIC;
    current_state_address0 : out STD_LOGIC_VECTOR ( 3 downto 0 );
    current_state_q0 : in STD_LOGIC_VECTOR ( 31 downto 0 );
    x_address0 : out STD_LOGIC_VECTOR ( 8 downto 0 );
    x_d0 : out STD_LOGIC_VECTOR ( 31 downto 0 );
    x_q0 : in STD_LOGIC_VECTOR ( 31 downto 0 );
    x_address1 : out STD_LOGIC_VECTOR ( 8 downto 0 );
    x_q1 : in STD_LOGIC_VECTOR ( 31 downto 0 );
    iters : in STD_LOGIC_VECTOR ( 31 downto 0 )
  );

  attribute CHECK_LICENSE_TYPE : string;
  attribute CHECK_LICENSE_TYPE of ADMM_solver_0 : entity is "ADMM_solver_0,ADMM_solver,{}";
  attribute CORE_GENERATION_INFO : string;
  attribute CORE_GENERATION_INFO of ADMM_solver_0 : entity is "ADMM_solver_0,ADMM_solver,{x_ipProduct=Vivado 2025.2,x_ipVendor=xilinx.com,x_ipLibrary=hls,x_ipName=ADMM_solver,x_ipVersion=1.0,x_ipCoreRevision=2114393145,x_ipLanguage=VERILOG,x_ipSimLanguage=MIXED}";
  attribute DowngradeIPIdentifiedWarnings : string;
  attribute DowngradeIPIdentifiedWarnings of ADMM_solver_0 : entity is "yes";
  attribute IP_DEFINITION_SOURCE : string;
  attribute IP_DEFINITION_SOURCE of ADMM_solver_0 : entity is "HLS";
  attribute hls_module : string;
  attribute hls_module of ADMM_solver_0 : entity is "yes";
end ADMM_solver_0;

architecture stub of ADMM_solver_0 is
  attribute syn_black_box : boolean;
  attribute black_box_pad_pin : string;
  attribute syn_black_box of stub : architecture is true;
  attribute black_box_pad_pin of stub : architecture is "current_state_ce0,x_ce0,x_we0,x_ce1,ap_clk,ap_rst,ap_done,ap_idle,ap_ready,ap_start,current_state_address0[3:0],current_state_q0[31:0],x_address0[8:0],x_d0[31:0],x_q0[31:0],x_address1[8:0],x_q1[31:0],iters[31:0]";
  attribute X_INTERFACE_INFO : string;
  attribute X_INTERFACE_INFO of ap_clk : signal is "xilinx.com:signal:clock:1.0 ap_clk CLK";
  attribute X_INTERFACE_MODE : string;
  attribute X_INTERFACE_MODE of ap_clk : signal is "slave";
  attribute X_INTERFACE_PARAMETER : string;
  attribute X_INTERFACE_PARAMETER of ap_clk : signal is "XIL_INTERFACENAME ap_clk, ASSOCIATED_RESET ap_rst, FREQ_HZ 100000000, FREQ_TOLERANCE_HZ 0, PHASE 0.0, INSERT_VIP 0";
  attribute X_INTERFACE_INFO of ap_rst : signal is "xilinx.com:signal:reset:1.0 ap_rst RST";
  attribute X_INTERFACE_MODE of ap_rst : signal is "slave";
  attribute X_INTERFACE_PARAMETER of ap_rst : signal is "XIL_INTERFACENAME ap_rst, POLARITY ACTIVE_HIGH, INSERT_VIP 0";
  attribute X_INTERFACE_INFO of ap_done : signal is "xilinx.com:interface:acc_handshake:1.0 ap_ctrl done";
  attribute X_INTERFACE_MODE of ap_done : signal is "slave";
  attribute X_INTERFACE_INFO of ap_idle : signal is "xilinx.com:interface:acc_handshake:1.0 ap_ctrl idle";
  attribute X_INTERFACE_INFO of ap_ready : signal is "xilinx.com:interface:acc_handshake:1.0 ap_ctrl ready";
  attribute X_INTERFACE_INFO of ap_start : signal is "xilinx.com:interface:acc_handshake:1.0 ap_ctrl start";
  attribute X_INTERFACE_INFO of current_state_address0 : signal is "xilinx.com:signal:data:1.0 current_state_address0 DATA";
  attribute X_INTERFACE_MODE of current_state_address0 : signal is "master";
  attribute X_INTERFACE_PARAMETER of current_state_address0 : signal is "XIL_INTERFACENAME current_state_address0, LAYERED_METADATA undef";
  attribute X_INTERFACE_INFO of current_state_q0 : signal is "xilinx.com:signal:data:1.0 current_state_q0 DATA";
  attribute X_INTERFACE_MODE of current_state_q0 : signal is "slave";
  attribute X_INTERFACE_PARAMETER of current_state_q0 : signal is "XIL_INTERFACENAME current_state_q0, LAYERED_METADATA undef";
  attribute X_INTERFACE_INFO of x_address0 : signal is "xilinx.com:signal:data:1.0 x_address0 DATA";
  attribute X_INTERFACE_MODE of x_address0 : signal is "master";
  attribute X_INTERFACE_PARAMETER of x_address0 : signal is "XIL_INTERFACENAME x_address0, LAYERED_METADATA undef";
  attribute X_INTERFACE_INFO of x_d0 : signal is "xilinx.com:signal:data:1.0 x_d0 DATA";
  attribute X_INTERFACE_MODE of x_d0 : signal is "master";
  attribute X_INTERFACE_PARAMETER of x_d0 : signal is "XIL_INTERFACENAME x_d0, LAYERED_METADATA undef";
  attribute X_INTERFACE_INFO of x_q0 : signal is "xilinx.com:signal:data:1.0 x_q0 DATA";
  attribute X_INTERFACE_MODE of x_q0 : signal is "slave";
  attribute X_INTERFACE_PARAMETER of x_q0 : signal is "XIL_INTERFACENAME x_q0, LAYERED_METADATA undef";
  attribute X_INTERFACE_INFO of x_address1 : signal is "xilinx.com:signal:data:1.0 x_address1 DATA";
  attribute X_INTERFACE_MODE of x_address1 : signal is "master";
  attribute X_INTERFACE_PARAMETER of x_address1 : signal is "XIL_INTERFACENAME x_address1, LAYERED_METADATA undef";
  attribute X_INTERFACE_INFO of x_q1 : signal is "xilinx.com:signal:data:1.0 x_q1 DATA";
  attribute X_INTERFACE_MODE of x_q1 : signal is "slave";
  attribute X_INTERFACE_PARAMETER of x_q1 : signal is "XIL_INTERFACENAME x_q1, LAYERED_METADATA undef";
  attribute X_INTERFACE_INFO of iters : signal is "xilinx.com:signal:data:1.0 iters DATA";
  attribute X_INTERFACE_MODE of iters : signal is "slave";
  attribute X_INTERFACE_PARAMETER of iters : signal is "XIL_INTERFACENAME iters, LAYERED_METADATA undef";
  attribute X_CORE_INFO : string;
  attribute X_CORE_INFO of stub : architecture is "ADMM_solver,Vivado 2025.2";
begin
end;
