"""As explicações de magias e perícias do D&D 5e, a partir do catálogo do SRD.

A linha de título é montada em português, com os campos do catálogo. O corpo é o texto do SRD,
que está em inglês como os nomes das magias.
"""

from __future__ import annotations

from oraculo.dicas import Termo, resumir
from oraculo.sistemas.dnd5e.catalogo import Magia, Pericia

_ESCOLAS = {
    "abjuration": "Abjuração",
    "conjuration": "Conjuração",
    "divination": "Adivinhação",
    "enchantment": "Encantamento",
    "evocation": "Evocação",
    "illusion": "Ilusão",
    "necromancy": "Necromancia",
    "transmutation": "Transmutação",
}
_DANOS = {
    "acid": "ácido",
    "bludgeoning": "concussão",
    "cold": "frio",
    "fire": "fogo",
    "force": "força",
    "lightning": "elétrico",
    "necrotic": "necrótico",
    "piercing": "perfurante",
    "poison": "veneno",
    "psychic": "psíquico",
    "radiant": "radiante",
    "slashing": "cortante",
    "thunder": "trovão",
}
_ATRIBUTOS = {
    "for": "Força",
    "des": "Destreza",
    "con": "Constituição",
    "int": "Inteligência",
    "sab": "Sabedoria",
    "car": "Carisma",
}
_ATAQUES = {"melee": "ataque corpo a corpo", "ranged": "ataque à distância"}


def titulo_magia(m: Magia) -> str:
    partes = [_ESCOLAS.get(m.escola, m.escola.capitalize())]
    partes.append("truque" if m.circulo == 0 else f"{m.circulo}º círculo")
    if m.dano:
        tipo = _DANOS.get(m.tipo_dano or "", m.tipo_dano or "")
        partes.append(f"{m.dano} de {tipo}" if tipo else m.dano)
    if m.cura:
        partes.append("cura")
    if m.ataque:
        partes.append(_ATAQUES.get(m.ataque, m.ataque))
    if m.resistencia:
        partes.append(f"resistência de {_ATRIBUTOS.get(m.resistencia, m.resistencia)}")
    if m.area:
        partes.append("em área")
    if m.concentracao:
        partes.append("concentração")
    if m.ritual:
        partes.append("ritual")
    return " · ".join(partes)


def termo_magia(m: Magia) -> Termo:
    return Termo(m.nome, resumir(m.descricao), titulo_magia(m))


def termo_pericia(p: Pericia) -> Termo:
    return Termo(p.nome, resumir(p.descricao), _ATRIBUTOS.get(p.atributo, p.atributo))
