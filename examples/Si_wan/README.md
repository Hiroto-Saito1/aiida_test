
# はじめに
この例では 
* Si の scf 計算
* k点を増やして nscf 計算
* pw2wannier 計算
* wannier90 計算

という workchain を作ります。

## computer の登録
computer.yml に出力先ディレクトリなどの計算I/Oの詳細をまとめておく。
```
verdi computer setup --config computer.yml
verdi computer configure core.local Si_wan
verdi computer list
```

### 注意
qsub にジョブを投げる際の最初の環境パスの設定などは、 setting.sh に書いておいて読み込むという形に設定した。


## code の登録
qe-pw.yml に pw.x の実行ファイルのパスを書く。
ymlファイル内で computer の指定が必要。
```
verdi code create core.code.installed --config qe-pw.yml
verdi code create core.code.installed --config qe-pw2wannier90.yml
verdi code create core.code.installed --config w90-wannier90.yml
verdi code list
```

# 計算の実行
結晶構造は Si.cif から読まれる。
```
export PYTHONPATH="/home2/hirotosaito/github_projects/aiida_test/examples/Si_wan:$PYTHONPATH"
verdi daemon restart
python run_workchain.py
verdi process list -a
```
### 注意
workchain のクラス (Si_wan.py) と、実行プログラム (run_workchain.py) は、分ける必要がある。
Si_wan.py を書き換えるたびにデーモンの再起動が必要。
```
verdi daemon restart
```

計算結果の確認
```
verdi process show <pk>
verdi node graph generate <pk>
```