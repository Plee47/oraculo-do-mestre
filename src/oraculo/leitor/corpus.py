# ruff: noqa: E501  (tabela de fontes com URLs longas)
"""Corpus de treino do detector "é livro de RPG?": só obras de licença aberta.

Cada fonte declara licença e papel no treino. Os arquivos ficam em `.cache/corpus/` (local) ou
no volume `livros_abertos` (Databricks) e nunca vão para o repositório (ADR 0002).
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Fonte:
    id: str
    titulo: str
    url: str
    rpg: bool
    categoria: str  # rpg | fantasia | regras_de_jogo | literatura
    idioma: str
    licenca: str

    @property
    def arquivo(self) -> str:
        return f"{self.id}.{'pdf' if self.url.lower().endswith('.pdf') else 'txt'}"


_GUT = "https://www.gutenberg.org/cache/epub/{0}/pg{0}.txt"
_TAGMAR = "https://tagmar.com.br/downloads/Tagmar%20-%20{}.pdf"

FONTES: tuple[Fonte, ...] = (
    Fonte("srd51", "D&D SRD 5.1", "https://media.wizards.com/2023/downloads/dnd/SRD_CC_v5.1.pdf",
          True, "rpg", "en", "CC-BY-4.0"),
    Fonte("srd52", "D&D SRD 5.2", "https://media.dndbeyond.com/compendium-images/srd/5.2/SRD_CC_v5.2.pdf",
          True, "rpg", "en", "CC-BY-4.0"),
    Fonte("tagmar_regras", "Tagmar — Livro de Regras 3.0", _TAGMAR.format("Livro%20de%20Regras%203.0"),
          True, "rpg", "pt", "CC-BY-NC-SA-3.0-BR"),
    Fonte("tagmar_magias", "Tagmar — Livro de Magias 3.01", _TAGMAR.format("Livro%20de%20Magias%203.01"),
          True, "rpg", "pt", "CC-BY-NC-SA-3.0-BR"),
    Fonte("dom_casmurro", "Dom Casmurro", _GUT.format(55752), False, "literatura", "pt", "domínio público"),
    Fonte("bras_cubas", "Memórias Póstumas de Brás Cubas", _GUT.format(54829),
          False, "literatura", "pt", "domínio público"),
    Fonte("lusiadas", "Os Lusíadas", _GUT.format(3333), False, "literatura", "pt", "domínio público"),
    Fonte("well_worlds_end", "The Well at the World's End", _GUT.format(169),
          False, "fantasia", "en", "domínio público"),
    Fonte("phantastes", "Phantastes", _GUT.format(325), False, "fantasia", "en", "domínio público"),
    Fonte("gods_pegana", "The Gods of Pegana", _GUT.format(8395),
          False, "fantasia", "en", "domínio público"),
    Fonte("alice", "Alice's Adventures in Wonderland", _GUT.format(11),
          False, "fantasia", "en", "domínio público"),
    Fonte("chess", "Chess Fundamentals", _GUT.format(33870),
          False, "regras_de_jogo", "en", "domínio público"),
)  # fmt: skip


def baixar_corpus(destino: str | Path, fontes: tuple[Fonte, ...] = FONTES) -> list[str]:
    """Baixa as fontes que ainda não existem em `destino`. Retorna os ids baixados."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    baixados = []
    for f in fontes:
        alvo = destino / f.arquivo
        if alvo.exists() and alvo.stat().st_size > 0:
            continue
        req = urllib.request.Request(f.url, headers={"User-Agent": "oraculo-do-mestre/0.1"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            alvo.write_bytes(resp.read())
        baixados.append(f.id)
    return baixados


# --------------------------------------------------------------------------- páginas

_INICIO_GUTENBERG = re.compile(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.S)
_FIM_GUTENBERG = re.compile(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG", re.S)
TAMANHO_PAGINA_TXT = 2500  # caracteres por "página" quando a fonte é texto puro


def paginas_de_texto(texto: str, tamanho: int = TAMANHO_PAGINA_TXT) -> list[str]:
    """Remove o cabeçalho/rodapé do Gutenberg e corta em páginas de ~`tamanho` caracteres."""
    if m := _INICIO_GUTENBERG.search(texto):
        texto = texto[m.end() :]
    if m := _FIM_GUTENBERG.search(texto):
        texto = texto[: m.start()]
    paginas, atual = [], []
    tam = 0
    for paragrafo in re.split(r"\n\s*\n", texto):
        atual.append(paragrafo.strip())
        tam += len(paragrafo)
        if tam >= tamanho:
            paginas.append("\n\n".join(atual))
            atual, tam = [], 0
    if atual:
        paginas.append("\n\n".join(atual))
    return [p for p in paginas if p.strip()]


def paginas_de_pdf(caminho: str | Path) -> list[str]:
    from pypdf import PdfReader  # import tardio: só quem lê PDF precisa do pypdf

    return [(pagina.extract_text() or "") for pagina in PdfReader(str(caminho)).pages]


def paginas_do_arquivo(caminho: str | Path) -> list[str]:
    caminho = Path(caminho)
    if caminho.suffix.lower() == ".pdf":
        return paginas_de_pdf(caminho)
    return paginas_de_texto(caminho.read_text(encoding="utf-8", errors="replace"))
