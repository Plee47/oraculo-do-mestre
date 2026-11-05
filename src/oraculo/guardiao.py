"""Guardião de conteúdo: impede que livros ou dados protegidos entrem no repositório público.

Roda no CI e no pre-commit:  python -m oraculo.guardiao
Regras (ver docs/decisoes/0002-politica-de-conteudo.md):
  1. Nenhum livro (PDF, EPUB...) versionado, exceto fixtures de licença aberta.
  2. Nada dentro de pastas `privado/`.
  3. Dados publicados em `dados/publicos/<sistema>/` só para sistemas com conteudo_publico=true.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

from oraculo.nucleo.sistema import SISTEMAS_DISPONIVEIS, obter_regras

EXTENSOES_LIVRO = {".pdf", ".epub", ".mobi", ".cbz", ".cbr", ".djvu"}
PASTA_FIXTURES_ABERTAS = "tests/fixtures/abertos/"
PASTA_DADOS_PUBLICOS = "dados/publicos/"


def sistemas_publicos() -> set[str]:
    return {s for s in SISTEMAS_DISPONIVEIS if obter_regras(s).definicao.conteudo_publico}


def verificar(arquivos: list[str], publicos: set[str] | None = None) -> list[str]:
    """Devolve a lista de violações (vazia = tudo certo)."""
    publicos = sistemas_publicos() if publicos is None else publicos
    violacoes = []
    for caminho in arquivos:
        p = PurePosixPath(caminho.replace("\\", "/"))
        texto = str(p)
        if p.suffix.lower() in EXTENSOES_LIVRO and not texto.startswith(PASTA_FIXTURES_ABERTAS):
            violacoes.append(f"{texto}: arquivos de livro não podem ser versionados")
        if "privado" in p.parts:
            violacoes.append(f"{texto}: conteúdo de pasta privada")
        if texto.startswith(PASTA_DADOS_PUBLICOS):
            partes = p.parts
            sistema = partes[2] if len(partes) > 3 else None
            if sistema not in publicos:
                violacoes.append(f"{texto}: o sistema {sistema!r} não tem licença para publicação")
    return violacoes


def main() -> int:
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8")
    arquivos = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    violacoes = verificar(arquivos)
    for v in violacoes:
        print(f"✗ {v}", file=sys.stderr)
    if not violacoes:
        print(f"Guardião: {len(arquivos)} arquivos verificados, nenhum conteúdo protegido.")
    return 1 if violacoes else 0


if __name__ == "__main__":
    raise SystemExit(main())
