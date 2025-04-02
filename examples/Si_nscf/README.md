
# はじめに
この例では Si の scf 計算を行った後に、k点を増やして nscf 計算を行うという例を用いて、 workchain の概念を学びます。

## computer の登録
computer.yml に出力先ディレクトリなどの計算I/Oの詳細をまとめておく。
```
verdi computer setup --config computer.yml
verdi computer configure core.local Si_nscf
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
python run_workchain.py
verdi process list -a
```
### 注意
workchain のクラス (Si_scf_nscf.py) と、実行プログラム (run_workchain.py) は、分ける必要がある。
Si_scf_nscf.py を書き換えるたびにデーモンの再起動が必要。
```
verdi daemon restart
```

計算結果の確認
```
verdi process show <pk>
```