from aiida import load_profile
from aiida.orm import StructureData, load_code, Str
from aiida.engine import submit
import ase.io

from Si_scf_nscf import SiScfNscfWorkChain

load_profile("aiida_test")

structure = StructureData(ase=ase.io.read("Si.cif"))
code = load_code("qe-pw@Si_nscf")

submit(
    SiScfNscfWorkChain,
    code=code,
    structure=structure,
    pseudo_family=Str("SSSP/1.3/PBE/efficiency"),
)
