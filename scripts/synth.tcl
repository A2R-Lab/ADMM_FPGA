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

# Ensure the in-memory project uses the target part before any IP creation/import.
set_part $part

set rtl_dir "$proj_root/vivado_project/vivado_project.srcs/sources_1/new"
set xdc_dir "$proj_root/vivado_project/vivado_project.srcs/constrs_1/new"
set hls_export_dir "$proj_root/vitis_projects/ADMM/ADMM/hls/impl/ip"
set hls_impl_verilog_dir "$proj_root/vitis_projects/ADMM/ADMM/hls/impl/verilog"

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
set hls_verilog_dir "$hls_export_dir/hdl/verilog"
set hls_ip_dir "$hls_export_dir/hdl/ip"

if {[file exists $hls_verilog_dir]} {
    # Floating-point HLS designs provide Tcl recipes to create required sub-IPs.
    set ip_tcl_files [glob -nocomplain $hls_impl_verilog_dir/*_ip.tcl]
    if {[llength $ip_tcl_files] > 0} {
        puts "Generating [llength $ip_tcl_files] HLS floating-point sub-IPs..."
        foreach ip_tcl $ip_tcl_files {
            source $ip_tcl
        }
    } else {
        # Fallback for flows that only export XCI files.
        set xci_files [glob -nocomplain $hls_ip_dir/*/*.xci]
        if {[llength $xci_files] > 0} {
            puts "Reading [llength $xci_files] HLS sub-IP XCI files..."
            foreach ip_xci $xci_files {
                read_ip $ip_xci
            }

            set hls_sub_ips [get_ips]
            if {[llength $hls_sub_ips] > 0} {
                puts "Generating synthesis targets for HLS sub-IPs..."
                generate_target synthesis $hls_sub_ips
            }
        }
    }

    puts "Reading HLS RTL from: $hls_verilog_dir"

    foreach f [glob -nocomplain $hls_verilog_dir/*.v] {
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
write_checkpoint -force "$build_dir/$synth_dcp"

puts "========================================"
puts "Synthesis complete!"
puts "Checkpoint: $build_dir/$synth_dcp"
puts "========================================"
