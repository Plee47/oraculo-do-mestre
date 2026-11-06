"""Avaliação da extração contra um gabarito (o catálogo do SRD vindo da API).

1. Em cada página, as entradas ESPERADAS são achadas de forma determinística: uma linha com o
   nome exato de uma magia/monstro do gabarito, seguida da linha de nível/escola ou de
   tamanho/tipo. Assim medimos recall (o que o LLM deixou passar) e precisão (o que inventou).
2. Para cada entrada encontrada, cada campo é comparado com o gabarito.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from oraculo.leitor.extracao import Extracao, limpar_texto_pdf
from oraculo.sistemas.dnd5e.catalogo import Catalogo, Magia, Monstro

_DEPOIS_MAGIA = r"\d(?:st|nd|rd|th)-?\s*level\s+\w+|\w+\s+cantrip\b"
_DEPOIS_MONSTRO = r"(?:tiny|small|medium|large|huge|gargantuan)\s+\w+"

CAMPOS_MAGIA = (
    "circulo", "escola", "concentracao", "ritual", "dano", "tipo_dano", "resistencia", "area",
    "cura",
)  # fmt: skip
CAMPOS_MONSTRO = (
    "tamanho", "tipo", "cr", "ca", "pv", "atributos", "imunidades_dano", "resistencias_dano",
    "vulnerabilidades_dano", "voa", "acoes_lendarias",
)  # fmt: skip


def normalizar(nome: str) -> str:
    return re.sub(r"[^a-z0-9]", "", nome.lower())


def _padrao_titulos(nomes: list[str], depois: str) -> re.Pattern:
    """Título (qualquer espaço/quebra entre as palavras) seguido da linha de tipo/nível.

    O PDF às vezes sai com uma palavra por linha ("Acid Splash / Conjuration / cantrip"),
    então a busca ignora quebras de linha em vez de comparar linha a linha.
    """
    alternativas = sorted(
        (r"\s+".join(map(re.escape, n.split())) for n in nomes), key=len, reverse=True
    )
    return re.compile(rf"(?<![A-Za-z])({'|'.join(alternativas)})\s+(?i:{depois})")


_CACHE_PADROES: dict[int, tuple[re.Pattern, re.Pattern, dict, dict]] = {}


def esperadas_na_pagina(texto: str, gabarito: Catalogo) -> tuple[set[str], set[str]]:
    """(ids de magias, ids de monstros) cujo bloco começa nesta página."""
    chave = id(gabarito)
    if chave not in _CACHE_PADROES:
        _CACHE_PADROES[chave] = (
            _padrao_titulos([m.nome for m in gabarito.magias], _DEPOIS_MAGIA),
            _padrao_titulos([m.nome for m in gabarito.monstros], _DEPOIS_MONSTRO),
            {normalizar(m.nome): m.id for m in gabarito.magias},
            {normalizar(m.nome): m.id for m in gabarito.monstros},
        )
    re_magia, re_monstro, magias, monstros = _CACHE_PADROES[chave]
    limpo = limpar_texto_pdf(texto)
    achadas = {magias[normalizar(m.group(1))] for m in re_magia.finditer(limpo)}
    achados = {monstros[normalizar(m.group(1))] for m in re_monstro.finditer(limpo)}
    return achadas, achados


def _valor(item: Magia | Monstro, campo: str):
    v = getattr(item, campo)
    if isinstance(v, str):
        return v.lower().replace(" ", "") or None
    if isinstance(v, list):
        return tuple(sorted(v))
    if campo == "acoes_lendarias":
        return int(v)
    return v


@dataclass
class ResultadoExtracao:
    metricas: dict[str, float]
    campos: list[dict]  # uma linha por (entrada, campo): para tabela no MLflow


def avaliar_extracao(
    extracao: Extracao, esperadas_magias: set[str], esperados_monstros: set[str], gabarito: Catalogo
) -> ResultadoExtracao:
    metricas: dict[str, float] = {}
    linhas: list[dict] = []
    grupos = (
        ("magias", extracao.magias, esperadas_magias, gabarito.magias, CAMPOS_MAGIA),
        ("monstros", extracao.monstros, esperados_monstros, gabarito.monstros, CAMPOS_MONSTRO),
    )
    for tipo, extraidos, esperados, ouro, campos in grupos:
        por_nome = {normalizar(x.nome): x for x in ouro}
        casados = {}
        for x in extraidos:
            g = por_nome.get(normalizar(x.nome))
            if g is not None and g.id in esperados:
                casados[g.id] = (x, g)
        precisao = len(casados) / len(extraidos) if extraidos else 0.0
        recall = len(casados) / len(esperados) if esperados else 0.0
        metricas[f"{tipo}_precisao"] = precisao
        metricas[f"{tipo}_recall"] = recall
        metricas[f"{tipo}_f1"] = (
            2 * precisao * recall / (precisao + recall) if precisao + recall else 0.0
        )
        for campo in campos:
            acertos = [_valor(x, campo) == _valor(g, campo) for x, g in casados.values()]
            metricas[f"{tipo}_campo_{campo}"] = sum(acertos) / len(acertos) if acertos else 0.0
            for (x, g), ok in zip(casados.values(), acertos, strict=True):
                linhas.append(
                    {
                        "tipo": tipo,
                        "id": g.id,
                        "campo": campo,
                        "acertou": ok,
                        "extraido": str(_valor(x, campo)),
                        "gabarito": str(_valor(g, campo)),
                    }
                )
        if casados:
            metricas[f"{tipo}_campos_media"] = sum(
                metricas[f"{tipo}_campo_{c}"] for c in campos
            ) / len(campos)
    metricas["nota_geral"] = (
        sum(
            metricas.get(f"{t}_f1", 0) * metricas.get(f"{t}_campos_media", 0)
            for t in ("magias", "monstros")
        )
        / 2
    )
    return ResultadoExtracao(metricas, linhas)
