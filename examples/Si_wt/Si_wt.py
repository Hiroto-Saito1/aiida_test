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
    RemoteData,
    SinglefileData,
    Str,
    StructureData,
    UpfData,
)
from aiida.plugins import CalculationFactory


class SiWtWorkChain(WorkChain):
    """
    Si 結晶からワニエ関数生成までを自動化する最小ワークチェイン。

    フロー
    ------
    1. SCF (pw.x)
    2. NSCF (pw.x, nosym)
    3. wannier90 -pp
    4. pw2wannier90
    5. wannier90 本計算
    6. aiida_hr.dat / aiida_tb.dat を抽出
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)

        # コード
        spec.input("pw_code", valid_type=orm.Code)
        spec.input("pw2wannier90_code", valid_type=orm.Code)
        spec.input("wannier_code", valid_type=orm.Code)

        # 構造・UPF
        spec.input("structure", valid_type=StructureData)
        spec.input_namespace("pseudos", valid_type=UpfData, dynamic=True, required=True)

        # 実行設定
        spec.input("num_machines", valid_type=Int, default=lambda: Int(1))
        spec.input(
            "max_wallclock_seconds", valid_type=Int, default=lambda: Int(3600 * 24 * 7)
        )
        spec.input("queue_name", valid_type=Str, default=lambda: Str("GroupA"))
        spec.input(
            "import_sys_environment", valid_type=Bool, default=lambda: Bool(False)
        )

        # Wannier 設定
        spec.input("num_wann", valid_type=Int)
        spec.input("kpoints_scf", valid_type=KpointsData)
        spec.input("kpoints_nscf", valid_type=KpointsData)
        spec.input("projections", valid_type=OrbitalData)

        # 手順
        spec.outline(
            cls.run_pw_scf,
            cls.run_pw_nscf,
            cls.run_w90_pp,
            cls.run_pw2wan,
            cls.run_w90,
            cls.collect_tb_files,
        )

        # 出力
        spec.output("scf_output", valid_type=Dict)
        spec.output("nscf_output", valid_type=Dict)
        spec.output("nnkp_file", valid_type=SinglefileData)
        spec.output("p2wannier_output", valid_type=Dict)
        spec.output("matrices_folder", valid_type=FolderData)
        spec.output("pw2wan_remote_folder", valid_type=RemoteData)
        spec.output("aiida_hr", valid_type=SinglefileData)
        spec.output("aiida_tb", valid_type=SinglefileData)

    # ------------------------------------------------------------------
    # utilities
    # ------------------------------------------------------------------
    def _metadata_options(self):
        """
        AiiDA `metadata.options` を生成する。

        Returns:
            dict: keys = ``resources``, ``max_wallclock_seconds``,
            ``queue_name``, ``import_sys_environment``.
        """
        return {
            "resources": {"num_machines": int(self.inputs.num_machines)},
            "max_wallclock_seconds": int(self.inputs.max_wallclock_seconds),
            "queue_name": self.inputs.queue_name.value,
            "import_sys_environment": bool(self.inputs.import_sys_environment.value),
        }

    def _extract_max_cutoffs(self):
        """
        全 UpfData から最大カットオフ (WFC/RHO) を取得する。

        Returns:
            tuple(float, float): ``(ecutwfc, ecutrho)``.
        """
        wfc = rho = 0.0
        for pseudo in self.inputs.pseudos.values():
            wfc = max(wfc, pseudo.base.attributes.get("cutoff_wfc", 20.0))
            rho = max(rho, pseudo.base.attributes.get("cutoff_rho", 100.0))
        return wfc, rho

    # ------------------------------------------------------------------
    # SCF
    # ------------------------------------------------------------------
    def run_pw_scf(self):
        """SCF 計算を起動。"""
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

        running = self.submit(builder)
        self.report(f"SCF PwCalculation<{running.pk}> 開始")
        return ToContext(pw_scf=running)

    # ------------------------------------------------------------------
    # NSCF
    # ------------------------------------------------------------------
    def run_pw_nscf(self):
        """NSCF 計算を起動。"""
        self.out("scf_output", self.ctx.pw_scf.outputs.output_parameters)
        params = self.ctx.pw_scf.inputs.parameters.get_dict()
        params["CONTROL"]["calculation"] = "nscf"
        params.setdefault("SYSTEM", {})["nosym"] = True
        params["SYSTEM"]["nbnd"] = int(self.inputs.num_wann.value) * 2

        try:
            _ = self.inputs.kpoints_nscf.get_kpoints_mesh()
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

        running = self.submit(builder)
        self.report(f"NSCF PwCalculation<{running.pk}> 開始")
        return ToContext(pw_nscf=running)

    # ------------------------------------------------------------------
    # wannier90 -pp
    # ------------------------------------------------------------------
    def run_w90_pp(self):
        """wannier90 -pp を実行し NNKP を生成。"""
        self.out("nscf_output", self.ctx.pw_nscf.outputs.output_parameters)
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

        running = self.submit(builder)
        self.report(f"Wannier90(pp)<{running.pk}> 開始")
        return ToContext(w90_pp=running)

    # ------------------------------------------------------------------
    # pw2wannier90
    # ------------------------------------------------------------------
    def run_pw2wan(self):
        """pw2wannier90 を実行し AMN/MMN を生成。"""
        self.out("nnkp_file", self.ctx.w90_pp.outputs.nnkp_file)

        builder = CalculationFactory("quantumespresso.pw2wannier90").get_builder()
        builder.code = self.inputs.pw2wannier90_code
        builder.parameters = Dict({"inputpp": {"write_amn": True, "write_mmn": True}})
        builder.parent_folder = self.ctx.pw_nscf.outputs.remote_folder
        builder.nnkp_file = self.ctx.w90_pp.outputs.nnkp_file
        builder.settings = Dict({"ADDITIONAL_RETRIEVE_LIST": ["*.amn", "*.mmn"]})
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Pw2Wannier90<{running.pk}> 開始")
        return ToContext(pw2wan=running)

    # ------------------------------------------------------------------
    # wannier90 main
    # ------------------------------------------------------------------
    def run_w90(self):
        """wannier90 本計算を実行し HR/TB を生成。"""
        self.out("matrices_folder", self.ctx.pw2wan.outputs.retrieved)
        self.out("pw2wan_remote_folder", self.ctx.pw2wan.outputs.remote_folder)
        self.out("p2wannier_output", self.ctx.pw2wan.outputs.output_parameters)

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

        running = self.submit(builder)
        self.report(f"Wannier90(main)<{running.pk}> 開始")
        return ToContext(w90=running)

    # ------------------------------------------------------------------
    # collect
    # ------------------------------------------------------------------
    def collect_tb_files(self):
        """aiida_hr.dat / aiida_tb.dat を抽出して出力ポートへ配置。"""
        if "w90" not in self.ctx or not self.ctx.w90.is_finished_ok:
            self.report("Wannier90(main) が正常終了しませんでした")
            return
        retrieved = self.ctx.w90.outputs.retrieved
        self.out(
            "aiida_hr", extract_file(retrieved=retrieved, filename=Str("aiida_hr.dat"))
        )
        self.out(
            "aiida_tb", extract_file(retrieved=retrieved, filename=Str("aiida_tb.dat"))
        )


@calcfunction
def extract_file(retrieved: FolderData, filename: Str) -> SinglefileData:
    """
    Extract a file from ``FolderData`` and return it as ``SinglefileData``.

    Args:
        retrieved: FolderData containing the target file.
        filename:  Name of the file to extract.

    Returns:
        SinglefileData: node holding the extracted file.
    """
    content = retrieved.get_object_content(filename.value, mode="rb")
    return SinglefileData(file=io.BytesIO(content), filename=filename.value)


@calcfunction
def get_explicit_kpoints(kpoints: KpointsData) -> KpointsData:
    """
    Convert a Monkhorst-Pack mesh into an explicit k-point list.

    Args:
        kpoints: KpointsData in mesh mode.

    Returns:
        KpointsData: explicit k-point list.
    """
    explicit = KpointsData()
    mesh = kpoints.get_kpoints_mesh(print_list=True)
    explicit.set_kpoints(mesh)
    return explicit
