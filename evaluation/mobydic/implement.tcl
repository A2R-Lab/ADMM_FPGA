# Usage: vivado -mode batch -source feasibility/implement.tcl -tclargs DESIGN_DIR
set design [file normalize [lindex $argv 0]]
set rtl $design/hls/hls/syn/verilog
set out $design/implementation
file mkdir $out
cd $rtl
read_verilog [glob *.v]
set constraints [open $out/clock.xdc w]
puts $constraints {create_clock -period 10 -name default [get_ports ap_clk]}
close $constraints
read_xdc $out/clock.xdc
synth_design -top control -part xc7a100t-csg324-1 -mode out_of_context
report_utilization -file $out/post_synth_utilization.rpt
report_timing_summary -file $out/post_synth_timing.rpt
write_checkpoint -force $out/post_synth.dcp
opt_design
place_design
route_design
report_utilization -file $out/post_route_utilization.rpt
report_timing_summary -file $out/post_route_timing.rpt
report_power -file $out/post_route_power.rpt
write_checkpoint -force $out/post_route.dcp

# Evaluate the routed implementation at the operating clock.
close_design
open_checkpoint $out/post_route.dcp
create_clock -period 16.666666667 -name default [get_ports ap_clk]
set out $design/operating_60mhz
file mkdir $out
report_clocks -file $out/clocks.rpt
report_timing_summary -file $out/timing.rpt
report_power -file $out/power.rpt
report_utilization -file $out/utilization.rpt
write_checkpoint -force $out/post_route.dcp
