#!/usr/bin/env python3

import pandas as pd
import matplotlib.pyplot as plt
from io import StringIO
from aiida import load_profile
from aiida.orm import load_node


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Plot AHC from sigma_ahc_eta10.00meV.txt"
    )
    parser.add_argument(
        "pk",
        type=int,
        help="PK of the WorkChain (SiWtWorkChain) or of the FolderData node",
    )
    args = parser.parse_args()

    # AiiDA プロファイルをロード
    load_profile()
    node = load_node(args.pk)
    folder = getattr(node.outputs, "wt_retrieved", node)

    # ファイルをバイナリ取得 → 文字列に変換
    raw_bytes = folder.get_object_content("sigma_ahc_eta10.00meV.txt", mode="rb")
    raw_text = raw_bytes.decode("utf-8")

    # - usecols=[0,1]: 1列目(Energy), 2列目(σ_xy)のみ
    # - names=[...]: 列名を指定
    df = pd.read_table(
        StringIO(raw_text),
        comment="#",
        header=None,
        usecols=[0, 1],
        names=["energy_eV", "sigma_xy"],
        sep="\\s+",
    )

    # プロット
    plt.figure()
    plt.plot(df["energy_eV"], df["sigma_xy"])
    plt.xlabel("Energy (eV)")
    plt.ylabel("Anomalous Hall Conductivity (S/cm)")
    plt.title("AHC for η = 10.00 meV")
    plt.tight_layout()
    plt.grid()
    plt.savefig("ahc.pdf")


if __name__ == "__main__":
    main()
