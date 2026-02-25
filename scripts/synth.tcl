#------------------------------------------------------------------------------
# Vivado Synthesis Script (Non-Project Mode)
#------------------------------------------------------------------------------

set script_dir [file dirname [info script]]
set proj_root [file normalize "$script_dir/.."]

set build_dir "$proj_root/build"
set reports_dir "$build_dir/reports"

file mkdir $build_dir
file mkdir $reports_dir

#------------------------------------------------------------------------------
# Configuration (top_module and xdc_file can be passed via -tclargs)
#------------------------------------------------------------------------------
set part "xc7a100tcsg324-1"
if {[llength $argv] >= 2} {
    set top_module [lindex $argv 0]
    set xdc_file [lindex $argv 1]
} else {
    set top_module "top_spi"
    set xdc_file "constraints.xdc"
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
read_verilog "$rtl_dir/top_uart.v"
read_verilog "$rtl_dir/uart_rx.v"
read_verilog "$rtl_dir/uart_tx.v"
read_verilog "$rtl_dir/top_spi.v"
read_verilog "$rtl_dir/spi_slave.v"
read_verilog "$rtl_dir/spi_slave_word.v"

#------------------------------------------------------------------------------
# Read HLS IP
#------------------------------------------------------------------------------
if {[file exists "$hls_export_dir/hdl/verilog"]} {
    puts "Reading HLS IP from: $hls_export_dir"
    
    foreach f [glob -nocomplain $hls_export_dir/hdl/verilog/*.v] {
        read_verilog $f
    }
} else {
    puts "ERROR: HLS IP not found at $hls_export_dir"
    puts "Run 'make hls' first."
    exit 1
}

#------------------------------------------------------------------------------
# Read Constraints
#------------------------------------------------------------------------------
puts "Reading constraints..."
read_xdc "$xdc_dir/$xdc_file"

#------------------------------------------------------------------------------
# Synthesis
#------------------------------------------------------------------------------
puts "Running Synthesis..."

synth_design -top $top_module -part $part \
    -flatten_hierarchy rebuilt \
    -directive Default

#------------------------------------------------------------------------------
# Reports
#------------------------------------------------------------------------------
report_utilization -file "$reports_dir/post_synth_utilization.rpt"
report_timing_summary -file "$reports_dir/post_synth_timing.rpt"

#------------------------------------------------------------------------------
# Save Checkpoint
#------------------------------------------------------------------------------
write_checkpoint -force "$build_dir/post_synth.dcp"

puts "========================================"
puts "Synthesis complete!"
puts "Checkpoint: $build_dir/post_synth.dcp"
puts "========================================"
