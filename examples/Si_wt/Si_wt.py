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
    UpfData,
    List,
)
from aiida.plugins import CalculationFactory


class SiWtWorkChain(WorkChain):
    """Si → Wannier90 → WannierTools で AHC を計算するワークチェイン。"""

    @classmethod
    def define(cls, spec):
        super().define(spec)

        # codes
        spec.input("pw_code", valid_type=orm.Code)
        spec.input("pw2wannier90_code", valid_type=orm.Code)
        spec.input("wannier_code", valid_type=orm.Code)
        spec.input("wt_code", valid_type=orm.Code)

        # structure / pseudos
        spec.input("structure", valid_type=StructureData)
        spec.input_namespace("pseudos", valid_type=UpfData, dynamic=True, required=True)

        # runtime
        spec.input("num_machines", valid_type=Int, default=lambda: Int(1))
        spec.input(
            "max_wallclock_seconds", valid_type=Int, default=lambda: Int(3600 * 24 * 7)
        )
        spec.input("queue_name", valid_type=Str, default=lambda: Str("GroupA"))
        spec.input(
            "import_sys_environment", valid_type=Bool, default=lambda: Bool(False)
        )

        # wannier settings
        spec.input("num_wann", valid_type=Int)
        spec.input("kpoints_scf", valid_type=KpointsData)
        spec.input("kpoints_nscf", valid_type=KpointsData)
        spec.input("projections", valid_type=OrbitalData)

        spec.outline(
            cls.run_pw_scf,
            cls.run_pw_nscf,
            cls.run_w90_pp,
            cls.run_pw2wan,
            cls.run_w90,
            cls.collect_tb_files,
            cls.run_wt,
        )

        spec.output("aiida_hr", valid_type=SinglefileData)
        spec.output("aiida_tb", valid_type=SinglefileData)
        spec.output("wt_retrieved", valid_type=FolderData)
        spec.output("wt_output", valid_type=Dict)

    # ---------- helpers ----------
    def _metadata_options(self):
        return {
            "resources": {"num_machines": int(self.inputs.num_machines)},
            "max_wallclock_seconds": int(self.inputs.max_wallclock_seconds),
            "queue_name": self.inputs.queue_name.value,
            "import_sys_environment": bool(self.inputs.import_sys_environment.value),
        }

    def _extract_max_cutoffs(self):
        wfc = rho = 0.0
        for pseudo in self.inputs.pseudos.values():
            wfc = max(wfc, pseudo.base.attributes.get("cutoff_wfc", 20.0))
            rho = max(rho, pseudo.base.attributes.get("cutoff_rho", 100.0))
        return wfc, rho

    # ---------- steps ----------

    def run_pw_scf(self):
        ecutwfc, ecutrho = self._extract_max_cutoffs()
        params = Dict(
            {
                "CONTROL": {"calculation": "scf"},
                "SYSTEM": {
                    "ecutwfc": ecutwfc,
                    "ecutrho": ecutrho,
                    "lspinorb": True,
                    "noncolin": True,
                },
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
        params = self.ctx.pw_scf.inputs.parameters.get_dict()
        params["CONTROL"]["calculation"] = "nscf"
        params.setdefault("SYSTEM", {})["nosym"] = True
        params["SYSTEM"]["nbnd"] = int(self.inputs.num_wann.value) * 2
        try:
            _mesh, _ = self.inputs.kpoints_nscf.get_kpoints_mesh()
            kpts = get_explicit_kpoints(self.inputs.kpoints_nscf)
        except AttributeError:
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
        mesh, _ = self.inputs.kpoints_nscf.get_kpoints_mesh()
        nw = int(self.inputs.num_wann.value)
        params = Dict(
            {"mp_grid": mesh, "num_wann": nw, "num_bands": nw * 2, "spinors": True}
        )
        builder = CalculationFactory("wannier90.wannier90").get_builder()
        builder.code = self.inputs.wannier_code
        builder.structure = self.inputs.structure
        builder.parameters = params
        builder.kpoints = self.inputs.kpoints_nscf
        builder.projections = self.inputs.projections
        builder.settings = Dict({"postproc_setup": True})
        builder.metadata.options = self._metadata_options()
        return ToContext(w90_pp=self.submit(builder))

    def run_pw2wan(self):
        builder = CalculationFactory("quantumespresso.pw2wannier90").get_builder()
        builder.code = self.inputs.pw2wannier90_code
        builder.parameters = Dict({"inputpp": {"write_amn": True, "write_mmn": True}})
        builder.parent_folder = self.ctx.pw_nscf.outputs.remote_folder
        builder.nnkp_file = self.ctx.w90_pp.outputs.nnkp_file
        builder.settings = Dict({"ADDITIONAL_RETRIEVE_LIST": ["*.amn", "*.mmn"]})
        builder.metadata.options = self._metadata_options()
        return ToContext(pw2wan=self.submit(builder))

    def run_w90(self):
        params = self.ctx.w90_pp.inputs.parameters.get_dict()
        params.update(
            {
                "write_hr": True,
                "write_tb": True,
                "dis_froz_max": self.ctx.pw_scf.outputs.output_parameters.get_dict().get(
                    "fermi_energy", 0.0
                )
                + 1.0,
            }
        )
        builder = CalculationFactory("wannier90.wannier90").get_builder()
        builder.code = self.inputs.wannier_code
        builder.structure = self.inputs.structure
        builder.parameters = Dict(params)
        builder.kpoints = self.inputs.kpoints_nscf
        builder.remote_input_folder = self.ctx.pw2wan.outputs.remote_folder
        builder.projections = self.inputs.projections
        builder.metadata.options = self._metadata_options()
        return ToContext(w90=self.submit(builder))

    def collect_tb_files(self):
        retrieved = self.ctx.w90.outputs.retrieved
        self.out("aiida_hr", extract_file(retrieved, Str("aiida_hr.dat")))
        self.out("aiida_tb", extract_file(retrieved, Str("aiida_tb.dat")))

    def run_wt(self):
        """wt.x を core.shell で実行。"""
        # SCF の Fermi (Ry → eV)
        fermi_ry = self.ctx.pw_scf.outputs.output_parameters.get_dict()["fermi_energy"]
        fermi_ev = float(fermi_ry) * 13.605698066

        # 生成物
        hr_node = self.outputs["aiida_hr"]
        tb_node = self.outputs["aiida_tb"]
        wt_in = make_wt_input(hr_node, tb_node, fermi_ev)

        # shell CalcJob ビルダー
        builder = CalculationFactory("core.shell").get_builder()
        builder.code = self.inputs.wt_code

        # リソース設定
        for key, val in self._metadata_options().items():
            setattr(builder.metadata.options, key, val)

        # ファイル転送設定（トップレベルポート）
        builder.nodes = {"hr": hr_node, "tb": tb_node, "wtin": wt_in}
        builder.filenames = {
            "hr": "aiida_hr.dat",
            "tb": "aiida_tb.dat",
            "wtin": "wt.in",
        }
        builder.arguments = List(list=[])  # 引数なし
        builder.outputs = List(list=["*"])  # 全取得

        return ToContext(wt=self.submit(builder))

    def on_terminated(self):
        super().on_terminated()
        if "wt" in self.ctx and self.ctx.wt.is_finished_ok:
            self.out("wt_retrieved", self.ctx.wt.outputs.retrieved)
            names = self.ctx.wt.outputs.retrieved.list_object_names()
            if "AHC.dat" in names:
                ahc = self.ctx.wt.outputs.retrieved.get_object_content("AHC.dat")
                self.out("wt_output", Dict({"ahc_raw": ahc}))


# ---------------- calcfunctions ----------------


@calcfunction
def extract_file(retrieved: FolderData, filename: Str) -> SinglefileData:
    data = retrieved.get_object_content(filename.value, mode="rb")
    return SinglefileData(file=io.BytesIO(data), filename=filename.value)


@calcfunction
def get_explicit_kpoints(kpoints: KpointsData) -> KpointsData:
    kd = KpointsData()
    kd.set_kpoints(kpoints.get_kpoints_mesh(print_list=True))
    return kd


@calcfunction
def make_wt_input(hr: SinglefileData, tb: SinglefileData, ef) -> SinglefileData:
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
