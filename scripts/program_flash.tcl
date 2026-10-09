#------------------------------------------------------------------------------
# SPI Flash Programming Script (JTAG Indirect)
# Matches Vivado GUI flow exactly
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
    set bitstream [file normalize [lindex $argv 1]]
} else {
    set bitstream "$build_dir/${top_module}.bit"
}
set flash_mcs "$build_dir/${top_module}.mcs"

# Check if bitstream exists
if {![file exists $bitstream]} {
    puts "ERROR: Bitstream not found: $bitstream"
    exit 1
}

# Generate MCS file
puts "Generating MCS file..."
write_cfgmem -format mcs -interface spix4 -size 16 \
    -loadbit "up 0x0 $bitstream" \
    -force -file $flash_mcs

#------------------------------------------------------------------------------
# Hardware Manager - exactly as GUI does it
#------------------------------------------------------------------------------
open_hw_manager
connect_hw_server -allow_non_jtag
open_hw_target

# Set current device
current_hw_device [lindex [get_hw_devices xc7a100t_0] 0]
refresh_hw_device -update_hw_probes false [current_hw_device]

#------------------------------------------------------------------------------
# Create cfgmem - GUI style
#------------------------------------------------------------------------------
puts "Creating configuration memory..."
create_hw_cfgmem -hw_device [current_hw_device] [lindex [get_cfgmem_parts {s25fl128sxxxxxx0-spi-x1_x2_x4}] 0]

set_property PROGRAM.BLANK_CHECK  0 [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]
set_property PROGRAM.ERASE        1 [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]
set_property PROGRAM.CFG_PROGRAM  1 [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]
set_property PROGRAM.VERIFY       1 [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]
set_property PROGRAM.CHECKSUM     0 [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]

#------------------------------------------------------------------------------
# Set programming files
#------------------------------------------------------------------------------
set_property PROGRAM.ADDRESS_RANGE  {use_file} [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]
set_property PROGRAM.FILES [list $flash_mcs ] [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]
set_property PROGRAM.PRM_FILE {} [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]
set_property PROGRAM.UNUSED_PIN_TERMINATION {pull-none} [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]

#------------------------------------------------------------------------------
# Program
#------------------------------------------------------------------------------
puts "Programming flash..."
if {![string equal [get_property PROGRAM.HW_CFGMEM_TYPE  [current_hw_device]] [get_property MEM_TYPE [get_property CFGMEM_PART [get_property PROGRAM.HW_CFGMEM [current_hw_device ]]]]] }  {
    create_hw_bitstream -hw_device [current_hw_device] [get_property PROGRAM.HW_CFGMEM_BITFILE [ current_hw_device]];
    program_hw_devices [current_hw_device];
}

program_hw_cfgmem -hw_cfgmem [ get_property PROGRAM.HW_CFGMEM [current_hw_device]]

puts "Flash programming complete!"
puts "Booting FPGA from flash..."

# Boot the FPGA from the configuration memory (no power cycle needed)
boot_hw_device [current_hw_device]

puts "========================================="
puts "Done! FPGA is now running from flash."
puts "========================================="

close_hw_target
close_hw_manager
