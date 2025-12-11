# 2025-12-09T10:43:14.017794741
import vitis

client = vitis.create_client()
client.set_workspace(path="vitis_projects")

comp = client.get_component(name="forward_subst")
comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

comp.run(operation="SYNTHESIS")

cfg = client.get_config_file(path="/home/agrillo/vitis_projects/forward_subst/hls_config.cfg")

cfg.set_values(key="syn.file", values=["forward.cpp", "forward_10.h"])

cfg.set_values(key="syn.file", values=["forward.cpp", "forward_10.h", "forward_300.h"])

cfg.set_values(key="syn.file", values=["forward.cpp", "forward_10_3.h", "forward_300.h"])

comp.run(operation="SYNTHESIS")

cfg.set_values(key="syn.file", values=["forward.cpp", "forward_10_3.h", "forward_300_20.h"])

comp.run(operation="SYNTHESIS")

comp.run(operation="C_SIMULATION")

comp.run(operation="C_SIMULATION")

comp.run(operation="C_SIMULATION")

comp.run(operation="C_SIMULATION")

comp.run(operation="C_SIMULATION")

comp.run(operation="C_SIMULATION")

comp.run(operation="C_SIMULATION")

comp.run(operation="C_SIMULATION")

vitis.dispose()

