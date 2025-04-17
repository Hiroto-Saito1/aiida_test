from aiida.orm import Dict, StructureData, Group, User, Str
from aiida.plugins import DataFactory, CalculationFactory
from aiida.engine import WorkChain, ToContext

# Calculation plugins
PwCalculation = CalculationFactory("quantumespresso.pw")
Pw2WannierCalculation = CalculationFactory("quantumespresso.pw2wannier90")
WannierCalculation = CalculationFactory("wannier90")


class SiPw2WannierWorkChain(WorkChain):
    """
    Si構造に対してSCF → NSCF → pw2wannier90 → wannier90を順次実行するWorkChain
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input(
            "pw_code",
            valid_type=DataFactory("core.code.installed"),
            help="pw.x用のコード",
        )
        spec.input(
            "pw2wannier_code",
            valid_type=DataFactory("core.code.installed"),
            help="pw2wannier90用のコード",
        )
        spec.input(
            "wannier90_code",
            valid_type=DataFactory("core.code.installed"),
            help="wannier90用のコード",
        )
        spec.input("structure", valid_type=StructureData, help="Si結晶構造")
        spec.input(
            "pseudo_family", valid_type=Str, help="擬ポテンシャルファミリーのラベル"
        )
        spec.input(
            "wannier_parameters", valid_type=Dict, help="Wannier90用のパラメータ"
        )

        spec.outline(
            cls.run_scf,
            cls.run_nscf,
            cls.run_pw2wannier,
            cls.run_wannier90,
            cls.results,
        )

        spec.exit_code(
            300,
            "ERROR_MISSING_OUTPUT_PARAMETERS",
            message="SCF計算の出力にoutput_parametersが含まれていません",
        )
        spec.outputs.dynamic = True

    def run_scf(self):
        """
        SCF計算を4x4x4のkメッシュで実行し、結果をコンテキストに格納します。
        """
        pseudo_family_label = self.inputs.pseudo_family.value
        user = User.collection.get_default()
        pseudo_family = Group.collection.get(label=pseudo_family_label, user=user)

        pseudos = pseudo_family.get_pseudos(structure=self.inputs.structure)
        cutoffs = pseudo_family.get_recommended_cutoffs(structure=self.inputs.structure)

        parameters = Dict(
            {
                "CONTROL": {"calculation": "scf"},
                "SYSTEM": {"ecutwfc": cutoffs[0], "ecutrho": cutoffs[1]},
            }
        )

        KpointsData = DataFactory("core.array.kpoints")
        kpoints = KpointsData()
        kpoints.set_kpoints_mesh([4, 4, 4])

        builder = PwCalculation.get_builder()
        builder.code = self.inputs.pw_code
        builder.structure = self.inputs.structure
        builder.parameters = parameters
        builder.pseudos = pseudos
        builder.kpoints = kpoints
        builder.metadata.options = {
            "resources": {"num_machines": 12},
            "queue_name": "GroupE",
            "import_sys_environment": False,
        }

        future = self.submit(builder)
        return ToContext(scf=future)

    def run_nscf(self):
        """
        SCF結果を利用してNSCF計算を8x8x8のkメッシュで実行します。
        """
        scf_calc = self.ctx.scf
        if not hasattr(scf_calc.outputs, "output_parameters"):
            self.report("SCF出力にoutput_parametersがありません")
            return self.exit_codes.ERROR_MISSING_OUTPUT_PARAMETERS

        nscf_params = scf_calc.inputs.parameters.get_dict()
        nscf_params["CONTROL"]["calculation"] = "nscf"
        parameters = Dict(nscf_params)

        KpointsData = DataFactory("core.array.kpoints")
        kpoints = KpointsData()
        kpoints.set_kpoints_mesh([8, 8, 8])

        pseudo_family_label = self.inputs.pseudo_family.value
        user = User.collection.get_default()
        pseudo_family = Group.collection.get(label=pseudo_family_label, user=user)
        pseudos = pseudo_family.get_pseudos(structure=self.inputs.structure)

        builder = PwCalculation.get_builder()
        builder.code = self.inputs.pw_code
        builder.structure = self.inputs.structure
        builder.parameters = parameters
        builder.pseudos = pseudos
        builder.kpoints = kpoints
        builder.parent_folder = scf_calc.outputs.remote_folder
        builder.metadata.options = {
            "resources": {"num_machines": 12},
            "queue_name": "GroupE",
            "import_sys_environment": False,
        }

        future = self.submit(builder)
        self.ctx.pseudos = pseudos
        return ToContext(nscf=future)

    def run_pw2wannier(self):
        """
        NSCF計算の結果を使ってpw2wannier90を実行します。
        """
        nscf_calc = self.ctx.nscf

        builder = Pw2WannierCalculation.get_builder()
        builder.code = self.inputs.pw2wannier_code
        builder.parent_folder = nscf_calc.outputs.remote_folder
        builder.pseudos = self.ctx.pseudos
        builder.metadata.options = {
            "resources": {"num_machines": 12},
            "queue_name": "GroupE",
            "import_sys_environment": False,
        }

        future = self.submit(builder)
        return ToContext(pw2wannier=future)

    def run_wannier90(self):
        """
        pw2wannier90の出力を使ってWannier90を実行します。
        """
        pw2wan_calc = self.ctx.pw2wannier

        builder = WannierCalculation.get_builder()
        builder.code = self.inputs.wannier90_code
        builder.parameters = self.inputs.wannier_parameters
        builder.parent_folder = pw2wan_calc.outputs.remote_folder
        builder.metadata.options = {
            "resources": {"num_machines": 12},
            "queue_name": "GroupE",
            "import_sys_environment": False,
        }

        future = self.submit(builder)
        return ToContext(wannier=future)

    def results(self):
        """
        SCF、NSCF、pw2wannier90、Wannier90の各出力フォルダやパラメータを出力します。
        """
        self.out("scf_output_parameters", self.ctx.scf.outputs.output_parameters)
        self.out("nscf_output_parameters", self.ctx.nscf.outputs.output_parameters)
        self.out("pw2wannier_remote_folder", self.ctx.pw2wannier.outputs.remote_folder)
        self.out("wannier_remote_folder", self.ctx.wannier.outputs.remote_folder)
