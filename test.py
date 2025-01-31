from aiida import load_profile
from aiida.orm import load_code, load_node, load_group, Dict
from aiida.plugins import DataFactory
from aiida.engine import submit, run

load_profile("aiida_test")
code = load_code("pw@localhost")
builder = code.get_builder()

structure = load_node(2)
builder.structure = structure

pseudo_family = load_group("SSSP/1.3/PBE/efficiency")
pseudos = pseudo_family.get_pseudos(structure=structure)
builder.pseudos = pseudos

parameters = {
    "CONTROL": {
        "calculation": "scf",  # self-consistent field
    },
    "SYSTEM": {
        "ecutwfc": 30.0,  # wave function cutoff in Ry
        "ecutrho": 240.0,  # density cutoff in Ry
    },
}
builder.parameters = Dict(parameters)

KpointsData = DataFactory("core.array.kpoints")
kpoints = KpointsData()
kpoints.set_kpoints_mesh([4, 4, 4])
builder.kpoints = kpoints

builder.metadata.options.resources = {"num_machines": 1}
builder.metadata.options.queue_name = "GroupC"
builder.metadata.options.import_sys_environment = False  # -V オプションを削除する
builder.metadata.options.scheduler_stdout = ""
builder.metadata.options.scheduler_stderr = ""

calcjob_node = submit(builder)