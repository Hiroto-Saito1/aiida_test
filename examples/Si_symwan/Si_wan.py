################################################################################
# Copyright (c), AiiDA team and individual contributors.
# All rights reserved.
# This file is part of the AiiDA-wannier90 code adaptations.
################################################################################
"""A minimal WorkChain to run Wannier90 for Si with recommended cutoffs and dynamic queue settings."""
from aiida import orm
from aiida.engine import ToContext, WorkChain, calcfunction
from aiida.orm import Dict, Group, User, SinglefileData, Bool, Str, KpointsData, Int
from aiida.plugins import CalculationFactory


@calcfunction
def get_explicit_kpoints(kpoints: KpointsData) -> KpointsData:
    """Convert a Monkhorst–Pack mesh to an explicit k-point list."""
    explicit = KpointsData()
    explicit.set_kpoints(kpoints.get_kpoints_mesh(print_list=True))
    return explicit


class SiMinimalW90WorkChain(WorkChain):
    """Workchain to run SCF, NSCF (explicit grid), Wannier90(pp), pw2wannier90, and Wannier90 for Si with user-defined num_wann."""

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("pw_code", valid_type=orm.Code, help="pw.x code for SCF/NSCF")
        spec.input(
            "pw2wannier90_code",
            valid_type=orm.Code,
            help="pw2wannier90.x code for Pw2Wannier90Calculation",
        )
        spec.input(
            "wannier_code",
            valid_type=orm.Code,
            help="wannier90.x code for Wannier90Calculation",
        )
        spec.input(
            "structure", valid_type=orm.StructureData, help="Si crystal structure"
        )
        spec.input(
            "pseudo_family",
            valid_type=orm.Str,
            help="Label of the pseudo potential family (pseudo.family.sssp)",
        )
        spec.input(
            "num_machines",
            valid_type=orm.Int,
            required=False,
            default=lambda: orm.Int(1),
            help="Number of machines per calc",
        )
        spec.input(
            "max_wallclock_seconds",
            valid_type=orm.Int,
            required=False,
            default=lambda: orm.Int(3600),
            help="Max wallclock time (s)",
        )
        spec.input(
            "queue_name",
            valid_type=Str,
            required=False,
            default=lambda: Str("GroupA"),
            help="Queue name to submit jobs",
        )
        spec.input(
            "import_sys_environment",
            valid_type=Bool,
            required=False,
            default=lambda: Bool(False),
            help="Whether to import system environment variables",
        )
        spec.input(
            "num_wann",
            valid_type=orm.Int,
            help="Number of Wannier functions to generate",
        )
        spec.input(
            "kpoints_scf",
            valid_type=orm.KpointsData,
            help="Kpoints mesh for SCF",
        )
        spec.input(
            "kpoints_nscf",
            valid_type=orm.KpointsData,
            help="Kpoints mesh or explicit list for NSCF/Wannier",
        )
        spec.input(
            "kpoint_path",
            valid_type=orm.Dict,
            help="High-symmetry path for bands interpolation",
        )
        spec.input(
            "projections",
            valid_type=orm.OrbitalData,
            help="Wannierisation projections",
        )

        spec.outline(
            cls.run_pw_scf,
            cls.run_pw_nscf,
            cls.run_w90_pp,
            cls.run_pw2wan,
            cls.run_w90,
        )

        spec.output("scf_output", valid_type=orm.Dict)
        spec.output("nscf_output", valid_type=orm.Dict)
        spec.output("nnkp_file", valid_type=orm.SinglefileData)
        spec.output("p2wannier_output", valid_type=orm.Dict)
        spec.output("matrices_folder", valid_type=orm.FolderData)
        spec.output("pw2wan_remote_folder", valid_type=orm.RemoteData)

    def _metadata_options(self):
        return {
            "resources": {"num_machines": int(self.inputs.num_machines)},
            "max_wallclock_seconds": int(self.inputs.max_wallclock_seconds),
            "queue_name": self.inputs.queue_name.value,
            "import_sys_environment": bool(self.inputs.import_sys_environment.value),
        }

    def run_pw_scf(self):
        """Run SCF using recommended cutoffs from pseudo.family.sssp"""
        user = User.collection.get_default()
        pseudo_group = Group.collection.get(
            label=self.inputs.pseudo_family.value, user=user
        )
        pseudos = pseudo_group.get_pseudos(structure=self.inputs.structure)
        cutoffs = pseudo_group.get_recommended_cutoffs(structure=self.inputs.structure)
        ecutwfc, ecutrho = cutoffs

        scf_params = {
            "CONTROL": {"calculation": "scf"},
            "SYSTEM": {"ecutwfc": ecutwfc, "ecutrho": ecutrho},
        }
        builder = CalculationFactory("quantumespresso.pw").get_builder()
        builder.code = self.inputs.pw_code
        builder.structure = self.inputs.structure
        builder.pseudos = pseudos
        builder.parameters = orm.Dict(scf_params)
        builder.kpoints = self.inputs.kpoints_scf
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Launching PwCalculation<{running.pk}> (SCF)")
        return ToContext(pw_scf=running)

    def run_pw_nscf(self):
        """Run NSCF with explicit k-grid and symmetry off (nosym)."""
        self.out("scf_output", self.ctx.pw_scf.outputs.output_parameters)
        nscf_params = self.ctx.pw_scf.inputs["parameters"].get_dict()
        nscf_params["CONTROL"]["calculation"] = "nscf"
        nscf_params.setdefault("SYSTEM", {})["nosym"] = True
        # set bands at least twice num_wann
        nscf_params["SYSTEM"]["nbnd"] = int(self.inputs.num_wann.value) * 2

        try:
            _ = self.inputs.kpoints_nscf.get_kpoints_mesh()
            kpoints_explicit = get_explicit_kpoints(self.inputs.kpoints_nscf)
        except AttributeError:
            kpoints_explicit = self.inputs.kpoints_nscf

        builder = CalculationFactory("quantumespresso.pw").get_builder()
        builder.code = self.inputs.pw_code
        builder.structure = self.inputs.structure
        builder.pseudos = self.ctx.pw_scf.inputs["pseudos"]
        builder.parameters = orm.Dict(nscf_params)
        builder.kpoints = kpoints_explicit
        builder.parent_folder = self.ctx.pw_scf.outputs.remote_folder
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Launching PwCalculation<{running.pk}> (NSCF explicit nosym)")
        return ToContext(pw_nscf=running)

    def run_w90_pp(self):
        """Generate .nnkp via Wannier90 -pp"""
        self.out("nscf_output", self.ctx.pw_nscf.outputs.output_parameters)
        num_wann = int(self.inputs.num_wann.value)
        pp_params = {
            "mp_grid": self.inputs.kpoints_nscf.get_kpoints_mesh()[0],
            "num_wann": num_wann,
            "num_bands": num_wann * 2,
        }
        builder = CalculationFactory("wannier90.wannier90").get_builder()
        builder.code = self.inputs.wannier_code
        builder.structure = self.inputs.structure
        builder.parameters = orm.Dict(pp_params)
        builder.kpoints = self.inputs.kpoints_nscf
        builder.kpoint_path = self.inputs.kpoint_path
        builder.projections = self.inputs.projections
        builder.settings = orm.Dict({"postproc_setup": True})
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Launching Wannier90<{running.pk}> (pp)")
        return ToContext(w90_pp=running)

    def run_pw2wan(self):
        """Run pw2wannier90 using generated nnkp"""
        self.out("nnkp_file", self.ctx.w90_pp.outputs.nnkp_file)
        p2w_params = {"inputpp": {"write_amn": True, "write_mmn": True}}
        settings = {"ADDITIONAL_RETRIEVE_LIST": ["*.amn", "*.mmn"]}
        builder = CalculationFactory("quantumespresso.pw2wannier90").get_builder()
        builder.code = self.inputs.pw2wannier90_code
        builder.parameters = orm.Dict(p2w_params)
        builder.parent_folder = self.ctx.pw_nscf.outputs.remote_folder
        builder.nnkp_file = self.ctx.w90_pp.outputs.nnkp_file
        builder.settings = orm.Dict(settings)
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Launching Pw2Wannier90<{running.pk}>")
        return ToContext(pw2wan=running)

    def run_w90(self):
        """Run final Wannier90 main run"""
        self.out("matrices_folder", self.ctx.pw2wan.outputs.retrieved)
        self.out("pw2wan_remote_folder", self.ctx.pw2wan.outputs.remote_folder)
        self.out("p2wannier_output", self.ctx.pw2wan.outputs.output_parameters)
        main_params = self.ctx.w90_pp.inputs["parameters"].get_dict()
        # override bands
        main_params["num_bands"] = int(self.inputs.num_wann.value) * 2
        builder = CalculationFactory("wannier90.wannier90").get_builder()
        builder.code = self.inputs.wannier_code
        builder.structure = self.inputs.structure
        builder.parameters = orm.Dict(main_params)
        builder.kpoints = self.inputs.kpoints_nscf
        builder.kpoint_path = self.inputs.kpoint_path
        builder.remote_input_folder = self.ctx.pw2wan.outputs.remote_folder
        builder.projections = self.inputs.projections
        builder.metadata.options = self._metadata_options()

        running = self.submit(builder)
        self.report(f"Launching Wannier90<{running.pk}> (main)")
        return ToContext(w90=running)
