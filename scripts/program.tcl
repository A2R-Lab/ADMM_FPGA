#------------------------------------------------------------------------------
# FPGA Programming Script
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

# Check if bitstream exists
if {![file exists $bitstream]} {
    puts "ERROR: Bitstream not found: $bitstream"
    puts "Please run build first."
    exit 1
}

# Open hardware manager
open_hw_manager

# Connect to hardware server
connect_hw_server -allow_non_jtag

# Get the first available target
set targets [get_hw_targets]
if {[llength $targets] == 0} {
    puts "ERROR: No hardware targets found. Check cable connection."
    close_hw_manager
    exit 1
}

# Open target and device
open_hw_target [lindex $targets 0]
set device [lindex [get_hw_devices] 0]
current_hw_device $device

# Set the programming file
set_property PROGRAM.FILE $bitstream $device

# Program the device
puts "Programming device with: $bitstream"
program_hw_devices $device

puts "Programming complete!"

# Close hardware manager
close_hw_target
close_hw_manager
