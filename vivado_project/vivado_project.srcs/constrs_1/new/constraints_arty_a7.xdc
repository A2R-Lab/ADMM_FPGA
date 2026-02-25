## Arty A7-100T specific constraints for top-level UART design

## Use SPI X4 for flash programming
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]

## 100 MHz system clock into DDR clocking fabric (top-level board oscillator)
set_property -dict { PACKAGE_PIN E3 IOSTANDARD LVCMOS33 } [get_ports { sys_clk_i }];
create_clock -name sys_clk_i -period 10.000 [get_ports { sys_clk_i }]

## Reset (mapped to BTN0, active-high on board; logic expects active-low resetn)
set_property -dict { PACKAGE_PIN D9 IOSTANDARD LVCMOS33 } [get_ports { resetn }];

## USB-UART interface
## Board signal uart_txd_in is an input to the FPGA (RX for the design)
## Board signal uart_rxd_out is an output from the FPGA (TX for the design)
set_property -dict { PACKAGE_PIN A9  IOSTANDARD LVCMOS33 } [get_ports { uart_rxd }];
set_property -dict { PACKAGE_PIN D10 IOSTANDARD LVCMOS33 } [get_ports { uart_txd }];

## Simple LEDs (map 4-bit led bus)
set_property -dict { PACKAGE_PIN H5  IOSTANDARD LVCMOS33 } [get_ports { led[0] }];
set_property -dict { PACKAGE_PIN J5  IOSTANDARD LVCMOS33 } [get_ports { led[1] }];
set_property -dict { PACKAGE_PIN T9  IOSTANDARD LVCMOS33 } [get_ports { led[2] }];
set_property -dict { PACKAGE_PIN T10 IOSTANDARD LVCMOS33 } [get_ports { led[3] }];

## QSPI flash pins used by AXI Quad SPI (XIP)
set_property -dict { PACKAGE_PIN K17 IOSTANDARD LVCMOS33 } [get_ports { qspi_io0_io }];
set_property -dict { PACKAGE_PIN K18 IOSTANDARD LVCMOS33 } [get_ports { qspi_io1_io }];
set_property -dict { PACKAGE_PIN L13 IOSTANDARD LVCMOS33 } [get_ports { qspi_ss_io[0] }];
