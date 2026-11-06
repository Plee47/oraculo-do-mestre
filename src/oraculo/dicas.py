"""Termos com explicação ao passar o mouse (ou ao tocar, ou ao chegar pelo teclado).

Só HTML e CSS: o Streamlit não deixa JavaScript em `st.html`, e o estilo fica em `app/estilo.css`.
Todo texto é escapado, porque boa parte dele vem da leitura de um livro enviado pelo usuário.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from dataclasses import dataclass

_RE_FRASE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Termo:
    nome: str
    dica: str = ""  # sem explicação, o nome aparece como texto comum, sem prometer nada
    titulo: str = ""  # linha curta acima da explicação


def resumir(texto: str, limite: int = 380) -> str:
    """Encurta na última frase que cabe, ignorando tabelas e marcas de Markdown do SRD."""
    linhas = []
    for linha in (texto or "").splitlines():
        limpa = linha.replace("*", "").strip()
        if not limpa or limpa.startswith("|"):
            continue
        linhas.append(limpa.lstrip("#").strip())
    corrido = " ".join(linhas)
    if len(corrido) <= limite:
        return corrido
    saida = ""
    for frase in _RE_FRASE.split(corrido):
        if len(saida) + len(frase) + 1 > limite:
            break
        saida = f"{saida} {frase}".strip()
    return saida or corrido[:limite].rsplit(" ", 1)[0] + "…"


def _termo_html(t: Termo) -> str:
    nome = html.escape(t.nome)
    if not t.dica and not t.titulo:
        return f"<span>{nome}</span>"
    titulo = f'<span class="dica-titulo">{html.escape(t.titulo)}</span>' if t.titulo else ""
    return (
        f'<span class="termo" tabindex="0">{nome}'
        f'<span class="dica" role="tooltip">{titulo}{html.escape(t.dica)}</span></span>'
    )


def termos_html(termos: Iterable[Termo], rotulo: str = "") -> str:
    """Uma linha de termos separados por vírgula, com um rótulo opcional na frente."""
    inicio = f"<strong>{html.escape(rotulo)}:</strong> " if rotulo else ""
    return f'<div class="termos">{inicio}{", ".join(_termo_html(t) for t in termos)}</div>'
