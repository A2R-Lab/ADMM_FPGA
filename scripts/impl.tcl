#------------------------------------------------------------------------------
# Vivado Implementation Script (Place & Route)
#------------------------------------------------------------------------------

set script_dir [file dirname [info script]]
set proj_root [file normalize "$script_dir/.."]

set build_dir "$proj_root/build"
set reports_dir "$build_dir/reports"

set vivado_max_threads 0
if {[info exists ::env(VIVADO_MAX_THREADS)] && [string is integer -strict $::env(VIVADO_MAX_THREADS)] && $::env(VIVADO_MAX_THREADS) > 0} {
    set vivado_max_threads $::env(VIVADO_MAX_THREADS)
} elseif {[info exists ::env(SLURM_CPUS_PER_TASK)] && [string is integer -strict $::env(SLURM_CPUS_PER_TASK)] && $::env(SLURM_CPUS_PER_TASK) > 0} {
    set vivado_max_threads $::env(SLURM_CPUS_PER_TASK)
}
if {$vivado_max_threads > 0} {
    puts "Vivado max threads: $vivado_max_threads"
    set_param general.maxThreads $vivado_max_threads
}

if {[llength $argv] >= 1} {
    set synth_dcp [lindex $argv 0]
} else {
    set synth_dcp "post_synth.dcp"
}
if {[llength $argv] >= 2} {
    set route_dcp [lindex $argv 1]
} else {
    set route_dcp "post_route.dcp"
}

#------------------------------------------------------------------------------
# Open Synthesis Checkpoint
#------------------------------------------------------------------------------
puts "Opening synthesis checkpoint..."
open_checkpoint "$build_dir/$synth_dcp"

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
write_checkpoint -force "$build_dir/$route_dcp"

puts "Implementation complete: $build_dir/$route_dcp"
