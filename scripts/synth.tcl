#------------------------------------------------------------------------------
# Vivado Synthesis Script (Non-Project Mode)
#------------------------------------------------------------------------------

set script_dir [file dirname [info script]]
set proj_root [file normalize "$script_dir/.."]

set build_dir "$proj_root/build"
set reports_dir "$build_dir/reports"

file mkdir $build_dir
file mkdir $reports_dir

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

#------------------------------------------------------------------------------
# Configuration (top_module, xdc_file, and synth checkpoint name via -tclargs)
#------------------------------------------------------------------------------
set part "xc7a100tcsg324-1"
if {[llength $argv] >= 2} {
    set top_module [lindex $argv 0]
    set xdc_file [lindex $argv 1]
} else {
    set top_module "top_spi"
    set xdc_file "constraints.xdc"
}
if {[llength $argv] >= 3} {
    set synth_dcp [lindex $argv 2]
} else {
    set synth_dcp "post_synth.dcp"
}

set rtl_dir "$proj_root/vivado_project/vivado_project.srcs/sources_1/new"
set xdc_dir "$proj_root/vivado_project/vivado_project.srcs/constrs_1/new"
set hls_export_dir "$proj_root/vitis_projects/ADMM/ADMM/hls/impl/ip"

puts "Top module: $top_module"
puts "Constraints: $xdc_file"

#------------------------------------------------------------------------------
# Read RTL Sources (all tops and peripherals; synth_design -top selects which)
#------------------------------------------------------------------------------
puts "Reading RTL sources..."
set_property include_dirs [list $rtl_dir "$build_dir/power"] [current_fileset]
if {$top_module ne "top_uart_power"} { read_verilog "$rtl_dir/top_uart.v" }
read_verilog "$rtl_dir/uart_rx.v"
read_verilog "$rtl_dir/uart_tx.v"
if {$top_module ne "top_uart_power"} { read_verilog "$rtl_dir/top_spi.v" }
read_verilog "$rtl_dir/spi_slave.v"
read_verilog "$rtl_dir/spi_slave_word.v"

if {$top_module eq "top_uart_power"} {
    read_verilog "$rtl_dir/power_xadc.v"
    foreach f [glob "$rtl_dir/power_*.sv"] { read_verilog -sv $f }
    read_verilog -sv "$rtl_dir/top_uart_power.sv"
}

#------------------------------------------------------------------------------
# Read HLS IP
#------------------------------------------------------------------------------
# Missing initialization data is a build failure, never a usable bitstream.
set_msg_config -id {Synth 8-4445} -new_severity ERROR
if {$top_module eq "top_uart_power" && ![file exists "$build_dir/power/power_workload.mem"]} {
    error "Power workload ROM is missing"
}
set hls_syn "$proj_root/vitis_projects/ADMM/ADMM/hls/syn/verilog"
if {[file exists "$rtl_dir/power_tiny_adapter.sv"]} {
    # Use generated operator creation scripts, including floating-point IP.
    set old_pwd [pwd]
    cd $hls_syn
    foreach f [glob *.v] { read_verilog [file normalize $f] }
    foreach f [glob -nocomplain *.dat] { add_files -norecurse [file normalize $f] }
    foreach f [glob -nocomplain *.tcl] { source $f }
} elseif {[file exists "$hls_export_dir/hdl/verilog"]} {
    foreach f [glob "$hls_export_dir/hdl/verilog/*.v"] { read_verilog $f }
} else { error "HLS RTL missing" }
# The board workload uses a repository-relative ROM path. IP creation must not
# leave synthesis in the HLS directory. HLS initialization files are registered
# above and also resolve relative to their Verilog source files.
cd $proj_root

#------------------------------------------------------------------------------
# Read Constraints
#------------------------------------------------------------------------------
puts "Reading constraints..."
if {$top_module eq "top_uart_power"} { read_xdc "$xdc_dir/constraints_arty_a7.xdc" }
read_xdc "$xdc_dir/$xdc_file"

#------------------------------------------------------------------------------
# Synthesis
#------------------------------------------------------------------------------
puts "Running Synthesis..."

# A staged_a post-synthesis mismatch disappears when hierarchy is retained
# (with DSPs still enabled). Preserve hierarchy as a workaround; the precise
# optimization responsible has not been isolated. See docs/arty_comparison.md.
set flatten_mode rebuilt
if {![info exists ::env(ADMM_SOLVER_ARCH)] || $::env(ADMM_SOLVER_ARCH) eq "staged_a"} {
    set flatten_mode none
}
puts "Synthesis hierarchy policy: $flatten_mode"
synth_design -top $top_module -part $part \
    -flatten_hierarchy $flatten_mode \
    -directive Default

#------------------------------------------------------------------------------
# Reports
#------------------------------------------------------------------------------
if {$top_module eq "top_uart_power" && [llength [get_clocks sys_clk]] != 1} {
    error "Power benchmark requires its 100 MHz sys_clk constraint"
}
report_utilization -file "$reports_dir/post_synth_utilization.rpt"
report_timing_summary -file "$reports_dir/post_synth_timing.rpt"
report_power -file "$reports_dir/post_synth_power.rpt"

#------------------------------------------------------------------------------
# Save Checkpoint
#------------------------------------------------------------------------------
write_checkpoint -force "$build_dir/$synth_dcp"

set synth_root [file rootname $synth_dcp]
set funcsim_netlist "$build_dir/${synth_root}_funcsim.v"
puts "Writing functional simulation netlist: $funcsim_netlist"
write_verilog -mode funcsim -force $funcsim_netlist

puts "========================================"
puts "Synthesis complete!"
puts "Checkpoint: $build_dir/$synth_dcp"
puts "========================================"
