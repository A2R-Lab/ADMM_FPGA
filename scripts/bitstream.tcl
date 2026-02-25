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
puts "Bitstream top module: $top_module"

#------------------------------------------------------------------------------
# Open Routed Checkpoint
#------------------------------------------------------------------------------
puts "Opening routed checkpoint..."
open_checkpoint "$build_dir/post_route.dcp"

#------------------------------------------------------------------------------
# Generate Bitstream
#------------------------------------------------------------------------------
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
