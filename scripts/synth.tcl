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
set hls_ddr_export_dir "$proj_root/vitis_projects/ADMM/ADMM_ddr/hls/impl/ip/hdl/verilog"
set hls_loader_export_dir "$proj_root/vitis_projects/ADMM/matrix_loader/hls/impl/ip/hdl/verilog"
set ddr_bd_dir "$proj_root/build/ddr_bd"
set ddr_bd_ipshared_dir "$ddr_bd_dir/ddr_bd.gen/sources_1/bd/admm_ddr_system/ipshared"
set xpm_root "$::env(XILINX_VIVADO)/data/ip/xpm"
set xilinx_ip_root "$::env(XILINX_VIVADO)/data/ip/xilinx"
set ddr_bd_synth "$ddr_bd_dir/ddr_bd.gen/sources_1/bd/admm_ddr_system/synth/admm_ddr_system.v"
set ddr_bd_wrapper "$ddr_bd_dir/ddr_bd.gen/sources_1/bd/admm_ddr_system/hdl/admm_ddr_system_wrapper.v"
set ddr_bd_ip_dir "$ddr_bd_dir/ddr_bd.gen/sources_1/bd/admm_ddr_system/ip"
set ddr_mig_xdc "$ddr_bd_dir/ddr_bd.gen/sources_1/bd/admm_ddr_system/ip/admm_ddr_system_mig_0_0/admm_ddr_system_mig_0_0/user_design/constraints/admm_ddr_system_mig_0_0.xdc"

puts "Top module: $top_module"
puts "Constraints: $xdc_file"

proc read_hdl_tree {root_dir allow_vhdl} {
    if {![file exists $root_dir]} {
        return
    }
    foreach item [glob -nocomplain -directory $root_dir *] {
        if {[file isdirectory $item]} {
            set leaf [file tail $item]
            if {$leaf eq "sim" || $leaf eq "example_design"} {
                continue
            }
            read_hdl_tree $item $allow_vhdl
        } elseif {[string equal [file extension $item] ".v"]} {
            read_verilog $item
        } elseif {[string equal [file extension $item] ".sv"]} {
            read_verilog -sv $item
        } elseif {$allow_vhdl && ([string equal [file extension $item] ".vhd"] || [string equal [file extension $item] ".vhdl"])} {
            read_vhdl $item
        }
    }
}

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
read_verilog "$rtl_dir/telemetry_counters.v"

#------------------------------------------------------------------------------
# Read design-specific generated IP/netlists
#------------------------------------------------------------------------------
if {[string equal $top_module "top"]} {
    if {![file exists $ddr_bd_synth] || ![file exists $ddr_bd_wrapper]} {
        puts "ERROR: DDR block-design netlists not found."
        puts "Expected:"
        puts "  $ddr_bd_synth"
        puts "  $ddr_bd_wrapper"
        puts "Run: vivado -mode batch -source scripts/create_arty_ddr_bd.tcl"
        puts "Then: make_wrapper -files [get_files */admm_ddr_system.bd] -top"
        exit 1
    }

    puts "Reading DDR BD netlists..."
    read_verilog $ddr_bd_synth
    read_hdl_tree $ddr_bd_ip_dir 1
    if {[file exists $ddr_bd_ipshared_dir]} {
        set ipshared_inc_dirs [concat \
            [glob -nocomplain -type d "$ddr_bd_ipshared_dir/*/hdl"] \
            [glob -nocomplain -type d "$ddr_bd_ipshared_dir/*/hdl/verilog"]]
        if {[llength $ipshared_inc_dirs] > 0} {
            set_property include_dirs $ipshared_inc_dirs [current_fileset]
        }
        # Load XPM library sources required by some AMD VHDL IP wrappers.
        if {[file exists "$xpm_root/xpm_VCOMP.vhd"]} {
            read_vhdl -library xpm "$xpm_root/xpm_VCOMP.vhd"
        }
        foreach rel {
            xpm_cdc/hdl/xpm_cdc.sv
            xpm_fifo/hdl/xpm_fifo.sv
            xpm_memory/hdl/xpm_memory.sv
            xpm_axi32/hdl/xpm_axi32.sv
            xpm_pmc_bridge/hdl/xpm_pmc_bridge.sv
        } {
            set f "$xpm_root/$rel"
            if {[file exists $f]} {
                read_verilog -sv -library xpm $f
            }
        }
        # Compile key AMD IP VHDL into their expected libraries so wrappers
        # do not remain black boxes in implementation.
        foreach f [glob -nocomplain "$ddr_bd_ipshared_dir/*/hdl/axi_lite_ipif*_rfs.vhd"] {
            read_vhdl -library axi_lite_ipif_v3_0_4 $f
        }
        foreach f [glob -nocomplain "$ddr_bd_ipshared_dir/*/hdl/interrupt_control*_rfs.vhd"] {
            read_vhdl -library interrupt_control_v3_1_5 $f
        }
        set dist_mem_vhd "$xilinx_ip_root/dist_mem_gen_v8_0/hdl/dist_mem_gen_v8_0_vhsyn_rfs.vhd"
        if {[file exists $dist_mem_vhd]} {
            read_vhdl -library dist_mem_gen_v8_0_17 $dist_mem_vhd
        }
        foreach f [glob -nocomplain "$ddr_bd_ipshared_dir/*/hdl/proc_sys_reset*_rfs.vhd"] {
            read_vhdl -library proc_sys_reset_v5_0_17 $f
        }
        foreach f [glob -nocomplain "$ddr_bd_ipshared_dir/*/hdl/axi_quad_spi*_rfs.vhd"] {
            read_vhdl -library axi_quad_spi_v3_2_35 $f
        }
        foreach f [glob -nocomplain "$ddr_bd_ipshared_dir/*/hdl/*.v"] {
            if {[regexp {/(ADMM_solver_ddr|matrix_loader)} $f]} {
                continue
            }
            read_verilog $f
        }
        foreach f [glob -nocomplain "$ddr_bd_ipshared_dir/*/hdl/verilog/*.v"] {
            if {[regexp {/(ADMM_solver_ddr|matrix_loader)} $f]} {
                continue
            }
            read_verilog $f
        }
    }
    if {[file exists $hls_ddr_export_dir]} {
        foreach f [glob -nocomplain "$hls_ddr_export_dir/*.v"] {
            read_verilog $f
        }
    } else {
        puts "ERROR: DDR solver HLS RTL not found at: $hls_ddr_export_dir"
        puts "Run: make hls-ddr"
        exit 1
    }
    if {[file exists $hls_loader_export_dir]} {
        foreach f [glob -nocomplain "$hls_loader_export_dir/*.v"] {
            read_verilog $f
        }
    } else {
        puts "ERROR: Matrix loader HLS RTL not found at: $hls_loader_export_dir"
        puts "Run: make hls-loader"
        exit 1
    }
    read_verilog $ddr_bd_wrapper
} else {
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
}

#------------------------------------------------------------------------------
# Read Constraints
#------------------------------------------------------------------------------
puts "Reading constraints..."
read_xdc "$xdc_dir/$xdc_file"
if {[string equal $top_module "top"]} {
    if {![file exists $ddr_mig_xdc]} {
        puts "ERROR: MIG constraints not found at: $ddr_mig_xdc"
        puts "Run: vivado -mode batch -source scripts/create_arty_ddr_bd.tcl"
        exit 1
    }
    puts "Reading MIG constraints..."
    read_xdc $ddr_mig_xdc
    # Arty A7 sys_clk_i (E3) is a 3.3V oscillator. MIG xdc may set LVCMOS25,
    # which conflicts with other Bank 35 pins (LEDs/UART). Force board voltage.
    if {[llength [get_ports -quiet sys_clk_i]] > 0} {
        puts "Overriding sys_clk_i IOSTANDARD to LVCMOS33 for Arty A7..."
        set_property IOSTANDARD LVCMOS33 [get_ports sys_clk_i]
        set_property PACKAGE_PIN E3 [get_ports sys_clk_i]
    }
}

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
