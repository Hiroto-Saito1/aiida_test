#!/usr/bin/env python3
from pathlib import Path

import ase.io
from aiida import load_profile
from aiida.engine import submit
from aiida.orm import StructureData, KpointsData, load_code
from aiida_pseudo.data.pseudo import UpfData
from aiida_wannier90.orbitals import generate_projections

from Si_wt import SiWtWorkChain

# AiiDA プロファイルをロード
load_profile("aiida_test")

# 構造データの読み込み
structure = StructureData(ase=ase.io.read("Si.cif"))

# コードのロード
pw_code = load_code("qe-pw@Si_symwan")
pw2wannier90_code = load_code("qe-pw2wannier90@Si_symwan")
wannier_code = load_code("w90-wannier90@Si_symwan")
wt_code = load_code("wt-wt@Si_symwan")
symwannier_code = load_code("sw-writefulldata@Si_symwan")

# UPF 疑似ポテンシャルの読み込み・保存
pseudo_si = UpfData(Path("Si.rel-pbe-n-kjpaw_psl.0.1.UPF").resolve()).store()

# k-point メッシュの設定
kpoints_scf = KpointsData()
kpoints_scf.set_kpoints_mesh([1, 1, 1])
kpoints_nscf = KpointsData()
kpoints_nscf.set_kpoints_mesh([3, 3, 3])

# Wannier 用の投影関数を生成
projections = generate_projections(
    dict(kind_name="Si", radial=1, ang_mtm_l_list=[0, 1], spin=None),
    structure=structure,
)

# WorkChain のビルダー取得
builder = SiWtWorkChain.get_builder()

# 入力ポートに値をセット
builder.pw_code = pw_code
builder.pw2wannier90_code = pw2wannier90_code
builder.wannier_code = wannier_code
builder.wt_code = wt_code
builder.symwannier_code = symwannier_code
builder.structure = structure
builder.pseudos = {"Si": pseudo_si}
builder.kpoints_scf = kpoints_scf
builder.kpoints_nscf = kpoints_nscf
builder.num_wann = 16
builder.projections = projections
builder.ppn = 12
builder.queue_name = "GroupC"

# メタデータとして label/description をセット
builder.metadata.label = "Si AHC ワークチェイン"
builder.metadata.description = (
    "シリコン結晶のAHCをWannier90→WannierToolsで計算するワークフロー"
)

# 送信実行
submit(builder)
