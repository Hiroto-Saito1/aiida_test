from aiida import load_profile

# Load the AiiDA profile
load_profile("aiida_test")

from aiida.orm import StructureData, load_code, Str, Dict, KpointsData, Group, User
from aiida_wannier90.orbitals import generate_projections
from aiida.engine import submit
import ase.io
from Si_wan import SiMinimalW90WorkChain

# 1) Si 構造の読み込み
structure = StructureData(ase=ase.io.read("Si.cif"))

# 2) コードのロード
pw_code = load_code("qe-pw@Si_wan")
pw2wannier90_code = load_code("qe-pw2wannier90@Si_wan")
wannier_code = load_code("w90-wannier90@Si_wan")

# 3) 擬ポテンシャルファミリーのラベル
pseudo_family = Str("SSSP/1.3/PBE/efficiency")

# 4) k‑points 設定
kpoints_scf = KpointsData()
kpoints_scf.set_kpoints_mesh([4, 4, 4])
kpoints_nscf = KpointsData()
kpoints_nscf.set_kpoints_mesh([8, 8, 8])

# 5) バンド構造用パス
kpoint_path = Dict(
    dict={
        "point_coords": {
            "G": [0.0, 0.0, 0.0],
            "X": [0.5, 0.0, 0.5],
            "L": [0.5, 0.5, 0.5],
        },
        "path": [("G", "X"), ("X", "L"), ("L", "G")],
    }
)

# 6) 投影関数の生成
projections = generate_projections(
    {
        "kind_name": "Si",
        "radial": 1,
        "ang_mtm_l_list": [0, 1],
        "spin": None,
    },
    structure=structure,
)

# 7) ワークチェインのサブミット
submit(
    SiMinimalW90WorkChain,
    pw_code=pw_code,
    pw2wannier90_code=pw2wannier90_code,
    wannier_code=wannier_code,
    structure=structure,
    pseudo_family=pseudo_family,
    kpoints_scf=kpoints_scf,
    kpoints_nscf=kpoints_nscf,
    num_wann=8,
    kpoint_path=kpoint_path,
    projections=projections,
    num_machines=12,
    queue_name="GroupA",
)
