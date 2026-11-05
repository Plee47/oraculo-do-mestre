"""Ficha genérica: o mesmo modelo serve para qualquer sistema de RPG.

O que muda de um sistema para outro (quais atributos existem, como se calcula a vida, o que
é válido) fica nas regras de cada sistema, em `oraculo.sistemas.<id>`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TipoFicha = Literal["pj", "npc", "criatura"]
MetodoAtributos = Literal["livre", "compra_pontos", "padrao", "rolagem"]


class Ficha(BaseModel):
    nome: str = Field(min_length=1)
    sistema: str
    tipo: TipoFicha = "pj"
    nivel: int = Field(default=1, ge=1)
    classe: str | None = None
    atributos: dict[str, int] = Field(default_factory=dict)
    metodo_atributos: MetodoAtributos = "livre"
    origem: str | None = None  # raça, ancestralidade, clã... (depende do sistema)
    pericias: list[str] = Field(default_factory=list)
    equipamento: list[str] = Field(default_factory=list)
    poderes: list[str] = Field(default_factory=list)  # magias, técnicas, habilidades
    explicacoes: list[str] = Field(default_factory=list)  # por que cada escolha foi feita
    tags: list[str] = Field(default_factory=list)
    notas: str = ""


class Problema(BaseModel):
    """Algo que as regras apontaram na ficha.

    `erro` torna a ficha inválida pelas regras; `aviso` é uma dica (a ficha é válida, mas
    provavelmente não é o que o jogador quer).
    """

    gravidade: Literal["erro", "aviso"]
    campo: str
    mensagem: str
