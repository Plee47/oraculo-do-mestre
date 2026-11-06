"""Catálogo normalizado do SRD 5.1: o formato que sai do Databricks e entra no site.

Os modelos aqui são independentes da API de origem. Se amanhã o catálogo vier do PDF do SRD
(Fase 3), o gerador e o site continuam iguais.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

# Abreviações da API (inglês) -> ids de atributo do projeto (português)
ATRIBUTO_SRD = {"str": "for", "dex": "des", "con": "con", "int": "int", "wis": "sab", "cha": "car"}


class Raca(BaseModel):
    id: str
    nome: str
    deslocamento: int
    tamanho: str
    bonus: dict[str, int] = Field(default_factory=dict)
    bonus_escolha: int = 0  # quantos +1 o jogador escolhe (ex.: meio-elfo escolhe 2)
    bonus_escolha_opcoes: list[str] = Field(default_factory=list)


class NivelClasse(BaseModel):
    nivel: int
    proficiencia: int
    asi_acumulados: int  # melhorias de atributo recebidas até este nível
    truques: int = 0
    magias_conhecidas: int | None = None  # None = conjurador que prepara magias
    espacos: list[int] = Field(default_factory=lambda: [0] * 9)  # espaços por círculo 1..9

    @property
    def circulo_maximo(self) -> int:
        return max((i + 1 for i, n in enumerate(self.espacos) if n > 0), default=0)


class ClasseSRD(BaseModel):
    id: str
    nome: str
    dado_vida: int
    resistencias: list[str]
    armaduras: list[str]  # leve, media, pesada, escudo
    armas: list[str]  # simples, marcial e/ou ids de armas específicas
    pericias_escolha: int
    pericias_opcoes: list[str]
    conjuracao: str | None = None
    niveis: list[NivelClasse] = Field(default_factory=list)

    def nivel(self, n: int) -> NivelClasse:
        return next(x for x in self.niveis if x.nivel == n)


class Magia(BaseModel):
    id: str
    nome: str
    circulo: int  # 0 = truque
    escola: str
    classes: list[str]
    concentracao: bool = False
    ritual: bool = False
    ataque: str | None = None  # melee / ranged
    resistencia: str | None = None  # atributo do teste de resistência
    tipo_dano: str | None = None
    dano: str | None = None  # dano no círculo base (ou no nível 1, para truques)
    cura: bool = False
    area: bool = False
    descricao: str = ""  # texto do SRD

    @property
    def funcao(self) -> str:
        if self.cura:
            return "cura"
        if self.dano:
            return "dano"
        if self.resistencia:
            return "controle"
        return "utilidade"


class Arma(BaseModel):
    id: str
    nome: str
    categoria: str  # simples / marcial
    alcance: str  # corpo_a_corpo / distancia
    dano: str
    tipo_dano: str
    propriedades: list[str] = Field(default_factory=list)


class Armadura(BaseModel):
    id: str
    nome: str
    categoria: str  # leve / media / pesada / escudo
    ca_base: int
    soma_des: bool
    des_maxima: int | None = None
    for_minima: int = 0
    desvantagem_furtividade: bool = False


class Pericia(BaseModel):
    id: str
    nome: str
    atributo: str
    descricao: str = ""  # texto do SRD


class AtaqueMonstro(BaseModel):
    nome: str
    bonus_ataque: int | None = None  # jogada de ataque...
    cd: int | None = None  # ...ou teste de resistência
    resistencia: str | None = None  # atributo do teste
    dano_medio: float = 0.0
    tipos_dano: list[str] = Field(default_factory=list)
    area: bool = False
    limitado: bool = False  # recarga ou x/dia


class Monstro(BaseModel):
    id: str
    nome: str
    tipo: str
    tamanho: str
    cr: float
    xp: int
    ca: int
    pv: int
    atributos: dict[str, int]
    resistencias_bonus: dict[str, int]  # bônus em cada teste de resistência
    imunidades_dano: list[str] = Field(default_factory=list)
    resistencias_dano: list[str] = Field(default_factory=list)
    vulnerabilidades_dano: list[str] = Field(default_factory=list)
    fisico_nao_magico: str | None = None  # "imune" ou "resiste" a físico não mágico
    imunidades_condicao: list[str] = Field(default_factory=list)
    voa: bool = False
    acoes_lendarias: int = 0
    resistencia_lendaria: bool = False
    ataques: list[AtaqueMonstro] = Field(default_factory=list)
    rotina: list[str] = Field(default_factory=list)  # ataques de um turno normal

    def ataque(self, nome: str) -> AtaqueMonstro:
        return next(a for a in self.ataques if a.nome == nome)


class Catalogo(BaseModel):
    sistema: str = "dnd5e"
    fonte: str = "SRD 5.1 (CC-BY-4.0) via dnd5eapi.co"
    racas: list[Raca]
    classes: list[ClasseSRD]
    magias: list[Magia]
    armas: list[Arma]
    armaduras: list[Armadura]
    pericias: list[Pericia]
    monstros: list[Monstro] = Field(default_factory=list)

    def monstro(self, id_: str) -> Monstro:
        return next(m for m in self.monstros if m.id == id_)

    def raca(self, id_: str) -> Raca:
        return next(r for r in self.racas if r.id == id_)

    def classe(self, id_: str) -> ClasseSRD:
        return next(c for c in self.classes if c.id == id_)

    def pericia(self, id_: str) -> Pericia:
        return next(p for p in self.pericias if p.id == id_)

    def magias_da_classe(self, classe_id: str, circulo_max: int) -> list[Magia]:
        return [m for m in self.magias if classe_id in m.classes and m.circulo <= circulo_max]

    def resumo(self) -> dict[str, int]:
        campos = ("racas", "classes", "magias", "armas", "armaduras", "pericias", "monstros")
        return {campo: len(getattr(self, campo)) for campo in campos}

    def salvar(self, caminho: str | Path) -> None:
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        # newline fixo: o arquivo sai idêntico no Windows e no Databricks (Linux)
        texto = self.model_dump_json(indent=1) + "\n"
        Path(caminho).write_text(texto, encoding="utf-8", newline="\n")

    @classmethod
    def carregar(cls, caminho: str | Path) -> Catalogo:
        return cls.model_validate(json.loads(Path(caminho).read_text(encoding="utf-8")))
