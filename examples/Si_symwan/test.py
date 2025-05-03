from aiida.plugins import CalculationFactory

## builder.metadata.options[...] = ... で設定可能なキー

# 1) core.shell の CalcJob クラスを得る
ShellJob = CalculationFactory("core.shell")

# 2) そのスペック全体を取得
spec = ShellJob.spec()

# 3) metadata のサブポート一覧を ports で取り出す
metadata_ports = spec.inputs["metadata"].ports

# 4) options サブポートを ports で取り出す
options_port = metadata_ports["options"].ports

# 5) 使えるキー名を全部プリント
print("Allowed metadata.options keys:")
for name in options_port:
    print(f"  - {name}")
