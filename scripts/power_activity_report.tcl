# Usage: vivado -mode batch -source scripts/power_activity_report.tcl
set root [file normalize "[file dirname [info script]]/.."]
set output "$root/build/power/activity_reports"
file mkdir $output
set phases {idle_before active idle_after}
if {[llength $argv]} { set phases $argv }
foreach phase $phases {
    if {$phase ni {idle_before active idle_after}} { error "Unknown phase: $phase" }
    open_checkpoint "$root/build/post_route_top_uart_power_arty-power.dcp"
    set trajectory_cells [get_cells -quiet -hier -filter {NAME =~ *traj*}]
    if {[llength $trajectory_cells] != 0} {
        error "Unexpected trajectory cells in power build: $trajectory_cells"
    }
    puts "Verified: no trajectory-named cells in routed design"
    read_saif -strip_path power_activity_tb/test/dut -out_file "$output/${phase}_annotation.txt" "$root/build/power/activity_${phase}.saif"
    report_power -hier all -hierarchical_depth 2 -advisory -file "$output/${phase}_power.rpt"
    report_switching_activity -static_probability -signal_rate -file "$output/${phase}_switching.rpt" \
        [get_nets -hier -filter {NAME =~ capture/*}]
    report_switching_activity -static_probability -signal_rate -file "$output/${phase}_memory_enables.rpt" \
        [get_pins -hier -filter {NAME =~ capture/* && (REF_PIN_NAME =~ EN* || REF_PIN_NAME =~ WE*)}]
    # Synthesis recodes the capture FSM, so generic RTL SAIF propagation can
    # incorrectly assign 50% read-enable duty. Prove this profile has no reads
    # before explicitly mapping that one control onto the physical RAM pins.
    set proof [exec python3 "$root/scripts/check_power_saif.py" "$root/build/power/activity_${phase}.saif"]
    set proof_file [open "$output/${phase}_read_enable_proof.json" w]
    puts $proof_file $proof
    close $proof_file
    set read_net [get_nets -quiet capture/ram_q0]
    set read_pins [get_pins -hier -filter {NAME =~ capture/mem_reg_*/ENBWREN}]
    if {[llength $read_net] != 1 || [llength $read_pins] != 29} {
        error "Trace RAM mapping changed; inspect the netlist before mapping read activity"
    }
    foreach pin $read_pins {
        if {[get_nets -of_objects $pin] ne $read_net} { error "Unexpected trace read enable: $pin" }
    }
    set_switching_activity -static_probability 0 -toggle_rate 0 $read_net
    report_power -hier all -hierarchical_depth 2 -file "$output/${phase}_read_checked_power.rpt"
    close_design
}
exit
