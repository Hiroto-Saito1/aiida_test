# はじめに
このディレクトリは、 aiida と QE を用いて Wannier 化を行うチュートリアルです。

## python 環境設定
conda 24.9.2, python 3.12.8 を使用。

```
conda env create -f environment.yml
conda activate aiida
```

## aiida 環境設定
~/.aiida ディレクトリを作り、ここにグローバル設定を保存する。

プロジェクトごとにプロファイルを作る。
ここでは aiida_test プロファイルを作る。メールアドレスは入力必須。
デフォルトにしておく。
```
rabbitmq-server -detached
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

## 擬ポテンシャルの設定
```
aiida-pseudo install sssp
aiida-pseudo list
```
Full relrativisticなポテンシャルがほしいときには、オプションで指定する。
```
aiida-pseudo install pseudo-dojo -x PBE -r FR -f upf
```


## 参考文献
https://eminamitani.github.io/website/2021/03/25/aiida_2/
