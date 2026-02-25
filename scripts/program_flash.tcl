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
    if {[file exists "$build_dir/top.bit"]} {
        set top_module "top"
    } else {
        set top_module "top_spi"
    }
}
set bitstream "$build_dir/${top_module}.bit"
set flash_mcs "$build_dir/${top_module}.mcs"
set matrix_blob "$build_dir/matrices.bin"
set matrix_blob_addr "0x00600000"

# Check if bitstream exists
if {![file exists $bitstream]} {
    puts "ERROR: Bitstream not found: $bitstream"
    exit 1
}

# Generate MCS file
puts "Generating MCS file..."
if {[file exists $matrix_blob]} {
    puts "Including matrix blob in MCS: $matrix_blob at $matrix_blob_addr"
    write_cfgmem -format mcs -interface spix4 -size 16 \
        -loadbit "up 0x0 $bitstream" \
        -loaddata "up $matrix_blob_addr $matrix_blob" \
        -force -file $flash_mcs
} else {
    puts "Matrix blob not found ($matrix_blob). Generating bitstream-only MCS."
    write_cfgmem -format mcs -interface spix4 -size 16 \
        -loadbit "up 0x0 $bitstream" \
        -force -file $flash_mcs
}

#------------------------------------------------------------------------------
# Hardware Manager - exactly as GUI does it
#------------------------------------------------------------------------------
open_hw_manager
connect_hw_server -allow_non_jtag

# Discover and open a concrete hardware target (same robust pattern as program.tcl)
set targets [get_hw_targets]
if {[llength $targets] == 0} {
    puts "ERROR: No hardware targets found. Check cable connection/permissions."
    close_hw_manager
    exit 1
}
open_hw_target [lindex $targets 0]

# Set current device (generic, do not hardcode instance name)
set devices [get_hw_devices]
if {[llength $devices] == 0} {
    puts "ERROR: No FPGA devices found on opened target."
    close_hw_target
    close_hw_manager
    exit 1
}
set device [lindex $devices 0]
current_hw_device $device
refresh_hw_device -update_hw_probes false $device

#------------------------------------------------------------------------------
# Create cfgmem - GUI style
#------------------------------------------------------------------------------
puts "Creating configuration memory..."
set cfgmem_parts [get_cfgmem_parts {s25fl128sxxxxxx0-spi-x1_x2_x4}]
if {[llength $cfgmem_parts] == 0} {
    puts "ERROR: SPI flash part s25fl128sxxxxxx0-spi-x1_x2_x4 not found in Vivado."
    close_hw_target
    close_hw_manager
    exit 1
}
create_hw_cfgmem -hw_device $device [lindex $cfgmem_parts 0]

set_property PROGRAM.BLANK_CHECK  0 [ get_property PROGRAM.HW_CFGMEM $device]
set_property PROGRAM.ERASE        1 [ get_property PROGRAM.HW_CFGMEM $device]
set_property PROGRAM.CFG_PROGRAM  1 [ get_property PROGRAM.HW_CFGMEM $device]
set_property PROGRAM.VERIFY       1 [ get_property PROGRAM.HW_CFGMEM $device]
set_property PROGRAM.CHECKSUM     0 [ get_property PROGRAM.HW_CFGMEM $device]

#------------------------------------------------------------------------------
# Set programming files
#------------------------------------------------------------------------------
set_property PROGRAM.ADDRESS_RANGE  {use_file} [ get_property PROGRAM.HW_CFGMEM $device]
set_property PROGRAM.FILES [list $flash_mcs ] [ get_property PROGRAM.HW_CFGMEM $device]
set_property PROGRAM.PRM_FILE {} [ get_property PROGRAM.HW_CFGMEM $device]
set_property PROGRAM.UNUSED_PIN_TERMINATION {pull-none} [ get_property PROGRAM.HW_CFGMEM $device]

#------------------------------------------------------------------------------
# Program
#------------------------------------------------------------------------------
puts "Programming flash..."
if {![string equal [get_property PROGRAM.HW_CFGMEM_TYPE $device] [get_property MEM_TYPE [get_property CFGMEM_PART [get_property PROGRAM.HW_CFGMEM $device]]]] }  {
    create_hw_bitstream -hw_device $device [get_property PROGRAM.HW_CFGMEM_BITFILE $device];
    program_hw_devices $device;
}

program_hw_cfgmem -hw_cfgmem [ get_property PROGRAM.HW_CFGMEM $device]

puts "Flash programming complete!"
puts "Booting FPGA from flash..."

# Boot the FPGA from the configuration memory (no power cycle needed)
boot_hw_device $device

puts "========================================="
puts "Done! FPGA is now running from flash."
puts "========================================="

close_hw_target
close_hw_manager
