from aiida import load_profile
from aiida.orm import load_code, load_node, load_group, Dict
from aiida.plugins import DataFactory
from aiida.engine import submit, run
import ase.io

load_profile("aiida_test")
code = load_code("qe-pw@Si_scf")
builder = code.get_builder()

# structure
StructureData = DataFactory("core.structure")
ase_structure = ase.io.read("Si.cif")
structure = StructureData(ase=ase_structure)
builder.structure = structure

# pseudo
pseudo_family = load_group("SSSP/1.3/PBE/efficiency")
pseudos = pseudo_family.get_pseudos(structure=structure)
builder.pseudos = pseudos

# 擬ポテンシャルから推奨のカットオフを取得
recommended_cutoffs = pseudo_family.get_recommended_cutoffs(structure=structure)
ecutwfc = recommended_cutoffs[0]
ecutrho = recommended_cutoffs[1]

# parameters
parameters = {
    "CONTROL": {
        "calculation": "scf",  # self-consistent field
    },
    "SYSTEM": {
        "ecutwfc": ecutwfc,
        "ecutrho": ecutrho,
    },
}
builder.parameters = Dict(parameters)

# kpoint
KpointsData = DataFactory("core.array.kpoints")
kpoints = KpointsData()
kpoints.set_kpoints_mesh([4, 4, 4])
builder.kpoints = kpoints

# submit
builder.metadata.options.withmpi = False
builder.metadata.options.resources = {
    'num_machines': 1,
    'num_mpiprocs_per_machine': 1,
}
# builder.metadata.options.environment_variables = {"OMP_NUM_THREADS": "10"}
builder.metadata.options.custom_scheduler_commands = "\n".join([
    "#PBS -q lx",
    "#PBS -l elapstim_req=00:10:00",
    "# この行が PBS ディレクティブブロックを切ります",
])
builder.metadata.options.import_sys_environment = False  # -V オプションを削除する

calcjob_node = submit(builder)
