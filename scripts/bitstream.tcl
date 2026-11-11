#------------------------------------------------------------------------------
# Vivado Bitstream Generation Script
#------------------------------------------------------------------------------

set script_dir [file dirname [info script]]
set proj_root [file normalize "$script_dir/.."]

set build_dir "$proj_root/build"
if {[llength $argv] >= 1} {
    set top_module [lindex $argv 0]
} else {
    set top_module "top_spi"
}
if {[llength $argv] >= 2} {
    set route_dcp [lindex $argv 1]
} else {
    set route_dcp "post_route.dcp"
}
puts "Bitstream top module: $top_module"

#------------------------------------------------------------------------------
# Open Routed Checkpoint
#------------------------------------------------------------------------------
puts "Opening routed checkpoint..."
open_checkpoint "$build_dir/$route_dcp"

#------------------------------------------------------------------------------
# Generate Bitstream
#------------------------------------------------------------------------------
if {$top_module eq "top_uart_power"} {
    if {[llength [get_clocks sys_clk]] != 1} {
        error "Missing benchmark clock constraint"
    }
    foreach delay_type {max min} {
        set worst_path [get_timing_paths -delay_type $delay_type -max_paths 1]
        if {[llength $worst_path] == 0 || [get_property SLACK $worst_path] < 0} {
            error "Power benchmark has failing or missing $delay_type timing; refusing bitstream"
        }
    }
}
puts "Generating bitstream..."
write_bitstream -force "$build_dir/${top_module}.bit"

#------------------------------------------------------------------------------
# Generate Flash Binary (SPI x4, 16MB flash)
#------------------------------------------------------------------------------
puts "Generating flash binary..."
write_cfgmem -format bin -interface spix4 -size 16 \
    -loadbit "up 0x0 $build_dir/${top_module}.bit" \
    -force -file "$build_dir/${top_module}.bin"

puts "========================================="
puts "Bitstream: $build_dir/${top_module}.bit"
puts "Flash bin: $build_dir/${top_module}.bin"
puts "========================================="
