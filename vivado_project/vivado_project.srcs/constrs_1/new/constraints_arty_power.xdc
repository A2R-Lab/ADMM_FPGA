# Arty A7-100 Rev E. Analog ports feed XADC directly (no digital input buffers).
# Base Arty constraints are loaded separately by synth.tcl.
set_property -dict { PACKAGE_PIN B16 IOSTANDARD LVCMOS33 } [get_ports vsnsvu_p]
set_property -dict { PACKAGE_PIN B17 IOSTANDARD LVCMOS33 } [get_ports vsnsvu_n]
set_property -dict { PACKAGE_PIN C12 IOSTANDARD LVCMOS33 } [get_ports vsns5v0_p]
set_property -dict { PACKAGE_PIN B12 IOSTANDARD LVCMOS33 } [get_ports vsns5v0_n]
set_property -dict { PACKAGE_PIN F13 IOSTANDARD LVCMOS33 } [get_ports isns5v0_p]
set_property -dict { PACKAGE_PIN F14 IOSTANDARD LVCMOS33 } [get_ports isns5v0_n]
set_property -dict { PACKAGE_PIN A15 IOSTANDARD LVCMOS33 } [get_ports isns0v95_p]
set_property -dict { PACKAGE_PIN A16 IOSTANDARD LVCMOS33 } [get_ports isns0v95_n]
