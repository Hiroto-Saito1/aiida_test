
# はじめに
この例では Si の scf 計算を行います。

## 注意
aiida-nqsv-pluginライブラリを自作し、`pip install -e .`でインストールした。
(https://github.com/Hiroto-Saito1/aiida_nqsv_plugin)

## computer の登録
computer.yml に出力先ディレクトリなどの計算I/Oの詳細をまとめておく。
```
verdi computer setup --config computer.yml
verdi computer configure core.local Si_scf
verdi computer list
```

### 注意
qsub にジョブを投げる際の最初の環境パスの設定などは、 setting.sh に書いておいて読み込むという形に設定した。


## QE の登録
qe-pw.yml に pw.x の実行ファイルのパスを書く。
ymlファイル内で computer の指定が必要。
```
verdi code create core.code.installed --config qe-pw.yml
verdi code list
```
projwfc.x なども同様に、個別のymlファイルを書いて登録する。

# 計算の実行
結晶構造は Si.cif から読まれる。
```
python Si_pw.py
verdi process list -a
```

計算結果の確認
```
verdi process show <pk>
```
