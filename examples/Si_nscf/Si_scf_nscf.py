from aiida import load_profile
from aiida.orm import Dict, StructureData, Group, User, Str
from aiida.plugins import DataFactory
from aiida.engine import WorkChain, ToContext


class SiScfNscfWorkChain(WorkChain):
    """
    この WorkChain は、Si の結晶構造に対して Quantum ESPRESSO を用いた SCF 計算（4x4x4 kメッシュ）を実行した後、
    SCF 計算の結果を引き継いで NSCF 計算（8x8x8 kメッシュ）を行います。
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input(
            "code",
            valid_type=DataFactory("core.code.installed"),
            help="Quantum ESPRESSO のコード",
        )
        spec.input("structure", valid_type=StructureData, help="計算対象のSi結晶構造")
        spec.input(
            "pseudo_family", valid_type=Str, help="使用する擬ポテンシャルのファミリー名"
        )
        spec.outline(cls.run_scf, cls.run_nscf, cls.results)
        # エラーコードの定義
        spec.exit_code(
            300,
            "ERROR_MISSING_OUTPUT_PARAMETERS",
            message="SCF計算の出力に output_parameters が含まれていません",
        )
        spec.outputs.dynamic = True

    def run_scf(self):
        """
        SCF 計算を 4x4x4 の k メッシュで実行します。
        """
        # 入力された擬ポテンシャルファミリーから擬ポテンシャルおよび推奨カットオフを取得
        pseudo_family_label = self.inputs.pseudo_family.value
        user = User.collection.get_default()
        pseudo_family = Group.collection.get(label=pseudo_family_label, user=user)

        pseudos = pseudo_family.get_pseudos(structure=self.inputs.structure)
        recommended_cutoffs = pseudo_family.get_recommended_cutoffs(
            structure=self.inputs.structure
        )

        # SCF計算用パラメータの設定
        scf_parameters = Dict(
            {
                "CONTROL": {"calculation": "scf"},
                "SYSTEM": {
                    "ecutwfc": recommended_cutoffs[0],
                    "ecutrho": recommended_cutoffs[1],
                },
            }
        )

        # k点メッシュの設定 (4x4x4)
        KpointsData = DataFactory("core.array.kpoints")
        kpoints_scf = KpointsData()
        kpoints_scf.set_kpoints_mesh([4, 4, 4])

        inputs = {
            "code": self.inputs.code,
            "structure": self.inputs.structure,
            "parameters": scf_parameters,
            "pseudos": pseudos,
            "kpoints": kpoints_scf,
            "metadata": {
                "options": {
                    "resources": {"num_machines": 12},
                    "queue_name": "GroupE",
                    "import_sys_environment": False,
                }
            },
        }

        # SCF計算の実行
        future = self.submit(inputs["code"].get_builder(), **inputs)
        return ToContext(scf=future)

    def run_nscf(self):
        """
        SCF 計算結果を用いて NSCF 計算を 8x8x8 の k メッシュで実行します。
        """
        scf_calc = self.ctx.scf

        # SCF 計算の入力に parameters が存在するかチェック
        if not hasattr(scf_calc.inputs, "parameters"):
            self.report("parameters が見つかりません")
            return self.exit_codes.ERROR_MISSING_INPUT_PARAMETERS

        # SCF の output_parameters からパラメータを取得し、NSCF 用に書き換え
        nscf_parameters_dict = scf_calc.inputs.parameters.get_dict()
        # self.report(f"SCF input parameters: {scf_calc.inputs.parameters.get_dict()}")
        nscf_parameters_dict["CONTROL"]["calculation"] = "nscf"

        # k点メッシュの設定 (8x8x8)
        KpointsData = DataFactory("core.array.kpoints")
        kpoints_nscf = KpointsData()
        kpoints_nscf.set_kpoints_mesh([8, 8, 8])

        # 擬ポテンシャルの再取得
        pseudo_family_label = self.inputs.pseudo_family.value
        user = User.collection.get_default()
        pseudo_family = Group.collection.get(label=pseudo_family_label, user=user)
        pseudos = pseudo_family.get_pseudos(structure=self.inputs.structure)

        inputs = {
            "code": self.inputs.code,
            "structure": self.inputs.structure,
            "parameters": Dict(nscf_parameters_dict),
            "pseudos": pseudos,
            "kpoints": kpoints_nscf,
            "parent_folder": scf_calc.outputs.remote_folder,
            "metadata": {
                "options": {
                    "resources": {"num_machines": 12},
                    "queue_name": "GroupE",
                    "import_sys_environment": False,
                }
            },
        }

        # NSCF計算の実行
        future = self.submit(inputs["code"].get_builder(), **inputs)
        return ToContext(nscf=future)

    def results(self):
        """
        SCFおよびNSCF計算の結果を出力として登録します。
        """
        self.out("scf_output_parameters", self.ctx.scf.outputs.output_parameters)
        self.out("nscf_output_parameters", self.ctx.nscf.outputs.output_parameters)
