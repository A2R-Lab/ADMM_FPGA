set_param general.maxThreads 4
set design [file normalize [lindex $argv 0]]
set out $design/implementation_refined
file mkdir $out
open_checkpoint $design/implementation/post_route.dcp
phys_opt_design -directive AggressiveExplore
route_design -directive Explore
report_utilization -file $out/post_route_utilization.rpt
report_timing_summary -file $out/post_route_timing.rpt
report_power -file $out/post_route_power.rpt
write_checkpoint -force $out/post_route.dcp
