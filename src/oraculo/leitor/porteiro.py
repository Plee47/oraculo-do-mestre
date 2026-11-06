"""Porteiro do leitor: decide se um arquivo vira fichas e por qual caminho.

* Não é RPG (romance, manual): barrado, sem gastar LLM.
* RPG de um sistema com regras prontas no Oráculo (D&D 5e, Feiticeiros & Maldições): usa as
  regras prontas (mais precisas e testadas).
* Qualquer outro RPG (Call of Cthulhu, Vampiro, um sistema 2d8 brasileiro...): o LLM lê o
  livro e monta a especificação do sistema (oraculo.sistemas.generico).
* Na dúvida (nota baixa, mas com sinais de RPG), segue para a leitura e o LLM confirma.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from oraculo.leitor.detector import ModeloDetector, Veredito, avaliar_documento

# Sistemas com regras prontas no Oráculo (o resto é lido pelo LLM).
SISTEMAS_SUPORTADOS = {"dnd5e": "D&D 5e", "fm": "Feiticeiros & Maldições"}
# Sistemas com extrator de entradas pelo LLM no Databricks (magias e monstros). O livro base
# de F&M não tem listas prontas (feitiços são criados pelo jogador).
SISTEMAS_COM_EXTRATOR = frozenset({"dnd5e"})
# Abaixo do limiar do detector, mas com sinais de RPG: o LLM confirma na leitura.
NOTA_MINIMA_DUVIDA = 0.25

Caminho = Literal["pronto", "leitura", "barrado"]


@dataclass(frozen=True)
class Decisao:
    aceito: bool
    motivo: str
    veredito: Veredito
    caminho: Caminho = "barrado"
    incerto: bool = False  # aceito na dúvida: a leitura com LLM confirma se é RPG


def decidir(modelo: ModeloDetector, paginas: list[str]) -> Decisao:
    v = avaliar_documento(modelo, paginas)
    if v.paginas_analisadas == 0:
        return Decisao(False, "sem texto extraível (PDF escaneado?)", v)
    if v.e_rpg and v.sistema in SISTEMAS_SUPORTADOS:
        nome = SISTEMAS_SUPORTADOS[v.sistema]
        return Decisao(True, f"livro de {nome} (nota {v.nota:.0%})", v, "pronto")
    if v.e_rpg:
        return Decisao(
            True, f"livro de RPG de um sistema próprio (nota {v.nota:.0%})", v, "leitura"
        )
    if v.nota >= NOTA_MINIMA_DUVIDA:
        return Decisao(
            True,
            f"talvez seja um livro de RPG (nota {v.nota:.0%}); a leitura com IA confirma",
            v,
            "leitura",
            incerto=True,
        )
    return Decisao(False, f"não parece um livro de RPG (nota {v.nota:.0%})", v)
