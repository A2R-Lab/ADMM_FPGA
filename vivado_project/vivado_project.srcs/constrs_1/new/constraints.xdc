## Use SPI X4 for flash programming
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]

#------------------------------------------------------------------------------
# Clock input (100 MHz)
#------------------------------------------------------------------------------
set_property -dict { PACKAGE_PIN P17   IOSTANDARD LVCMOS33 } [get_ports { clk }];
create_clock -period 10.000 -name sys_clk -waveform {0 5} [get_ports clk]

#------------------------------------------------------------------------------
# LEDs
#------------------------------------------------------------------------------
set_property -dict { PACKAGE_PIN L16   IOSTANDARD LVCMOS33 } [get_ports { led1 }]; # blue
set_property -dict { PACKAGE_PIN M16   IOSTANDARD LVCMOS33 } [get_ports { led2 }]; # yellow

#------------------------------------------------------------------------------
# Push button (active low reset)
#------------------------------------------------------------------------------
set_property -dict { PACKAGE_PIN U18   IOSTANDARD LVCMOS33 } [get_ports { resetn }];

#------------------------------------------------------------------------------
# SPI Interface
#------------------------------------------------------------------------------
set_property -dict { PACKAGE_PIN R18   IOSTANDARD LVCMOS33 } [get_ports { spi_cf_miso }];
set_property -dict { PACKAGE_PIN T18   IOSTANDARD LVCMOS33 } [get_ports { spi_cf_mosi }];
set_property -dict { PACKAGE_PIN P18   IOSTANDARD LVCMOS33 } [get_ports { spi_cf_sck  }];
set_property -dict { PACKAGE_PIN V10   IOSTANDARD LVCMOS33 } [get_ports { spi_cs_n }];  # IO1 

#------------------------------------------------------------------------------
# UART 1
#------------------------------------------------------------------------------
set_property -dict { PACKAGE_PIN N14   IOSTANDARD LVCMOS33 } [get_ports { uart1_tx }];
set_property -dict { PACKAGE_PIN M13   IOSTANDARD LVCMOS33 } [get_ports { uart1_rx }];

#------------------------------------------------------------------------------
# UART 2
#------------------------------------------------------------------------------
set_property -dict { PACKAGE_PIN L18   IOSTANDARD LVCMOS33 } [get_ports { uart2_tx }];
set_property -dict { PACKAGE_PIN M18   IOSTANDARD LVCMOS33 } [get_ports { uart2_rx }];

#------------------------------------------------------------------------------
# I2C (Crazyflie connector)
#------------------------------------------------------------------------------
set_property -dict { PACKAGE_PIN R11   IOSTANDARD LVCMOS33 } [get_ports { i2c_cf_sda }];
set_property -dict { PACKAGE_PIN R10   IOSTANDARD LVCMOS33 } [get_ports { i2c_cf_scl }];

#------------------------------------------------------------------------------
# GPIO
#------------------------------------------------------------------------------
set_property -dict { PACKAGE_PIN U11   IOSTANDARD LVCMOS33 } [get_ports { io2 }];

#------------------------------------------------------------------------------
# I2C Power Chip
#------------------------------------------------------------------------------
set_property -dict { PACKAGE_PIN V16   IOSTANDARD LVCMOS33 } [get_ports { i2c_pwr_sda }];
set_property -dict { PACKAGE_PIN V17   IOSTANDARD LVCMOS33 } [get_ports { i2c_pwr_scl }];

#------------------------------------------------------------------------------
# SPI Clock Constraint (adjust frequency as needed)
# Assuming SPI clock up to 10 MHz from external master
#------------------------------------------------------------------------------
create_clock -period 100.000 -name spi_sck -waveform {0 50} [get_ports spi_cf_sck]
set_clock_groups -asynchronous -group [get_clocks sys_clk] -group [get_clocks spi_sck]

#------------------------------------------------------------------------------
# Input Delay Constraints for SPI
#------------------------------------------------------------------------------
set_input_delay -clock spi_sck -max 10.0 [get_ports spi_cf_mosi]
set_input_delay -clock spi_sck -min 0.0  [get_ports spi_cf_mosi]
set_input_delay -clock spi_sck -max 10.0 [get_ports spi_cs_n]
set_input_delay -clock spi_sck -min 0.0  [get_ports spi_cs_n]

#------------------------------------------------------------------------------
# Output Delay Constraints for SPI
#------------------------------------------------------------------------------
set_output_delay -clock spi_sck -max 10.0 [get_ports spi_cf_miso]
set_output_delay -clock spi_sck -min 0.0  [get_ports spi_cf_miso]
