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

set opt_directive "Explore"
if {[info exists ::env(VIVADO_OPT_DIRECTIVE)] && $::env(VIVADO_OPT_DIRECTIVE) ne ""} {
    set opt_directive $::env(VIVADO_OPT_DIRECTIVE)
}
set place_directive "Explore"
if {[info exists ::env(VIVADO_PLACE_DIRECTIVE)] && $::env(VIVADO_PLACE_DIRECTIVE) ne ""} {
    set place_directive $::env(VIVADO_PLACE_DIRECTIVE)
}
set place_subdirective ""
if {[info exists ::env(VIVADO_PLACE_SUBDIRECTIVE)] && $::env(VIVADO_PLACE_SUBDIRECTIVE) ne ""} {
    set place_subdirective $::env(VIVADO_PLACE_SUBDIRECTIVE)
}
set phys_directive "AggressiveExplore"
if {[info exists ::env(VIVADO_PHYS_OPT_DIRECTIVE)] && $::env(VIVADO_PHYS_OPT_DIRECTIVE) ne ""} {
    set phys_directive $::env(VIVADO_PHYS_OPT_DIRECTIVE)
}
set route_directive "Explore"
if {[info exists ::env(VIVADO_ROUTE_DIRECTIVE)] && $::env(VIVADO_ROUTE_DIRECTIVE) ne ""} {
    set route_directive $::env(VIVADO_ROUTE_DIRECTIVE)
}
set route_tns_cleanup 0
if {[info exists ::env(VIVADO_ROUTE_TNS_CLEANUP)] && $::env(VIVADO_ROUTE_TNS_CLEANUP) eq "1"} {
    set route_tns_cleanup 1
}
set route_ultrathreads 0
if {[info exists ::env(VIVADO_ROUTE_ULTRATHREADS)] && $::env(VIVADO_ROUTE_ULTRATHREADS) eq "1"} {
    set route_ultrathreads 1
}

puts "Vivado opt directive: $opt_directive"
puts "Vivado place directive: $place_directive"
if {$place_subdirective ne ""} {
    puts "Vivado place subdirective: $place_subdirective"
}
puts "Vivado phys_opt directive: $phys_directive"
puts "Vivado route directive: $route_directive"
puts "Vivado route tns_cleanup: $route_tns_cleanup"
puts "Vivado route ultrathreads: $route_ultrathreads"

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
opt_design -directive $opt_directive

#------------------------------------------------------------------------------
# Placement
#------------------------------------------------------------------------------
puts "Running Placement..."
if {$place_subdirective ne ""} {
    place_design -directive $place_directive -subdirective $place_subdirective
} else {
    place_design -directive $place_directive
}

report_utilization -file "$reports_dir/post_place_utilization.rpt"
report_timing_summary -file "$reports_dir/post_place_timing.rpt"

write_checkpoint -force "$build_dir/post_place.dcp"

#------------------------------------------------------------------------------
# Physical Optimization
#------------------------------------------------------------------------------
puts "Running Physical Optimization..."
phys_opt_design -directive $phys_directive

#------------------------------------------------------------------------------
# Routing
#------------------------------------------------------------------------------
puts "Running Routing..."
set route_args [list -directive $route_directive]
if {$route_tns_cleanup} {
    lappend route_args -tns_cleanup
}
if {$route_ultrathreads} {
    lappend route_args -ultrathreads
}
route_design {*}$route_args

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
