import io
from aiida import orm
from aiida.engine import ToContext, WorkChain, calcfunction
from aiida.orm import (
    Dict,
    Group,
    User,
    SinglefileData,
    Bool,
    Str,
    KpointsData,
    Int,
    OrbitalData,
    StructureData,
    FolderData,
    RemoteData,
)
from aiida.plugins import CalculationFactory


class SiMinimalW90WorkChain(WorkChain):
    """
    Si の最小限 Wannier90 ワークチェーン。

    処理フロー:
      1. SCF 計算 (pw.x)
      2. NSCF 計算 (pw.x)
      3. Wannier90 前処理 (w90 -pp)
      4. pw2wannier90
      5. Wannier90 メイン実行
      6. aiida_hr.dat, aiida_tb.dat の抽出

    主な特徴:
      - 擬ポテンシャルの推奨カットオフを自動取得
      - num_bands = 2 * num_wann の設定
      - calcfunction 経由でファイル抽出しプロヴェナンスを保護
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("pw_code", valid_type=orm.Code, help="pw.x コード")
        spec.input(
            "pw2wannier90_code", valid_type=orm.Code, help="pw2wannier90.x コード"
        )
        spec.input("wannier_code", valid_type=orm.Code, help="wannier90.x コード")
        spec.input("structure", valid_type=StructureData, help="Si 構造データ")
        spec.input("pseudo_family", valid_type=Str, help="擬ポテンシャルファミリー")
        spec.input(
            "num_machines", valid_type=Int, default=lambda: Int(1), help="使用マシン数"
        )
        spec.input(
            "max_wallclock_seconds",
            valid_type=Int,
            default=lambda: Int(3600 * 24 * 7),
            help="最大実行時間(秒)",
        )
        spec.input(
            "queue_name",
            valid_type=Str,
            default=lambda: Str("GroupA"),
            help="ジョブキュー名",
        )
        spec.input(
            "import_sys_environment",
            valid_type=Bool,
            default=lambda: Bool(False),
            help="システム環境変数を読み込むか否か",
        )
        spec.input("num_wann", valid_type=Int, help="Wannier 関数数")
        spec.input("kpoints_scf", valid_type=KpointsData, help="SCF 用 k 点メッシュ")
        spec.input("kpoints_nscf", valid_type=KpointsData, help="NSCF/Wannier 用 k 点")
        spec.input("projections", valid_type=OrbitalData, help="射影設定")

        spec.outline(
            cls.run_pw_scf,
            cls.run_pw_nscf,
            cls.run_w90_pp,
            cls.run_pw2wan,
            cls.run_w90,
            cls.collect_tb_files,
        )

        spec.output("scf_output", valid_type=Dict)
        spec.output("nscf_output", valid_type=Dict)
        spec.output("nnkp_file", valid_type=SinglefileData)
        spec.output("p2wannier_output", valid_type=Dict)
        spec.output("matrices_folder", valid_type=FolderData)
        spec.output("pw2wan_remote_folder", valid_type=RemoteData)
        spec.output("aiida_hr", valid_type=SinglefileData, help="aiida_hr.dat")
        spec.output("aiida_tb", valid_type=SinglefileData, help="aiida_tb.dat")

    def _metadata_options(self):
        return {
            "resources": {"num_machines": int(self.inputs.num_machines)},
            "max_wallclock_seconds": int(self.inputs.max_wallclock_seconds),
            "queue_name": self.inputs.queue_name.value,
            "import_sys_environment": bool(self.inputs.import_sys_environment.value),
        }

    def run_pw_scf(self):
        """
        推奨カットオフを用いて SCF 計算を実行します。

        Returns:
            Dict: SCF 計算の結果パラメータ (scf_output)
        """
        user = User.collection.get_default()
        group = Group.collection.get(label=self.inputs.pseudo_family.value, user=user)
        pseudos = group.get_pseudos(structure=self.inputs.structure)
        ecutwfc, ecutrho = group.get_recommended_cutoffs(
            structure=self.inputs.structure
        )

        params = {
            "CONTROL": {"calculation": "scf"},
            "SYSTEM": {"ecutwfc": ecutwfc, "ecutrho": ecutrho},
        }
        builder = CalculationFactory("quantumespresso.pw").get_builder()
        builder.code = self.inputs.pw_code
        builder.structure = self.inputs.structure
        builder.pseudos = pseudos
        builder.parameters = Dict(params)
        builder.kpoints = self.inputs.kpoints_scf
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Launching SCF PwCalculation<{running.pk}>")
        return ToContext(pw_scf=running)

    def run_pw_nscf(self):
        """
        nosym を有効にした NSCF 計算を実行します。

        Returns:
            Dict: NSCF 計算の結果パラメータ (nscf_output)
        """
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
        builder.pseudos = self.ctx.pw_scf.inputs.pseudos
        builder.parameters = Dict(params)
        builder.kpoints = kpts
        builder.parent_folder = self.ctx.pw_scf.outputs.remote_folder
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Launching NSCF PwCalculation<{running.pk}>")
        return ToContext(pw_nscf=running)

    def run_w90_pp(self):
        """
        Wannier90 前処理 (-pp) を実行し .nnkp ファイルを生成します。

        Returns:
            SinglefileData: nnkp_file
        """
        self.out("nscf_output", self.ctx.pw_nscf.outputs.output_parameters)
        nw = int(self.inputs.num_wann.value)
        mesh, _ = self.inputs.kpoints_nscf.get_kpoints_mesh()
        params = {"mp_grid": mesh, "num_wann": nw, "num_bands": nw * 2}

        builder = CalculationFactory("wannier90.wannier90").get_builder()
        builder.code = self.inputs.wannier_code
        builder.structure = self.inputs.structure
        builder.parameters = Dict(params)
        builder.kpoints = self.inputs.kpoints_nscf
        builder.projections = self.inputs.projections
        builder.settings = Dict({"postproc_setup": True})
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Launching Wannier90(pp)<{running.pk}>")
        return ToContext(w90_pp=running)

    def run_pw2wan(self):
        """
        pw2wannier90 を実行し AMN/MMN を取得します。

        Returns:
            Dict: p2wannier_output
            FolderData: matrices_folder
        """
        self.out("nnkp_file", self.ctx.w90_pp.outputs.nnkp_file)
        params = {"inputpp": {"write_amn": True, "write_mmn": True}}
        settings = {"ADDITIONAL_RETRIEVE_LIST": ["*.amn", "*.mmn"]}

        builder = CalculationFactory("quantumespresso.pw2wannier90").get_builder()
        builder.code = self.inputs.pw2wannier90_code
        builder.parameters = Dict(params)
        builder.parent_folder = self.ctx.pw_nscf.outputs.remote_folder
        builder.nnkp_file = self.ctx.w90_pp.outputs.nnkp_file
        builder.settings = Dict(settings)
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Launching Pw2Wannier90<{running.pk}>")
        return ToContext(pw2wan=running)

    def run_w90(self):
        """
        Wannier90 メイン実行で write_hr, write_tb を有効化します。

        Returns:
            SinglefileData: aiida_hr
            SinglefileData: aiida_tb
        """
        self.out("matrices_folder", self.ctx.pw2wan.outputs.retrieved)
        self.out(
            "pw2wan_remote_folder",
            self.ctx.pw2wan.outputs.remote_folder,
        )
        self.out("p2wannier_output", self.ctx.pw2wan.outputs.output_parameters)

        params = self.ctx.w90_pp.inputs.parameters.get_dict()
        params.update(
            {
                "num_bands": int(self.inputs.num_wann.value) * 2,
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
        self.report(f"Launching Wannier90(main)<{running.pk}>")
        return ToContext(w90=running)

    def collect_tb_files(self):
        """
        生成された aiida_hr.dat と aiida_tb.dat を calcfunction 経由で格納します。

        Returns:
            SinglefileData: aiida_hr
            SinglefileData: aiida_tb
        """
        if "w90" not in self.ctx or not self.ctx.w90.is_finished_ok:
            self.report(
                f"Wannier90(main) calculation did not finish successfully: pk={getattr(
                    self.ctx.get('w90', None), 'pk', 'N/A'
                )}"
            )

        retrieved = self.ctx.w90.outputs.retrieved
        hr_node = extract_file(retrieved=retrieved, filename=Str("aiida_hr.dat"))
        tb_node = extract_file(retrieved=retrieved, filename=Str("aiida_tb.dat"))

        self.out("aiida_hr", hr_node)
        self.out("aiida_tb", tb_node)


@calcfunction
def extract_file(retrieved: FolderData, filename: Str) -> SinglefileData:
    """
    FolderData から指定ファイルを読み取り、SinglefileData として返します。

    Args:
        retrieved (FolderData): 出力を含むフォルダデータ
        filename (Str): 取得するファイル名

    Returns:
        SinglefileData: 指定ファイルの内容を格納したノード
    """
    content = retrieved.get_object_content(filename.value, mode="rb")
    return SinglefileData(file=io.BytesIO(content), filename=filename.value)


@calcfunction
def get_explicit_kpoints(kpoints: KpointsData) -> KpointsData:
    """
    Monkhorst-Pack メッシュを明示的な k 点リストに変換します。

    Args:
        kpoints (KpointsData): 元の k 点メッシュ

    Returns:
        KpointsData: 明示的な k 点リストを含む新規ノード
    """
    explicit = KpointsData()
    mesh = kpoints.get_kpoints_mesh(print_list=True)
    explicit.set_kpoints(mesh)
    return explicit
