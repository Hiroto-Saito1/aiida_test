from aiida.schedulers.plugins.pbspro import PbsproScheduler


class NoSelectPbsproScheduler(PbsproScheduler):
    """
    ・select行を消して-b 1(ノード１)を出す
    ・標準の job_directives(-r, -m, -N, -o, -e)をそのまま
    ・custom_scheduler_commands で渡した #PBS -T openmpi, #PBS -q, #PBS -l elapstim_req をその順で
    """

    def get_resource_lines(self, resources):
        """常に -b ノード数(=1) を PBS ヘッダに出力"""
        # resources['num_machines'] には builder 側で「1」を設定しておく想定
        return [f"#PBS -b {resources['num_machines']}"]

    def get_submit_script(self, **kwargs):
        """
        ヘッダーの順序を
         1) job_directives
         2) custom_scheduler_commands
         3) resource_lines (→ -b 1)
        の順で並べ替え
        """
        # 1) -r, -m, -N, -o, -e ...
        job = list(self.get_job_directives(self.job_directives))
        # 2) ユーザーが custom_scheduler_commands で渡した -T, -q, -l elapstim_req
        custom = (
            self.custom_scheduler_commands.splitlines()
            if self.custom_scheduler_commands
            else []
        )
        # 3) -b 1
        resources = list(self.get_resource_lines(self.resources))
        # 4) 本文前後の定型部分
        footer = self._get_preamble_footer_lines()

        lines = []
        lines.extend(job)
        lines.extend(custom)
        lines.extend(resources)
        lines.extend(footer)
        return "\n".join(lines)
