"""Porteiro do leitor: só livros de RPG de sistemas suportados seguem para o LLM.

Evita gerar fichas a partir de qualquer arquivo (um romance, um manual) e poupa a cota de
LLM: o detector roda em milissegundos, sem custo.
"""

from __future__ import annotations

from dataclasses import dataclass

from oraculo.leitor.detector import ModeloDetector, Veredito, avaliar_documento

# Sistemas que o leitor sabe extrair. Feiticeiros & Maldições entra na Fase 4.
SISTEMAS_SUPORTADOS = {"dnd5e": "D&D 5e"}


@dataclass(frozen=True)
class Decisao:
    aceito: bool
    motivo: str
    veredito: Veredito


def decidir(modelo: ModeloDetector, paginas: list[str]) -> Decisao:
    v = avaliar_documento(modelo, paginas)
    if v.paginas_analisadas == 0:
        return Decisao(False, "sem texto extraível (PDF escaneado?)", v)
    if not v.e_rpg:
        return Decisao(False, f"não parece um livro de RPG (nota {v.nota:.0%})", v)
    if v.sistema not in SISTEMAS_SUPORTADOS:
        sistema = v.sistema or "não identificado"
        return Decisao(False, f"livro de RPG, mas de um sistema não suportado ({sistema})", v)
    return Decisao(True, f"livro de {SISTEMAS_SUPORTADOS[v.sistema]} (nota {v.nota:.0%})", v)
