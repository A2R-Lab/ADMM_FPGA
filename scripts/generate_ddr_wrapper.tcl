#------------------------------------------------------------------------------
# Generate HDL wrapper for admm_ddr_system block design
#------------------------------------------------------------------------------

set script_dir [file normalize [file dirname [info script]]]
set proj_root [file normalize "$script_dir/.."]
set ddr_proj "$proj_root/build/ddr_bd/ddr_bd.xpr"
set ddr_bd "$proj_root/build/ddr_bd/ddr_bd.srcs/sources_1/bd/admm_ddr_system/admm_ddr_system.bd"

if {![file exists $ddr_proj]} {
    puts "ERROR: Missing DDR Vivado project: $ddr_proj"
    puts "Run: vivado -mode batch -source scripts/create_arty_ddr_bd.tcl"
    exit 1
}

if {![file exists $ddr_bd]} {
    puts "ERROR: Missing block design file: $ddr_bd"
    puts "Run: vivado -mode batch -source scripts/create_arty_ddr_bd.tcl"
    exit 1
}

open_project $ddr_proj
open_bd_design $ddr_bd

generate_target synthesis [get_files $ddr_bd]
make_wrapper -files [get_files $ddr_bd] -top

puts "========================================="
puts "Generated wrapper for admm_ddr_system"
puts "  $proj_root/build/ddr_bd/ddr_bd.gen/sources_1/bd/admm_ddr_system/hdl/admm_ddr_system_wrapper.v"
puts "========================================="
