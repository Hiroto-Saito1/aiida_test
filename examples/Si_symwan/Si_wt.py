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
from aiida_pseudo.data.pseudo import UpfData
from aiida.plugins import CalculationFactory


class SiWtWorkChain(WorkChain):
    """
    Si → Wannier90 → WannierTools で AHC を計算するワークチェイン。
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)

        spec.input("pw_code", valid_type=orm.Code)
        spec.input("pw2wannier90_code", valid_type=orm.Code)
        spec.input("wannier_code", valid_type=orm.Code)
        spec.input("wt_code", valid_type=orm.Code)
        spec.input("symwannier_code", valid_type=orm.Code)

        spec.input("structure", valid_type=StructureData)
        spec.input_namespace("pseudos", valid_type=UpfData, dynamic=True, required=True)

        spec.input("num_machines", valid_type=Int, default=lambda: Int(1))
        spec.input("ppn", valid_type=Int, default=lambda: Int(1))
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

        spec.outline(
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

        spec.output("aiida_hr", valid_type=SinglefileData)
        spec.output("aiida_tb", valid_type=SinglefileData)
        spec.output("wt_retrieved", valid_type=FolderData)

    def _metadata_options(self):
        """
        ワークチェインの実行メタデータを設定する。

        Returns:
            dict: metadata options.
        """
        return {
            "resources": {
                "num_machines": int(self.inputs.num_machines),
                "num_mpiprocs_per_machine": int(self.inputs.ppn.value),
                "num_cores_per_machine": int(self.inputs.ppn.value),
            },
            "max_wallclock_seconds": int(self.inputs.max_wallclock_seconds),
            "queue_name": self.inputs.queue_name.value,
            "import_sys_environment": bool(self.inputs.import_sys_environment.value),
        }

    def run_pw_scf(self):
        """
        Quantum ESPRESSO pw の SCF 計算を実行する。

        Returns:
            ToContext: ctx.pw_scf に計算結果を格納する。
        """
        ecutwfc, ecutrho = 38, 151
        params = Dict(
            {
                "CONTROL": {"calculation": "scf"},
                "SYSTEM": {
                    "ecutwfc": ecutwfc,
                    "ecutrho": ecutrho,
                    "lspinorb": True,
                    "noncolin": True,
                },
                "ELECTRONS": {"conv_thr": 1e-3, "electron_maxstep": 200},
            }
        )
        builder = CalculationFactory("quantumespresso.pw").get_builder()
        builder.code = self.inputs.pw_code
        builder.structure = self.inputs.structure
        builder.pseudos = self.inputs.pseudos
        builder.parameters = params
        builder.kpoints = self.inputs.kpoints_scf
        builder.metadata.options = self._metadata_options()
        return ToContext(pw_scf=self.submit(builder))

    def run_pw_nscf(self):
        """
        Quantum ESPRESSO pw の NSCF 計算を実行する。

        Returns:
            ToContext: ctx.pw_nscf に計算結果を格納する。
        """
        params = self.ctx.pw_scf.inputs.parameters.get_dict()
        params["CONTROL"]["calculation"] = "nscf"
        params.setdefault("SYSTEM", {})["nosym"] = True
        params["SYSTEM"]["nbnd"] = int(self.inputs.num_wann.value) * 2
        kpts = self.inputs.kpoints_nscf
        builder = CalculationFactory("quantumespresso.pw").get_builder()
        builder.code = self.inputs.pw_code
        builder.structure = self.inputs.structure
        builder.pseudos = self.inputs.pseudos
        builder.parameters = Dict(params)
        builder.kpoints = kpts
        builder.parent_folder = self.ctx.pw_scf.outputs.remote_folder
        builder.metadata.options = self._metadata_options()
        return ToContext(pw_nscf=self.submit(builder))

    def run_w90_pp(self):
        """
        Wannier90 の前処理 (pp) を実行する。

        Returns:
            ToContext: ctx.w90_pp に計算結果を格納する。
        """
        mesh, _ = self.inputs.kpoints_nscf.get_kpoints_mesh()
        nw = int(self.inputs.num_wann.value)
        params = Dict(
            {"mp_grid": mesh, "num_wann": nw, "num_bands": nw * 2, "spinors": True}
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
        pw2wannier90 を実行し、必要なファイルを取得する。

        Returns:
            ToContext: ctx.pw2wan に計算結果を格納する。
        """
        builder = CalculationFactory("quantumespresso.pw2wannier90").get_builder()
        builder.code = self.inputs.pw2wannier90_code
        builder.parameters = Dict(
            {"inputpp": {"write_amn": True, "write_mmn": True, "irr_bz": True}}
        )
        builder.parent_folder = self.ctx.pw_nscf.outputs.remote_folder
        builder.nnkp_file = self.ctx.w90_pp.outputs.nnkp_file
        builder.settings = Dict(
            {
                "ADDITIONAL_RETRIEVE_LIST": [
                    "*.iamn",
                    "*.immn",
                    "*.ieig",
                    "*.isym",
                    "*nnkp",
                ]
            }
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
        Wannier90 本計算を実行し hr と tb ファイルを生成する。

        Returns:
            ToContext: ctx.w90 に計算結果を格納する。
        """
        params = self.ctx.w90_pp.inputs.parameters.get_dict()
        params.update(
            {
                "write_hr": True,
                "write_tb": True,
                "dis_froz_max": self.ctx.pw_scf.outputs.output_parameters.get_dict().get(
                    "fermi_energy", 0.0
                )
                + 1.0,
                "num_iter": 0,
                "dis_num_iter": 0,
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
        hr.dat と tb.dat を取り出して出力ポートに登録する。
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
        wt.x を実行して AHC を計算する。

        Returns:
            ToContext: ctx.wt に ShellJob を格納する。
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
        ShellJob の retrieved FolderData を出力ポートに登録する。
        """
        retrieved = self.ctx.wt.outputs.retrieved
        self.out("wt_retrieved", retrieved)


@calcfunction
def get_explicit_kpoints(kpoints: KpointsData) -> KpointsData:
    """
    KpointsData のメッシュを明示的なリストに展開し、新しい KpointsData として返す。
    """
    kd = KpointsData()
    kd.set_kpoints(kpoints.get_kpoints_mesh(print_list=True))
    return kd


@calcfunction
def extract_file(retrieved: FolderData, filename: Str) -> SinglefileData:
    """
    Retrieved から指定ファイルを抽出して SinglefileData に変換する。

    Args:
        retrieved (FolderData): source folder.
        filename (Str): name of file to extract.

    Returns:
        SinglefileData: extracted file data.
    """
    data = retrieved.get_object_content(filename.value, mode="rb")
    return SinglefileData(file=io.BytesIO(data), filename=filename.value)


@calcfunction
def make_wt_input(hr: SinglefileData, tb: SinglefileData, ef) -> SinglefileData:
    """
    WannierTools の入力ファイルをテンプレートから作成する。

    Args:
        hr (SinglefileData): hr.dat file.
        tb (SinglefileData): tb.dat file.
        ef (float): Fermi energy.

    Returns:
        SinglefileData: generated wt.in file.
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
        OmegaNum = 100
        OmegaMin = -0.6
        OmegaMax = 0.6
        Nk1 = 10
        Nk2 = 10
        Nk3 = 10
    /
    LATTICE
    Angstrom
        3.8669746500  0.0000000000  0.0000000000
        1.9334873250  3.3488982827  0.0000000000
        1.9334873250  1.1162994276  3.1573715803

    ATOM_POSITIONS
    2
    Cartisen
    Si 5.8004619750 3.3488982827 2.3680286852
    Si 3.8669746500 2.2325988551 1.5786857901

    PROJECTORS
    4 4
    Si   s  px  py  pz
    Si   s  px  py  pz

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
