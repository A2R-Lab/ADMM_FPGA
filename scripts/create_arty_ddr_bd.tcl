#------------------------------------------------------------------------------
# Create Arty A7 DDR3 block design for ADMM DDR offload path
#------------------------------------------------------------------------------
# Prerequisites:
#  1) MIG project exists at scripts/mig_arty_a7.prj
#  2) HLS IP exported:
#       - make hls-ddr
#       - make hls-loader
#------------------------------------------------------------------------------

proc fail_with {msg} {
    puts "ERROR: $msg"
    exit 1
}

proc first_existing_pin {cell candidates} {
    foreach candidate $candidates {
        set pin [get_bd_pins -quiet "${cell}/${candidate}"]
        if {[llength $pin] > 0} {
            return $pin
        }
    }
    return ""
}

proc first_existing_intf {cell candidates} {
    foreach candidate $candidates {
        set intf [get_bd_intf_pins -quiet "${cell}/${candidate}"]
        if {[llength $intf] > 0} {
            return $intf
        }
    }
    return ""
}

proc connect_if_pin_exists {src_pin dst_pin_path} {
    if {[llength $src_pin] == 0} {
        return
    }
    set dst_pin [get_bd_pins -quiet $dst_pin_path]
    if {[llength $dst_pin] > 0} {
        connect_bd_net $src_pin $dst_pin
    }
}

proc make_external_pin_if_exists {pin_path} {
    set pin [get_bd_pins -quiet $pin_path]
    if {[llength $pin] > 0} {
        make_bd_pins_external $pin
    }
}

proc make_external_intf_if_exists {intf_path} {
    set intf [get_bd_intf_pins -quiet $intf_path]
    if {[llength $intf] > 0} {
        make_bd_intf_pins_external $intf
    }
}

set script_dir [file normalize [file dirname [info script]]]
set proj_root [file normalize "$script_dir/.."]
set build_dir [file normalize "$proj_root/build/ddr_bd"]
set mig_xml_src [file normalize "$script_dir/mig_arty_a7.prj"]
set mig_xml_local [file normalize "$build_dir/mig_arty_a7.prj"]

if {![file exists $mig_xml_src]} {
    fail_with "Missing MIG config file: $mig_xml_src"
}

set hls_ddr_ip_repo [file normalize "$proj_root/vitis_projects/ADMM/ADMM_ddr/hls/impl/ip"]
set hls_loader_ip_repo [file normalize "$proj_root/vitis_projects/ADMM/matrix_loader/hls/impl/ip"]

if {![file exists "$hls_ddr_ip_repo/component.xml"]} {
    fail_with "DDR solver HLS IP not found at $hls_ddr_ip_repo. Run: make hls-ddr"
}
if {![file exists "$hls_loader_ip_repo/component.xml"]} {
    fail_with "Matrix loader HLS IP not found at $hls_loader_ip_repo. Run: make hls-loader"
}

file mkdir $build_dir
file copy -force $mig_xml_src $mig_xml_local

create_project ddr_bd $build_dir -part xc7a100tcsg324-1 -force
set_property ip_repo_paths [list $hls_ddr_ip_repo $hls_loader_ip_repo] [current_project]
update_ip_catalog

create_bd_design "admm_ddr_system"

# Core IP
create_bd_cell -type ip -vlnv xilinx.com:ip:mig_7series:4.2 mig_0
set_property -dict [list CONFIG.XML_INPUT_FILE $mig_xml_local] [get_bd_cells mig_0]

create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 proc_sys_reset_0
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect_0
set_property -dict [list CONFIG.NUM_MI {1} CONFIG.NUM_SI {2}] [get_bd_cells axi_interconnect_0]
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clk_wiz_ref200
set_property -dict [list \
    CONFIG.PRIM_IN_FREQ {100.000} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {100.000} \
    CONFIG.CLKOUT2_USED {true} \
    CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {200.000} \
] [get_bd_cells clk_wiz_ref200]

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_quad_spi:3.2 axi_quad_spi_0
set_property -dict [list \
    CONFIG.C_SPI_MEMORY {1} \
    CONFIG.C_XIP_MODE {1} \
    CONFIG.C_TYPE_OF_AXI4_INTERFACE {1} \
    CONFIG.C_USE_STARTUP {1} \
    CONFIG.C_SPI_MEM_ADDR_BITS {24} \
] [get_bd_cells axi_quad_spi_0]

create_bd_cell -type ip -vlnv xilinx.com:hls:ADMM_solver_ddr:1.0 ADMM_solver_ddr_0
create_bd_cell -type ip -vlnv xilinx.com:hls:matrix_loader:1.0 matrix_loader_0

# External system clock/reset feeding MIG clocking fabric
set ddr_ref_clk [create_bd_port -dir I -type clk -freq_hz 100000000 ddr_ref_clk]
set ddr_sys_rst [create_bd_port -dir I -type rst ddr_sys_rst]
set_property -dict [list CONFIG.POLARITY {ACTIVE_HIGH}] $ddr_sys_rst

connect_bd_net $ddr_sys_rst [get_bd_pins mig_0/sys_rst]

# Generate both MIG clocks from a single buffered board clock:
# - clk_out1: 100MHz system clock to mig_0/sys_clk_i (MIG SYSCLK_TYPE=NO_BUFFER)
# - clk_out2: 200MHz reference clock to mig_0/clk_ref_i
connect_bd_net $ddr_ref_clk [get_bd_pins clk_wiz_ref200/clk_in1]
connect_if_pin_exists $ddr_sys_rst "clk_wiz_ref200/reset"
connect_if_pin_exists [get_bd_pins clk_wiz_ref200/clk_out1] "mig_0/sys_clk_i"
connect_if_pin_exists [get_bd_pins clk_wiz_ref200/clk_out2] "mig_0/clk_ref_i"

# Use MIG UI clock for all AXI logic
set ui_clk [get_bd_pins mig_0/ui_clk]
connect_if_pin_exists $ui_clk "axi_interconnect_0/ACLK"
connect_if_pin_exists $ui_clk "axi_interconnect_0/S00_ACLK"
connect_if_pin_exists $ui_clk "axi_interconnect_0/S01_ACLK"
connect_if_pin_exists $ui_clk "axi_interconnect_0/M00_ACLK"
connect_if_pin_exists $ui_clk "ADMM_solver_ddr_0/ap_clk"
connect_if_pin_exists $ui_clk "matrix_loader_0/ap_clk"
connect_if_pin_exists $ui_clk "axi_quad_spi_0/s_axi4_aclk"
connect_if_pin_exists $ui_clk "axi_quad_spi_0/s_axi_aclk"
connect_if_pin_exists $ui_clk "axi_quad_spi_0/ext_spi_clk"

# Reset generation synchronized to MIG UI clock
connect_bd_net $ui_clk [get_bd_pins proc_sys_reset_0/slowest_sync_clk]
connect_bd_net $ddr_sys_rst [get_bd_pins proc_sys_reset_0/ext_reset_in]
connect_bd_net [get_bd_pins mig_0/ui_clk_sync_rst] [get_bd_pins proc_sys_reset_0/aux_reset_in]
connect_bd_net [get_bd_pins mig_0/mmcm_locked] [get_bd_pins proc_sys_reset_0/dcm_locked]

set periph_aresetn [get_bd_pins proc_sys_reset_0/peripheral_aresetn]
set periph_reset [get_bd_pins proc_sys_reset_0/peripheral_reset]
connect_if_pin_exists $periph_aresetn "axi_interconnect_0/ARESETN"
connect_if_pin_exists $periph_aresetn "axi_interconnect_0/S00_ARESETN"
connect_if_pin_exists $periph_aresetn "axi_interconnect_0/S01_ARESETN"
connect_if_pin_exists $periph_aresetn "axi_interconnect_0/M00_ARESETN"
connect_if_pin_exists $periph_aresetn "mig_0/aresetn"
connect_if_pin_exists $periph_aresetn "axi_quad_spi_0/s_axi4_aresetn"
connect_if_pin_exists $periph_aresetn "axi_quad_spi_0/s_axi_aresetn"

set solver_rst_n [first_existing_pin ADMM_solver_ddr_0 {ap_rst_n}]
if {$solver_rst_n ne ""} { connect_bd_net $periph_aresetn $solver_rst_n }
set solver_rst [first_existing_pin ADMM_solver_ddr_0 {ap_rst}]
if {$solver_rst ne ""} { connect_bd_net $periph_reset $solver_rst }

set loader_rst_n [first_existing_pin matrix_loader_0 {ap_rst_n}]
if {$loader_rst_n ne ""} { connect_bd_net $periph_aresetn $loader_rst_n }
set loader_rst [first_existing_pin matrix_loader_0 {ap_rst}]
if {$loader_rst ne ""} { connect_bd_net $periph_reset $loader_rst }

# AXI data paths
set solver_axi [first_existing_intf ADMM_solver_ddr_0 {m_axi_gmem gmem}]
if {$solver_axi eq ""} {
    fail_with "ADMM_solver_ddr AXI master interface not found (expected m_axi_gmem/gmem)."
}
set loader_ddr_axi [first_existing_intf matrix_loader_0 {m_axi_ddr ddr}]
if {$loader_ddr_axi eq ""} {
    fail_with "matrix_loader DDR AXI master interface not found (expected m_axi_ddr/ddr)."
}
set loader_flash_axi [first_existing_intf matrix_loader_0 {m_axi_flash flash}]
if {$loader_flash_axi eq ""} {
    fail_with "matrix_loader flash AXI master interface not found (expected m_axi_flash/flash)."
}
set spi_axi_full [first_existing_intf axi_quad_spi_0 {AXI_FULL}]
if {$spi_axi_full eq ""} {
    fail_with "axi_quad_spi AXI_FULL interface not found."
}

connect_bd_intf_net $solver_axi [get_bd_intf_pins axi_interconnect_0/S00_AXI]
connect_bd_intf_net $loader_ddr_axi [get_bd_intf_pins axi_interconnect_0/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M00_AXI] [get_bd_intf_pins mig_0/S_AXI]
connect_bd_intf_net $loader_flash_axi $spi_axi_full

# External interfaces/pins for system integration
make_external_intf_if_exists "mig_0/DDR3"
make_external_pin_if_exists "mig_0/init_calib_complete"

# Export MIG UI clock/reset with deterministic top-level names.
set ui_clk_out [create_bd_port -dir O -type clk ui_clk_0]
connect_bd_net $ui_clk_out [get_bd_pins mig_0/ui_clk]
set ui_rst_out [create_bd_port -dir O -type rst ui_clk_sync_rst_0]
set_property -dict [list CONFIG.POLARITY {ACTIVE_HIGH}] $ui_rst_out
connect_bd_net $ui_rst_out [get_bd_pins mig_0/ui_clk_sync_rst]

make_external_intf_if_exists "ADMM_solver_ddr_0/ap_ctrl"
make_external_pin_if_exists "ADMM_solver_ddr_0/current_in"
make_external_pin_if_exists "ADMM_solver_ddr_0/command_out"
make_external_pin_if_exists "ADMM_solver_ddr_0/command_out_ap_vld"
make_external_pin_if_exists "ADMM_solver_ddr_0/matrix_blob"

make_external_intf_if_exists "matrix_loader_0/ap_ctrl"
make_external_pin_if_exists "matrix_loader_0/flash_blob"
make_external_pin_if_exists "matrix_loader_0/ddr_blob"
make_external_pin_if_exists "matrix_loader_0/word_count"
make_external_pin_if_exists "matrix_loader_0/checksum_out"
make_external_pin_if_exists "matrix_loader_0/checksum_out_ap_vld"

make_external_intf_if_exists "axi_quad_spi_0/SPI_0"
make_external_intf_if_exists "axi_quad_spi_0/STARTUP_IO"

assign_bd_address

# AXI Quad SPI exposes MEM0 as register space; force-include for XIP data reads.
set flash_addr_space [get_bd_addr_spaces -quiet "matrix_loader_0/Data_m_axi_flash"]
if {[llength $flash_addr_space] > 0} {
    foreach seg [get_bd_addr_segs -quiet -of_objects $flash_addr_space] {
        if {[string first "axi_quad_spi_0" [get_property NAME $seg]] >= 0} {
            include_bd_addr_seg $seg
        }
    }
}

validate_bd_design
save_bd_design

puts "========================================="
puts "Created block design: admm_ddr_system"
puts "Project directory: $build_dir"
puts "MIG config copied to: $mig_xml_local"
puts "Next steps:"
puts "  1) Generate wrapper HDL: make_wrapper -files [get_files */admm_ddr_system.bd] -top"
puts "  2) Add board XDC constraints for DDR3, QSPI, UART/control pins"
puts "  3) Hook boot FSM: wait init_calib_complete -> run matrix_loader -> run solver"
puts "========================================="
