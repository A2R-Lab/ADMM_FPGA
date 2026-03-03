#------------------------------------------------------------------------------
# FPGA Programming Script from explicit bitstream path
#------------------------------------------------------------------------------

if {[llength $argv] < 1} {
    puts "ERROR: Usage: vivado -mode batch -source program_file.tcl -tclargs <bitstream.bit>"
    exit 1
}

set bitstream [file normalize [lindex $argv 0]]

if {![file exists $bitstream]} {
    puts "ERROR: Bitstream not found: $bitstream"
    exit 1
}

open_hw_manager
connect_hw_server -allow_non_jtag

set targets [get_hw_targets]
if {[llength $targets] == 0} {
    puts "ERROR: No hardware targets found. Check cable connection."
    close_hw_manager
    exit 1
}

open_hw_target [lindex $targets 0]
set device [lindex [get_hw_devices] 0]
current_hw_device $device
set_property PROGRAM.FILE $bitstream $device

puts "Programming device with: $bitstream"
program_hw_devices $device
puts "Programming complete!"

close_hw_target
close_hw_manager
