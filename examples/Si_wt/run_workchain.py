#!/usr/bin/env python3
from pathlib import Path
from aiida import load_profile
from aiida.engine import submit
from aiida.orm import StructureData, KpointsData, load_code
from aiida_pseudo.data.pseudo import UpfData
import ase.io
from aiida_wannier90.orbitals import generate_projections
from Si_wt import SiWtWorkChain

load_profile("aiida_test")

structure = StructureData(ase=ase.io.read("Si.cif"))

pw_code = load_code("qe-pw@Si_wt")
pw2wannier90_code = load_code("qe-pw2wannier90@Si_wt")
wannier_code = load_code("w90-wannier90@Si_wt")
wt_code = load_code("wt-wt@Si_wt")

pseudo_si = UpfData(Path("Si.rel-pbe-n-kjpaw_psl.0.1.UPF").resolve()).store()

kpoints_scf = KpointsData()
kpoints_scf.set_kpoints_mesh([2, 2, 2])
kpoints_nscf = KpointsData()
kpoints_nscf.set_kpoints_mesh([2, 2, 2])

projections = generate_projections(
    dict(kind_name="Si", radial=1, ang_mtm_l_list=[0, 1], spin=None),
    structure=structure,
)

submit(
    SiWtWorkChain,
    pw_code=pw_code,
    pw2wannier90_code=pw2wannier90_code,
    wannier_code=wannier_code,
    wt_code=wt_code,
    structure=structure,
    pseudos={"Si": pseudo_si},
    kpoints_scf=kpoints_scf,
    kpoints_nscf=kpoints_nscf,
    num_wann=16,
    projections=projections,
    ppn=12,
    queue_name="GroupE",
)
