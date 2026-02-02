#------------------------------------------------------------------------------
# Vivado Implementation Script (Place & Route)
#------------------------------------------------------------------------------

set script_dir [file dirname [info script]]
set proj_root [file normalize "$script_dir/.."]

set build_dir "$proj_root/build"
set reports_dir "$build_dir/reports"

#------------------------------------------------------------------------------
# Open Synthesis Checkpoint
#------------------------------------------------------------------------------
puts "Opening synthesis checkpoint..."
open_checkpoint "$build_dir/post_synth.dcp"

#------------------------------------------------------------------------------
# Optimization
#------------------------------------------------------------------------------
puts "Running Optimization..."
opt_design -directive Explore

#------------------------------------------------------------------------------
# Placement
#------------------------------------------------------------------------------
puts "Running Placement..."
place_design -directive Explore

report_utilization -file "$reports_dir/post_place_utilization.rpt"
report_timing_summary -file "$reports_dir/post_place_timing.rpt"

write_checkpoint -force "$build_dir/post_place.dcp"

#------------------------------------------------------------------------------
# Physical Optimization
#------------------------------------------------------------------------------
puts "Running Physical Optimization..."
phys_opt_design -directive AggressiveExplore

#------------------------------------------------------------------------------
# Routing
#------------------------------------------------------------------------------
puts "Running Routing..."
route_design -directive Explore

#------------------------------------------------------------------------------
# Reports
#------------------------------------------------------------------------------
report_utilization -file "$reports_dir/post_route_utilization.rpt"
report_timing_summary -file "$reports_dir/post_route_timing.rpt"
report_power -file "$reports_dir/post_route_power.rpt"
report_drc -file "$reports_dir/post_route_drc.rpt"

#------------------------------------------------------------------------------
# Save Checkpoint
#------------------------------------------------------------------------------
write_checkpoint -force "$build_dir/post_route.dcp"

puts "Implementation complete: $build_dir/post_route.dcp"
