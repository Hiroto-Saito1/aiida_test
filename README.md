# はじめに
このディレクトリは、 aiida と QE を用いて Wannier 化を行うチュートリアルです。

## python 環境設定
conda 24.9.2, python 3.12.8 を使用。

```
conda env remove -n aiida
conda create -n aiida python=3.12
conda activate aiida

pip install aiida-core
conda install -c conda-forge aiida-core.services
rabbitmq-server -detached
verdi profile setup core.sqlite_dos
verdi profile configure-rabbitmq
```
あるいは
```
conda env remove -n aiida
conda env create -f environment.yml
conda activate aiida
```

## aiida 環境設定
~/.aiida ディレクトリを作り、ここにグローバル設定やSQLデータベースを保存する。

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

### 注意
簡単のためにSQLiteを用いるが、複数の計算を同時に行う場合にはPostgreSQLを用いる必要がある。
PostgreSQLを用いる方法についてはまた別の機会に。

## デーモンの起動
```
verdi daemon start
verdi status
```

### 注意
以下のようなWarningが出る。
```
Warning: RabbitMQ v3.12.13 is not supported and will cause unexpected problems!
Warning: It can cause long-running workflows to crash and jobs to be submitted multiple times.
Warning: See https://github.com/aiidateam/aiida-core/wiki/RabbitMQ-version-to-use for details.
```
これはデフォルトではデーモン(RabitMQ)が30分以上のジョブを監視してくれないことを意味する。
監視時間を無限にする方法はまた別の機会に。


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
