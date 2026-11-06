"""Mede a leitura genérica (qualquer livro) contra o gabarito do SRD 5.1.

O SRD existe como PDF (entrada) e como dados estruturados (catálogo da API, camada silver).
Então dá para ler o PDF como se fosse um sistema desconhecido e comparar o que a IA extraiu com
o que é verdade: atributos, classes, raças, criaturas (nome, PV e CA), mecânica e modificador.

As métricas vão para o MLflow (notebook 23) e decidem a estratégia de seleção de páginas.
"""

from __future__ import annotations

from oraculo.sistemas.dnd5e.catalogo import Catalogo
from oraculo.sistemas.generico.formulas import normalizar_id
from oraculo.sistemas.generico.modelo import SistemaLido

# Cada atributo do gabarito e os nomes com que ele pode aparecer (português e inglês).
ATRIBUTOS_DND = {
    "for": {"for", "forca", "str", "strength"},
    "des": {"des", "destreza", "dex", "dexterity"},
    "con": {"con", "constituicao", "constitution"},
    "int": {"int", "inteligencia", "intelligence"},
    "sab": {"sab", "sabedoria", "wis", "wisdom"},
    "car": {"car", "carisma", "cha", "charisma"},
}
CLASSES_PT = {
    "barbarian": "barbaro", "bard": "bardo", "cleric": "clerigo", "druid": "druida",
    "fighter": "guerreiro", "monk": "monge", "paladin": "paladino", "ranger": "patrulheiro",
    "rogue": "ladino", "sorcerer": "feiticeiro", "warlock": "bruxo", "wizard": "mago",
}  # fmt: skip
RACAS_PT = {
    "dwarf": "anao", "elf": "elfo", "halfling": "halfling", "human": "humano",
    "dragonborn": "draconato", "gnome": "gnomo", "half_elf": "meio_elfo", "half_orc": "meio_orc",
    "tiefling": "tiferino",
}  # fmt: skip


def _chaves(nome: str) -> set[str]:
    base = normalizar_id(nome)
    return {base, base.replace("_", "")}


def _casa(nome: str, aliases: set[str]) -> bool:
    chaves = _chaves(nome)
    return bool(chaves & aliases) or any(a in c for c in chaves for a in aliases if len(a) > 3)


def _razao(acertos: int, total: int) -> float:
    return acertos / total if total else 0.0


def avaliar_leitura(s: SistemaLido, gabarito: Catalogo) -> dict[str, float]:
    m: dict[str, float] = {}

    # Atributos: os 6 do D&D foram achados? E sobrou atributo inventado?
    achados = {
        chave
        for chave, aliases in ATRIBUTOS_DND.items()
        if any(_chaves(x) & aliases for a in s.atributos for x in (a.id, a.sigla, a.nome) if x)
    }
    m["atributos_recall"] = _razao(len(achados), len(ATRIBUTOS_DND))
    m["atributos_precisao"] = _razao(
        sum(
            1
            for a in s.atributos
            if any(
                _chaves(x) & al
                for al in ATRIBUTOS_DND.values()
                for x in (a.id, a.sigla, a.nome)
                if x
            )
        ),
        len(s.atributos),
    )

    # Classes: nome em inglês (o SRD) ou português.
    def alias_classe(c) -> set[str]:
        return _chaves(c.nome) | {CLASSES_PT.get(c.id, "")} - {""}

    classes = {c.id: alias_classe(c) for c in gabarito.classes}
    arquetipos = [a.nome for a in s.arquetipos]
    m["classes_recall"] = _razao(
        sum(1 for al in classes.values() if any(_casa(n, al) for n in arquetipos)), len(classes)
    )
    m["classes_precisao"] = _razao(
        sum(1 for n in arquetipos if any(_casa(n, al) for al in classes.values())), len(arquetipos)
    )

    # Criaturas: o nome existe no catálogo? PV e CA batem?
    por_nome = {}
    for monstro in gabarito.monstros:
        por_nome[normalizar_id(monstro.nome)] = monstro
    casadas = [(c, por_nome.get(normalizar_id(c.nome))) for c in s.criaturas]
    reais = [(c, g) for c, g in casadas if g is not None]
    m["criaturas_lidas"] = float(len(s.criaturas))
    m["criaturas_precisao"] = _razao(len(reais), len(s.criaturas))
    m["criaturas_pv_acerto"] = _razao(sum(1 for c, g in reais if c.vida == g.pv), len(reais))
    m["criaturas_ca_acerto"] = _razao(
        sum(1 for c, g in reais if c.defesa == g.ca), sum(1 for c, _ in reais if c.defesa)
    )

    # Mecânica e modificador
    m["mecanica_d20"] = 1.0 if "20" in s.mecanica.dado_base else 0.0
    modificador_certo = all(s.modificador_de(v) == (v - 10) // 2 for v in (3, 8, 10, 11, 14, 20))
    m["modificador_certo"] = 1.0 if s.modificador and modificador_certo else 0.0
    m["derivados_calculaveis"] = _razao(sum(1 for d in s.derivados if d.formula), len(s.derivados))

    partes = ("atributos_recall", "classes_recall", "classes_precisao", "criaturas_precisao",
              "criaturas_pv_acerto", "mecanica_d20", "modificador_certo")  # fmt: skip
    m["nota_geral"] = sum(m[p] for p in partes) / len(partes)
    return m
