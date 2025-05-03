import io
from aiida import orm
from aiida.engine import WorkChain, ToContext, calcfunction
from aiida.orm import (
    Bool,
    Dict,
    FolderData,
    Int,
    KpointsData,
    OrbitalData,
    SinglefileData,
    Str,
    StructureData,
    List,
)
from aiida_quantumespresso.common.hubbard import Hubbard
from aiida_quantumespresso.data.hubbard_structure import HubbardStructureData
from aiida_pseudo.data.pseudo import UpfData
from aiida.plugins import CalculationFactory


class EuCuSbWorkChain(WorkChain):
    """
    QE → symWannier → Wannier90 → WannierTools で異常ホール伝導度 (AHC) を計算するワークチェイン。
    SCF が収束しなくても NSCF に進み、NSCF では Hubbard U を適用します。
    """

    @classmethod
    def define(cls, spec):
        """
        ワークチェインの入力および出力の仕様、実行フローを定義します。

        Inputs:
          - pw_code: Quantum ESPRESSO pw.x 用の Code
          - pw2wannier90_code: pw2wannier90 用の Code
          - wannier_code: Wannier90 用の Code
          - wt_code: WannierTools 用の Code
          - symwannier_code: symWannier 用の Code
          - structure: 結晶構造 (StructureData)
          - hubbard_structure: Hubbard U 情報付き構造 (HubbardStructureData, 任意)
          - pseudos: Pseudo ポテンシャル (UpfData, dynamic)
          - num_machines, ncpus, max_wallclock_seconds, queue_name, import_sys_environment: 計算リソースと環境設定
          - num_wann: Wannier 関数数
          - kpoints_scf, kpoints_nscf: k 点情報 (KpointsData)
          - projections: 射影関数情報 (OrbitalData)

        Outline:
          1. setup_hubbard: Hubbard U 構造の用意
          2. run_pw_scf: SCF 計算
          3. run_pw_nscf: NSCF 計算 (Hubbard U 適用)
          4. run_w90_pp: Wannier90 前処理
          5. run_pw2wan: pw2wannier90 実行
          6. run_symwan: symWannier 実行
          7. run_w90: Wannier90 本処理
          8. collect_tb_files: tb.dat, hr.dat の収集
          9. run_wt: WannierTools 実行
          10. register_wt_retrieved: 出力登録

        Outputs:
          - aiida_hr: hr.dat
          - aiida_tb: tb.dat
          - wt_retrieved: WannierTools の結果フォルダ
        """
        super().define(spec)

        # --- inputs ---
        spec.input("pw_code", valid_type=orm.Code)
        spec.input("pw2wannier90_code", valid_type=orm.Code)
        spec.input("wannier_code", valid_type=orm.Code)
        spec.input("wt_code", valid_type=orm.Code)
        spec.input("symwannier_code", valid_type=orm.Code)

        spec.input("structure", valid_type=StructureData)
        spec.input("hubbard_structure", valid_type=HubbardStructureData, required=False)
        spec.input_namespace("pseudos", valid_type=UpfData, dynamic=True, required=True)

        spec.input("num_machines", valid_type=Int, default=lambda: Int(1))
        spec.input("ncpus", valid_type=Int, default=lambda: Int(1))
        spec.input(
            "max_wallclock_seconds", valid_type=Int, default=lambda: Int(3600 * 24 * 7)
        )
        spec.input("queue_name", valid_type=Str, default=lambda: Str("GroupA"))
        spec.input(
            "import_sys_environment", valid_type=Bool, default=lambda: Bool(False)
        )

        spec.input("num_wann", valid_type=Int)
        spec.input("kpoints_scf", valid_type=KpointsData)
        spec.input("kpoints_nscf", valid_type=KpointsData)
        spec.input("projections", valid_type=OrbitalData)
        spec.input(
            "angle1", valid_type=List, default=lambda: List(list=[0.0, 90.0, 90.0, 0.0])
        )
        spec.input(
            "angle2",
            valid_type=List,
            default=lambda: List(list=[0.0, 60.0, 240.0, 0.0]),
        )

        # --- outline ---
        spec.outline(
            cls.setup_hubbard,
            cls.run_pw_scf,
            cls.run_pw_nscf,
            cls.run_w90_pp,
            cls.run_pw2wan,
            cls.run_symwan,
            cls.run_w90,
            cls.collect_tb_files,
            cls.run_wt,
            cls.register_wt_retrieved,
        )

        # --- outputs ---
        spec.output("aiida_hr", valid_type=SinglefileData)
        spec.output("aiida_tb", valid_type=SinglefileData)
        spec.output("wt_retrieved", valid_type=FolderData)

    def _metadata_options(self):
        """
        各計算呼び出し時のメタデータオプション（リソース等）を生成して返します。
        """
        return {
            "resources": {
                "num_machines": int(self.inputs.num_machines),
                "num_mpiprocs_per_machine": int(self.inputs.ncpus.value),
                "num_cores_per_machine": int(self.inputs.ncpus.value),
            },
            "max_wallclock_seconds": int(self.inputs.max_wallclock_seconds),
            "queue_name": self.inputs.queue_name.value,
            "import_sys_environment": bool(self.inputs.import_sys_environment.value),
        }

    def setup_hubbard(self):
        """
        HubbardStructureData を準備または自動生成し、Hubbard U を構造に設定します。
        """
        if "hubbard_structure" in self.inputs:
            hubstr = self.inputs.hubbard_structure
        else:
            orig = self.inputs.structure
            hubstr = HubbardStructureData.from_structure(orig)
            # Eu の 4f 軌道に U = 6.7 を設定
            hubstr.initialize_onsites_hubbard(
                atom_name="Eu1",
                atom_manifold="4f",
                hubbard_type="U",
                value=6.7,
                use_kinds=True,
            )
            hubstr.initialize_onsites_hubbard(
                atom_name="Eu2",
                atom_manifold="4f",
                hubbard_type="U",
                value=6.7,
                use_kinds=True,
            )
            hubstr = hubstr.store()
        self.ctx.hubstr = hubstr

    def run_pw_scf(self):
        """
        Quantum ESPRESSO pw.x で Self-consistent Field (SCF) 計算を実行します。
        noncolin + spinorbit などの設定を含みます。
        """
        ecutwfc, ecutrho = 123, 491
        params = Dict(
            {
                "CONTROL": {"calculation": "scf"},
                "SYSTEM": {
                    "ecutwfc": ecutwfc,
                    "ecutrho": ecutrho,
                    "occupations": "smearing",
                    "smearing": "m-p",
                    "degauss": 0.01,
                    "lspinorb": True,
                    "noncolin": True,
                    "starting_magnetization": [0.0, 7.0, 7.0, 0.0],
                    "angle1": self.inputs.angle1.get_list(),
                    "angle2": self.inputs.angle2.get_list(),
                    "constrained_magnetization": "atomic",
                    "lambda": 0.5,
                },
                "ELECTRONS": {
                    "mixing_beta": 0.3,
                    # "conv_thr": 1e-8,
                    "conv_thr": 1e-3,
                    "electron_maxstep": 500,
                },
            }
        )
        builder = CalculationFactory("quantumespresso.pw").get_builder()
        builder.code = self.inputs.pw_code
        builder.structure = self.ctx.hubstr
        builder.pseudos = self.inputs.pseudos
        builder.parameters = params
        builder.kpoints = self.inputs.kpoints_scf
        builder.metadata.options = self._metadata_options()
        return ToContext(pw_scf=self.submit(builder))

    def run_pw_nscf(self):
        """
        SCF 計算の結果をもとに Non-SCF 計算を実行します。
        nosym と Hubbard U を適用、出力バンド数を増やします。
        """
        params = self.ctx.pw_scf.inputs.parameters.get_dict()
        params["CONTROL"]["calculation"] = "nscf"
        params.setdefault("SYSTEM", {})["nosym"] = True
        params["SYSTEM"]["nbnd"] = 320
        kpts = self.inputs.kpoints_nscf
        builder = CalculationFactory("quantumespresso.pw").get_builder()
        builder.code = self.inputs.pw_code
        builder.structure = self.ctx.hubstr
        builder.pseudos = self.inputs.pseudos
        builder.parameters = Dict(params)
        builder.kpoints = kpts
        builder.parent_folder = self.ctx.pw_scf.outputs.remote_folder
        builder.metadata.options = self._metadata_options()
        return ToContext(pw_nscf=self.submit(builder))

    def run_w90_pp(self):
        """
        Wannier90 の前処理 (pw2wannier90) を行い、mp_grid やバンド情報を準備します。
        exclude_bands にはリストを渡します。
        """
        mesh, _ = self.inputs.kpoints_nscf.get_kpoints_mesh()
        nw = int(self.inputs.num_wann.value)
        params = Dict(
            {
                "mp_grid": mesh,
                "num_wann": nw,
                "num_bands": 248,
                "exclude_bands": list(range(1, 73)),
                "spinors": True,
            }
        )
        builder = CalculationFactory("wannier90.wannier90").get_builder()
        builder.code = self.inputs.wannier_code
        builder.structure = self.inputs.structure
        builder.parameters = params
        builder.kpoints = get_explicit_kpoints(self.inputs.kpoints_nscf)
        builder.projections = self.inputs.projections
        builder.settings = Dict({"postproc_setup": True})
        builder.metadata.options = self._metadata_options()
        return ToContext(w90_pp=self.submit(builder))

    def run_pw2wan(self):
        """
        Quantum ESPRESSO pw2wannier90 を実行し、iamn, immn, ieig ファイルを生成します。
        """
        builder = CalculationFactory("quantumespresso.pw2wannier90").get_builder()
        builder.code = self.inputs.pw2wannier90_code
        builder.parameters = Dict(
            {"inputpp": {"write_amn": True, "write_mmn": True, "irr_bz": True}}
        )
        builder.parent_folder = self.ctx.pw_nscf.outputs.remote_folder
        builder.nnkp_file = self.ctx.w90_pp.outputs.nnkp_file
        builder.settings = Dict(
            {"ADDITIONAL_RETRIEVE_LIST": ["*.iamn", "*.immn", "*.ieig", "*.isym", "*nnkp"]}
        )
        builder.metadata.options = self._metadata_options()
        return ToContext(pw2wan=self.submit(builder))

    def run_symwan(self):
        """
        symWannier の write_full_data.py を実行し、
        pw2wannier90 で生成された *.iamn, *.immn, *.ieig, *.isym, *nnkp を
        ローカルへ回収し、再ステージングして Python スクリプトに渡します。
        """
        retrieved = self.ctx.pw2wan.outputs.retrieved
        iamn = extract_file(retrieved, Str("aiida.iamn"))
        immn = extract_file(retrieved, Str("aiida.immn"))
        ieig = extract_file(retrieved, Str("aiida.ieig"))
        isym = extract_file(retrieved, Str("aiida.isym"))
        nnkp = extract_file(retrieved, Str("aiida.nnkp"))

        builder = self.inputs.symwannier_code.get_builder()
        builder.code = self.inputs.symwannier_code

        builder.nodes = {
            "iamn": iamn,
            "immn": immn,
            "ieig": ieig,
            "isym": isym,
            "nnkp": nnkp,
        }
        builder.filenames = {
            "iamn": "aiida.iamn",
            "immn": "aiida.immn",
            "ieig": "aiida.ieig",
            "isym": "aiida.isym",
            "nnkp": "aiida.nnkp",
        }

        builder.metadata.options = self._metadata_options()
        builder.arguments = ["aiida"]
        builder.metadata.options.output_filename = "stdout"
        builder.metadata.options.append_text = "> stdout 2> stderr"
        builder.metadata.options.additional_retrieve_list = [
            "aiida.amn",
            "aiida.mmn",
            "aiida.eig",
            "aiida.nnkp",
        ]
        return ToContext(symwan=self.submit(builder))

    def run_w90(self):
        """
        Wannier90 を本実行し、hr.dat と tb.dat を出力します。
        dis_froz_max はフェルミエネルギー + 4 Ry に設定。
        """
        params = self.ctx.w90_pp.inputs.parameters.get_dict()
        params.update(
            {
                "write_hr": True,
                "write_tb": True,
                "dis_froz_max": self.ctx.pw_scf.outputs.output_parameters.get_dict().get(
                    "fermi_energy", 0.0
                )
                + 4.0,
                "num_iter": 0,
                "dis_num_iter": 200,
            }
        )
        builder = CalculationFactory("wannier90.wannier90").get_builder()
        builder.code = self.inputs.wannier_code
        builder.structure = self.inputs.structure
        builder.parameters = Dict(params)
        builder.kpoints = self.inputs.kpoints_nscf
        builder.remote_input_folder = self.ctx.symwan.outputs.remote_folder
        builder.projections = self.inputs.projections
        builder.metadata.options = self._metadata_options()
        return ToContext(w90=self.submit(builder))

    def collect_tb_files(self):
        """
        Wannier90 から返された tb.dat, hr.dat を抽出し、出力として登録します。
        """
        retrieved = self.ctx.w90.outputs.retrieved
        hr_sf = extract_file(retrieved, Str("aiida_hr.dat"))
        hr_sf.label = "aiida_hr"
        hr_sf.description = "Wannier90 generated hr.dat file"
        self.out("aiida_hr", hr_sf)
        tb_sf = extract_file(retrieved, Str("aiida_tb.dat"))
        tb_sf.label = "aiida_tb"
        tb_sf.description = "Wannier90 generated tb.dat file"
        self.out("aiida_tb", tb_sf)

    def run_wt(self):
        """
        WannierTools を実行し、AHC を計算。
        出力ファイル sigma_ahc_eta*meV.txt を追加取得します。
        """
        fermi_ry = self.ctx.pw_scf.outputs.output_parameters.get_dict()["fermi_energy"]
        fermi_ev = float(fermi_ry) * 13.605698066
        hr_node = self.outputs["aiida_hr"]
        tb_node = self.outputs["aiida_tb"]
        wt_in = make_wt_input(hr_node, tb_node, fermi_ev)
        builder = CalculationFactory("core.shell").get_builder()
        builder.code = self.inputs.wt_code
        builder.metadata.options = self._metadata_options()
        builder.nodes = {"hr": hr_node, "tb": tb_node, "wtin": wt_in}
        builder.filenames = {
            "hr": "aiida_hr.dat",
            "tb": "aiida_tb.dat",
            "wtin": "wt.in",
        }
        builder.arguments = List(list=[])
        builder.metadata.options.withmpi = True
        builder.metadata.options.additional_retrieve_list = ["sigma_ahc_eta*meV.txt"]
        return ToContext(wt=self.submit(builder))

    def register_wt_retrieved(self):
        """
        WannierTools の出力 retrieved をワークチェインの出力として登録します。
        """
        retrieved = self.ctx.wt.outputs.retrieved
        self.out("wt_retrieved", retrieved)


@calcfunction
def extract_file(retrieved: FolderData, filename: Str) -> SinglefileData:
    """
    Retrieved フォルダから指定ファイルを読み込み、SinglefileData として返すヘルパー関数。
    """
    data = retrieved.get_object_content(filename.value, mode="rb")
    return SinglefileData(file=io.BytesIO(data), filename=filename.value)


@calcfunction
def get_explicit_kpoints(kpoints: KpointsData) -> KpointsData:
    """
    KpointsData のメッシュを明示的なリストに展開し、新しい KpointsData として返す。
    """
    kd = KpointsData()
    kd.set_kpoints(kpoints.get_kpoints_mesh(print_list=True))
    return kd


@calcfunction
def make_wt_input(hr: SinglefileData, tb: SinglefileData, ef) -> SinglefileData:
    """
    WannierTools の入力ファイル wt.in を生成するヘルパー関数。

    Args:
      hr: hr.dat ファイル
      tb: tb.dat ファイル
      ef: フェルミエネルギー (eV)
    Returns:
      SinglefileData(wt.in)
    """
    ef_v = float(ef)
    template = f"""&TB_FILE
    Hrfile = '{hr.filename}'
    Package = 'QE'
    /
    &CONTROL
        AHC_calc = T
    /
    &SYSTEM
        SOC = 1
        E_FERMI = {ef_v:.6f}
    /
    &PARAMETERS
        OmegaNum = 300
        OmegaMin = -0.6
        OmegaMax = 0.6
        Nk1 = 200
        Nk2 = 200
        Nk3 = 50
    /
    LATTICE
    Angstrom
        4.5130000    0.0000000    0.0000000
        -2.2565000    3.9083730    0.0000000
        0.0000000    0.0000000   17.0920000

    ATOM_POSITIONS
    12                               ! number of atoms for projectors
    Direct
    Eu1  0.000000000000000   0.000000000000000   0.000000000000000
    Eu1  0.000000000000000   0.000000000000000   0.250000000000000
    Eu2  0.000000000000000   0.000000000000000   0.500000000000000
    Eu2  0.000000000000000   0.000000000000000   0.750000000000000
    Cu   0.333333333333333   0.666666666666667   0.125000000000000
    Cu   0.666666666666667   0.333333333333333   0.375000000000000
    Cu   0.333333333333333   0.666666666666667   0.625000000000000
    Cu   0.666666666666667   0.333333333333333   0.875000000000000
    Sb   0.666666666666667   0.333333333333333   0.125000000000000
    Sb   0.333333333333333   0.666666666666667   0.375000000000000
    Sb   0.666666666666667   0.333333333333333   0.625000000000000
    Sb   0.333333333333333   0.666666666666667   0.875000000000000

    PROJECTORS
    13  13  13  13  9  9  9  9  4  4  4  4
    Eu1  s  dz2 dxz dyz dx2-y2 dxy px  py  pz  s  px  py  pz
    Eu1  s  dz2 dxz dyz dx2-y2 dxy px  py  pz  s  px  py  pz
    Eu2  s  dz2 dxz dyz dx2-y2 dxy px  py  pz  s  px  py  pz
    Eu2  s  dz2 dxz dyz dx2-y2 dxy px  py  pz  s  px  py  pz
    Cu   s  px  py  pz  dz2 dxz dyz dx2-y2 dxy
    Cu   s  px  py  pz  dz2 dxz dyz dx2-y2 dxy
    Cu   s  px  py  pz  dz2 dxz dyz dx2-y2 dxy
    Cu   s  px  py  pz  dz2 dxz dyz dx2-y2 dxy
    Sb   s  px  py  pz
    Sb   s  px  py  pz
    Sb   s  px  py  pz
    Sb   s  px  py  pz

    SURFACE
    0  0  1
    1  0  0
    0  1  0

    KCUBE_BULK
    -0.50 -0.50 -0.50
    1.00  0.00  0.00
    0.00  1.00  0.00
    0.00  0.00  1.00
    """
    return SinglefileData(file=io.BytesIO(template.encode()), filename="wt.in")
