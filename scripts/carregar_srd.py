"""Plano B da ingestão: baixa o SRD localmente e envia para o volume `livros_abertos`.

Útil quando o compute do Databricks não alcança a API (o Free Edition restringe a internet).
Uso: python scripts/carregar_srd.py [-t dev|prod]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from deploy import databricks, variaveis_do_bundle  # noqa: E402

from oraculo.sistemas.dnd5e.srd import baixar_srd  # noqa: E402

CACHE = RAIZ / ".cache" / "srd51"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-t", "--target", default="dev")
    args = parser.parse_args()

    print(f"{baixar_srd(CACHE)} arquivos novos baixados em {CACHE}")
    v = variaveis_do_bundle(args.target)
    destino = f"dbfs:/Volumes/{v['catalogo']}/{v['schema']}/livros_abertos/dnd5e_srd51_api"
    databricks("fs", "cp", "-r", str(CACHE), destino, "--overwrite")
    print(f"Enviado para {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
