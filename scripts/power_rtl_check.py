"""Eight-transaction real-HLS check of the acquisition scheduler and solver adapter."""
from pathlib import Path
import re
import subprocess


def check(work, env, log, reference, run):
    sim=work/'build/measurement_rtl';sim.mkdir(parents=True,exist_ok=True)
    rtl=work/'vivado_project/vivado_project.srcs/sources_1/new'
    hls=work/'vitis_projects/ADMM/ADMM/hls/syn/verilog'
    tb=(work/'tests/solver_tb.sv').read_text()
    tb=tb.replace('reg [127:0] golden[0:4];integer seen=0;','integer seen=0;')
    tb=tb.replace('    initial $readmemh("../golden.mem",golden);','')
    tb=tb.replace('../test_workload/power_workload.mem',str(work/'build/power/power_workload.mem'))
    tb=tb.replace('five warm-started solves match C++ bit-for-bit','eight scheduler transactions completed')
    tb=tb.replace("32'd5","32'd8").replace('n!=5 || seen!=5','n!=8 || seen!=8')
    tb=re.sub(r'        if\(result!==golden\[seen\]\).*?;',r'        $display("RESULT %h",result);',tb)
    (sim/'solver_tb.sv').write_text(tb)
    tcl=f'''create_project -force power_check {sim}/project -part xc7a100t-csg324-1
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]
cd {hls}
add_files [glob *.v]
foreach data [glob -nocomplain *.dat] {{ add_files -fileset sim_1 $data }}
foreach script [glob -nocomplain *.tcl] {{ source $script }}
add_files -fileset sim_1 [list {rtl}/power_benchmark.sv {sim}/solver_tb.sv]
if {{[file exists {rtl}/power_tiny_adapter.sv]}} {{ add_files {rtl}/power_tiny_adapter.sv }}
set_property top solver_tb [get_filesets sim_1]
set_property xsim.simulate.runtime all [get_filesets sim_1]
launch_simulation
close_sim
exit
'''
    (sim/'run.tcl').write_text(tcl)
    run(['vivado','-mode','batch','-source',str(sim/'run.tcl')],sim,env,log)
    logs=list((sim/'project').rglob('simulate.log'))
    text='\n'.join(p.read_text(errors='replace') for p in logs)
    lines=re.findall(r'RESULT ([0-9a-fA-F]{32})',text)
    if len(lines)!=8 or 'PASS real HLS' not in text:raise ValueError('RTL measurement smoke did not finish eight transactions')
    if reference['comparison']=='exact':
        if [x.lower() for x in lines]!=[x.lower() for x in reference['outputs_hex']]:raise ValueError('RTL fixed-point outputs differ from reference')
    else:
        from power_tiny import validate_float_last
        for actual,expected in zip(lines,reference['outputs_hex']):
            words=lambda v:[(int(v,16)>>(32*i))&0xffffffff for i in range(4)]
            validate_float_last(words(actual),words(expected))
    return {'transactions':8,'passed':True,'reference_comparison':reference['comparison']}
