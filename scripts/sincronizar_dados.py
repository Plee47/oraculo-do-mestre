"""Traz os dados públicos exportados pelo Databricks para `dados/publicos/` (usado pelo site).

Uso: python scripts/sincronizar_dados.py [-t dev|prod]
Depois, revise com `git diff --stat dados/` e faça o commit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from deploy import databricks, variaveis_do_bundle  # noqa: E402

from oraculo.leitor.detector import FEATURES, ModeloDetector  # noqa: E402
from oraculo.sistemas.dnd5e.catalogo import Catalogo  # noqa: E402
from oraculo.sistemas.dnd5e.tabelas import validar_catalogo  # noqa: E402

PUBLICOS = RAIZ / "dados" / "publicos"


def _validar_detector(caminho: Path) -> list[str]:
    modelo = ModeloDetector.carregar(caminho)
    if set(modelo.coeficientes) != set(FEATURES):
        return ["detector: as features do modelo não batem com as do código"]
    return []


def _validar_avaliacao(caminho: Path) -> list[str]:
    import json

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not dados.get("modelos") or "modelo_escolhido" not in dados:
        return ["avaliação do leitor: arquivo incompleto"]
    return []


# arquivo no volume `exportacao` -> (destino no repositório, validação)
ARQUIVOS = {
    "dnd5e/catalogo.json": (
        PUBLICOS / "dnd5e" / "catalogo.json",
        lambda c: validar_catalogo(Catalogo.carregar(c)),
    ),
    "modelos/detector_rpg.json": (PUBLICOS / "modelos" / "detector_rpg.json", _validar_detector),
    "avaliacoes/leitor_srd51.json": (
        PUBLICOS / "avaliacoes" / "leitor_srd51.json",
        lambda c: _validar_avaliacao(c),
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-t", "--target", default="dev")
    args = parser.parse_args()

    v = variaveis_do_bundle(args.target)
    origem = f"dbfs:/Volumes/{v['catalogo']}/{v['schema']}/exportacao"
    for relativo, (destino, validar) in ARQUIVOS.items():
        destino.parent.mkdir(parents=True, exist_ok=True)
        databricks("fs", "cp", f"{origem}/{relativo}", str(destino), "--overwrite")
        problemas = validar(destino)
        if problemas:
            print("\n".join(problemas), file=sys.stderr)
            return 1
        print(f"OK {destino.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
