# Re-evaluate an existing routed design at an actual operating clock.
# HLS cycles and the netlist are unchanged. Repair timing only if necessary.
set_param general.maxThreads 4
set checkpoint [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
set mhz [lindex $argv 2]
file mkdir $out
open_checkpoint $checkpoint
create_clock -period [expr {1000.0 / $mhz}] -name default [get_ports ap_clk]
report_timing_summary -file $out/before_refinement_timing.rpt
set slack [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
if {$slack < 0} {
    phys_opt_design -directive AggressiveExplore
    route_design -directive Explore
}
report_utilization -file $out/post_route_utilization.rpt
report_timing_summary -file $out/post_route_timing.rpt
report_power -file $out/post_route_power.rpt
write_checkpoint -force $out/post_route.dcp
