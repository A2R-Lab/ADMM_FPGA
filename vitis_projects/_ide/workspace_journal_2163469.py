# 2025-12-09T14:43:23.248142801
import vitis

client = vitis.create_client()
client.set_workspace(path="vitis_projects")

comp = client.get_component(name="forward_subst")
comp.run(operation="SYNTHESIS")

status = client.export_projects(components = ["forward_subst"], system_projects = [], include_build_dir = False, dest = "/home/agrillo/vitis_projects/forward_subst.zip")

comp.run(operation="PACKAGE")

comp.run(operation="PACKAGE")

vitis.dispose()

