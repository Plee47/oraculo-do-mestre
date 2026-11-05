"""Plano B: baixa o corpus do detector localmente e envia para o volume `livros_abertos`.

Uso: python scripts/carregar_corpus.py [-t dev|prod]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from deploy import databricks, variaveis_do_bundle  # noqa: E402

from oraculo.leitor.corpus import baixar_corpus  # noqa: E402

CACHE = RAIZ / ".cache" / "corpus"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-t", "--target", default="dev")
    args = parser.parse_args()

    print("baixados:", baixar_corpus(CACHE))
    v = variaveis_do_bundle(args.target)
    destino = f"dbfs:/Volumes/{v['catalogo']}/{v['schema']}/livros_abertos/corpus_detector"
    databricks("fs", "cp", "-r", str(CACHE), destino, "--overwrite")
    print(f"Enviado para {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
