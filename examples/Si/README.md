# 最初にやること
## グローバル設定
~/.aiida ディレクトリを作り、ここにグローバル設定を保存する。
プロジェクトごとのプロファイルもここに保存される。
```
conda activate aiida
rabbitmq-server -detached
```

# 2回目以降
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

## localhostの設定
localhost.yml にまとめておく。パスの設定などは setting.sh にまとめておく。
```
verdi computer setup --config localhost.yml
verdi computer configure core.local localhost
verdi computer list
```

## QEの登録
qe-code.yml に実行ファイルのパスをまとめておく。
```
verdi code setup --condig qe-code.yaml
```

