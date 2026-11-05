"""Conversão catálogo <-> linhas de tabela (camada silver do Databricks).

Cada linha tem colunas planas (para SQL e dashboards) e `dados_json`, com o modelo completo,
que a camada gold usa para reconstruir o catálogo sem perder nada.
"""

from __future__ import annotations

import json

from oraculo.sistemas.dnd5e.catalogo import (
    Arma,
    Armadura,
    Catalogo,
    ClasseSRD,
    Magia,
    Monstro,
    Pericia,
    Raca,
)

TABELAS = ("racas", "classes", "magias", "armas", "armaduras", "pericias", "monstros")
_MODELOS = {
    "racas": Raca,
    "classes": ClasseSRD,
    "magias": Magia,
    "armas": Arma,
    "armaduras": Armadura,
    "pericias": Pericia,
    "monstros": Monstro,
}


def _planas(tabela: str, item) -> dict:
    if tabela == "racas":
        return {
            "nome": item.nome,
            "deslocamento": item.deslocamento,
            "tamanho": item.tamanho,
            "bonus_fixo_total": sum(item.bonus.values()),
            "bonus_escolha": item.bonus_escolha,
        }
    if tabela == "classes":
        return {
            "nome": item.nome,
            "dado_vida": item.dado_vida,
            "conjuracao": item.conjuracao or "",
            "armaduras": ",".join(item.armaduras),
            "pericias_escolha": item.pericias_escolha,
            "circulo_maximo_nivel_20": item.nivel(20).circulo_maximo if item.niveis else 0,
        }
    if tabela == "magias":
        return {
            "nome": item.nome,
            "circulo": item.circulo,
            "escola": item.escola,
            "funcao": item.funcao,
            "concentracao": item.concentracao,
            "area": item.area,
            "tipo_dano": item.tipo_dano or "",
            "classes": ",".join(item.classes),
        }
    if tabela == "armas":
        return {
            "nome": item.nome,
            "categoria": item.categoria,
            "alcance": item.alcance,
            "dano": item.dano,
            "tipo_dano": item.tipo_dano,
        }
    if tabela == "armaduras":
        return {
            "nome": item.nome,
            "categoria": item.categoria,
            "ca_base": item.ca_base,
            "soma_des": item.soma_des,
            "for_minima": item.for_minima,
        }
    if tabela == "monstros":
        return {
            "nome": item.nome,
            "tipo": item.tipo,
            "cr": item.cr,
            "xp": item.xp,
            "ca": item.ca,
            "pv": item.pv,
            "voa": item.voa,
            "fisico_nao_magico": item.fisico_nao_magico or "",
            "imunidades_dano": ",".join(item.imunidades_dano),
            "resistencias_dano": ",".join(item.resistencias_dano),
            "acoes_lendarias": item.acoes_lendarias,
            "ataques_em_area": sum(a.area for a in item.ataques),
        }
    return {"nome": item.nome, "atributo": item.atributo}


def catalogo_para_linhas(cat: Catalogo) -> dict[str, list[dict]]:
    return {
        tabela: [
            {"id": item.id, **_planas(tabela, item), "dados_json": item.model_dump_json()}
            for item in getattr(cat, tabela)
        ]
        for tabela in TABELAS
    }


def linhas_para_catalogo(linhas: dict[str, list[str]]) -> Catalogo:
    """`linhas` = {tabela: [dados_json, ...]}."""
    campos = {
        tabela: sorted(
            (_MODELOS[tabela].model_validate(json.loads(j)) for j in linhas.get(tabela, [])),
            key=lambda x: x.id,
        )
        for tabela in TABELAS
    }
    return Catalogo(**campos)


def validar_catalogo(cat: Catalogo) -> list[str]:
    """Expectativas de qualidade do SRD 5.1. Lista vazia = tudo certo."""
    problemas = []
    minimos = {
        "racas": 9,
        "classes": 12,
        "magias": 300,
        "armas": 30,
        "armaduras": 12,
        "pericias": 18,
        "monstros": 300,
    }
    for tabela, minimo in minimos.items():
        n = len(getattr(cat, tabela))
        if n < minimo:
            problemas.append(f"{tabela}: {n} itens (esperado >= {minimo})")
    for c in cat.classes:
        if [n.nivel for n in c.niveis] != list(range(1, 21)):
            problemas.append(f"classe {c.id}: tabela de níveis incompleta")
    ids_classes = {c.id for c in cat.classes}
    for m in cat.magias:
        if not set(m.classes) <= ids_classes:
            problemas.append(f"magia {m.id}: classe desconhecida {set(m.classes) - ids_classes}")
    for mo in cat.monstros:
        if mo.pv <= 0 or mo.ca <= 0:
            problemas.append(f"monstro {mo.id}: PV ou CA inválidos")
        if any(n not in {a.nome for a in mo.ataques} for n in mo.rotina):
            problemas.append(f"monstro {mo.id}: rotina cita ataque inexistente")
    return problemas
