# Run the PROFILE=1 top_tb snapshot from build/power/hls_sim.
# The bench stops at each phase boundary, excluding startup and UART download.
run all
set activity_objects [get_objects -r /power_activity_tb/test/dut/*]
foreach phase {idle_before active idle_after} {
    open_saif "../activity_${phase}.saif"
    log_saif $activity_objects
    run all
    close_saif
}
run all
quit
