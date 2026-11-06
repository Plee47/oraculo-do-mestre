"""Contrato que todo sistema de RPG implementa e o registro de sistemas disponíveis.

Dados estáticos (atributos, classes, tabelas) ficam num `sistema.yaml`; a lógica (fórmulas,
validação) fica em Python. Adicionar um sistema novo = uma pasta nova em `oraculo/sistemas/`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from importlib import import_module, resources

import yaml
from pydantic import BaseModel

from oraculo.nucleo.ficha import Ficha, Problema

SISTEMAS_DISPONIVEIS = ("dnd5e", "fm")


class Atributo(BaseModel):
    id: str
    nome: str
    abrev: str
    minimo: int
    maximo: int


class Classe(BaseModel):
    id: str
    nome: str
    srd: str | None = None  # id da classe na fonte de dados do sistema
    papel: str | None = None
    dado_vida: int | None = None
    atributos_principais: list[str] = []
    resistencias: list[str] = []
    resistencias_escolha: int | None = None  # None = todas as da lista; n = escolhe n delas
    conjuracao: str | None = None
    prioridade: list[str] = []
    pv_primeiro_nivel: int | None = None  # quando não é o próprio dado de vida
    energia_por_nivel: int | None = None  # PE, mana, estamina...
    energia_soma_atributo: bool = False  # soma o modificador do atributo-chave uma vez


class DefinicaoSistema(BaseModel):
    id: str
    nome: str
    versao: str
    fonte: str
    licenca: str
    conteudo_publico: bool  # pode ir para o repositório/site público?
    nivel_maximo: int
    atributos: list[Atributo]
    classes: list[Classe]
    extras: dict = {}

    def classe(self, classe_id: str | None) -> Classe | None:
        return next((c for c in self.classes if c.id == classe_id), None)


class RegrasSistema(ABC):
    """Interface que cada sistema implementa."""

    definicao: DefinicaoSistema

    @abstractmethod
    def derivados(self, ficha: Ficha) -> dict[str, int]:
        """Valores calculados a partir da ficha (modificadores, PV, CA, CD...)."""

    @abstractmethod
    def validar(self, ficha: Ficha) -> list[Problema]:
        """Erros de regra e avisos/dicas sobre a ficha."""

    def ficha_valida(self, ficha: Ficha) -> bool:
        return not any(p.gravidade == "erro" for p in self.validar(ficha))


def carregar_definicao(pacote: str) -> DefinicaoSistema:
    texto = resources.files(pacote).joinpath("sistema.yaml").read_text(encoding="utf-8")
    return DefinicaoSistema.model_validate(yaml.safe_load(texto))


def obter_regras(sistema_id: str) -> RegrasSistema:
    if sistema_id not in SISTEMAS_DISPONIVEIS:
        raise KeyError(
            f"sistema desconhecido: {sistema_id!r} (disponíveis: {SISTEMAS_DISPONIVEIS})"
        )
    modulo = import_module(f"oraculo.sistemas.{sistema_id}")
    return modulo.Regras()
