https://eminamitani.github.io/website/2021/03/25/aiida_2/ を参照

# 最初にやること
## グローバル設定
~/.aiida ディレクトリを作り、ここにグローバル設定を保存する。
プロジェクトごとのプロファイルもここに保存される。
```
conda activate aiida
rabbitmq-server -detached
```
## プロファイルの設定 
プロジェクトごとにプロファイルを作る。
ここでは aiida_test プロファイルを作る。メールアドレスは入力必須。
デフォルトにしておく。
```
verdi profile setup core.sqlite_dos
verdi profile set-default aiida_test
verdi profile configure-rabbitmq
verdi profile list
```
brokerがエラーを吐く場合、
```
rabbitmqctl stop
rabbitmq-server -detached
```
をもう一度やる。

## デーモンの起動
```
verdi daemon start
verdi status
```

## QEの登録
qe-pw.yml に pw.x のパスを書く。
```
verdi code create core.code.installed --config qe-pw.yml
verdi code list
```
projwfc.x なども同様に、個別のymlファイルを書いて登録する。

## 擬ポテンシャルの設定
```
aiida-pseudo install sssp
aiida-pseudo list
```
Full relrativisticなポテンシャルがほしいときには、オプションで指定する。
```
aiida-pseudo install pseudo-dojo -x PBE -r FR -f upf
```

# 2回目以降
## localhostの設定
localhost.yml に計算結果の出力先ディレクトリなどをまとめておく。これだけ計算ごとにディレクトリに置いておけば良さそう。

qsubにsubmitする際の環境パスの設定などは setting.sh にまとめておく。
```
verdi computer setup --config localhost.yml
verdi computer configure core.local localhost
verdi computer list
```

# 計算の実行
```
python Si_pw.py
verdi process list -a
```

計算結果の確認
```
verdi process show <pk>
```