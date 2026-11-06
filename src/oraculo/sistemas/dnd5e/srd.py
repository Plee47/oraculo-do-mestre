"""Ingestão do SRD 5.1 pela API pública dnd5eapi.co: download e parsing para o catálogo.

As funções de parsing recebem o JSON cru e devolvem os modelos de `catalogo.py`. São
puras (sem rede nem Spark), então rodam iguais nos testes, no Databricks e localmente.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from oraculo.sistemas.dnd5e.catalogo import (
    ATRIBUTO_SRD,
    Arma,
    Armadura,
    AtaqueMonstro,
    Catalogo,
    ClasseSRD,
    Magia,
    Monstro,
    NivelClasse,
    Pericia,
    Raca,
)

API_HOST = "https://www.dnd5eapi.co"
API = f"{API_HOST}/api/2014"
RECURSOS = ("races", "classes", "spells", "equipment", "skills", "monsters")
TIPOS_DANO = (
    "acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing",
    "poison", "psychic", "radiant", "slashing", "thunder",
)  # fmt: skip
_RE_DADO = re.compile(r"^\s*(\d+)d(\d+)\s*(?:([+-])\s*(\d+))?\s*$")
_RE_AREA = re.compile(r"each creature|cone|line that is|radius|-foot cube|-foot sphere", re.I)
_HEADERS = {"User-Agent": "oraculo-do-mestre/0.1", "Accept": "application/json"}

_ARMADURA = {"Light": "leve", "Medium": "media", "Heavy": "pesada", "Shield": "escudo"}
_PROF_ARMADURA = {
    "light-armor": ["leve"],
    "medium-armor": ["media"],
    "heavy-armor": ["pesada"],
    "all-armor": ["leve", "media", "pesada"],
    "shields": ["escudo"],
}
_PROF_ARMAS = {"simple-weapons": "simples", "martial-weapons": "marcial"}


# --------------------------------------------------------------------------- download


def _get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def baixar_srd(destino: str | Path, max_workers: int = 8) -> int:
    """Salva um JSON por item em `destino/<recurso>/<id>.json` (e os níveis das classes em
    `destino/class_levels/<classe>.json`). Pula o que já existe. Retorna quantos baixou."""
    destino = Path(destino)
    tarefas: list[tuple[str, Path]] = []
    for recurso in RECURSOS:
        pasta = destino / recurso
        pasta.mkdir(parents=True, exist_ok=True)
        for item in _get_json(f"{API}/{recurso}")["results"]:
            tarefas.append((API_HOST + item["url"], pasta / f"{item['index']}.json"))
            if recurso == "classes":
                niveis = destino / "class_levels" / f"{item['index']}.json"
                tarefas.append((f"{API_HOST}{item['url']}/levels", niveis))

    pendentes = [(url, arq) for url, arq in tarefas if not arq.exists()]

    def baixar(tarefa: tuple[str, Path]) -> None:
        url, arquivo = tarefa
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(_get_json(url), ensure_ascii=False), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(baixar, pendentes))
    return len(pendentes)


# --------------------------------------------------------------------------- parsing


def _atrib(ref: dict) -> str:
    return ATRIBUTO_SRD[ref["index"]]


def parse_raca(raw: dict) -> Raca:
    opcoes = raw.get("ability_bonus_options") or {}
    return Raca(
        id=raw["index"],
        nome=raw["name"],
        deslocamento=int(raw.get("speed", 30)),
        tamanho=raw.get("size", "Medium"),
        bonus={_atrib(b["ability_score"]): int(b["bonus"]) for b in raw.get("ability_bonuses", [])},
        bonus_escolha=int(opcoes.get("choose", 0)),
        bonus_escolha_opcoes=[
            _atrib(o["ability_score"]) for o in (opcoes.get("from") or {}).get("options", [])
        ],
    )


def parse_niveis(raw_niveis: list[dict]) -> list[NivelClasse]:
    niveis = []
    for n in sorted(raw_niveis, key=lambda x: x["level"]):
        if n.get("subclass"):  # níveis de subclasse vêm misturados na lista
            continue
        sc = n.get("spellcasting") or {}
        niveis.append(
            NivelClasse(
                nivel=n["level"],
                proficiencia=n["prof_bonus"],
                asi_acumulados=n.get("ability_score_bonuses", 0),
                truques=sc.get("cantrips_known", 0),
                magias_conhecidas=sc.get("spells_known"),
                espacos=[sc.get(f"spell_slots_level_{i}", 0) for i in range(1, 10)],
            )
        )
    return niveis


def parse_classe(raw: dict, raw_niveis: list[dict] | None = None) -> ClasseSRD:
    profs = [p["index"] for p in raw.get("proficiencies", [])]
    armaduras = sorted({a for p in profs for a in _PROF_ARMADURA.get(p, [])})
    armas = [_PROF_ARMAS.get(p, p) for p in profs if not p.startswith("saving-throw")]
    armas = [a for a in armas if a not in _PROF_ARMADURA]

    pericias_escolha, pericias_opcoes = 0, []
    for escolha in raw.get("proficiency_choices", []):
        opcoes = [o.get("item", {}).get("index", "") for o in escolha["from"].get("options", [])]
        skills = [o.removeprefix("skill-") for o in opcoes if o.startswith("skill-")]
        if skills:
            pericias_escolha, pericias_opcoes = int(escolha["choose"]), skills
            break

    conj = (raw.get("spellcasting") or {}).get("spellcasting_ability")
    return ClasseSRD(
        id=raw["index"],
        nome=raw["name"],
        dado_vida=int(raw["hit_die"]),
        resistencias=[_atrib(s) for s in raw.get("saving_throws", [])],
        armaduras=armaduras,
        armas=armas,
        pericias_escolha=pericias_escolha,
        pericias_opcoes=pericias_opcoes,
        conjuracao=_atrib(conj) if conj else None,
        niveis=parse_niveis(raw_niveis or []),
    )


def _primeiro_dano(dano: dict) -> str | None:
    for chave in ("damage_at_slot_level", "damage_at_character_level"):
        tabela = dano.get(chave) or {}
        if tabela:
            return tabela[min(tabela, key=int)]
    return None


def parse_magia(raw: dict) -> Magia:
    danos = raw.get("damage") or []
    dano = (
        danos[0] if isinstance(danos, list) and danos else danos if isinstance(danos, dict) else {}
    )
    dc = raw.get("dc") or {}
    return Magia(
        id=raw["index"],
        nome=raw["name"],
        circulo=int(raw.get("level", 0)),
        escola=(raw.get("school") or {}).get("index", ""),
        classes=[c["index"] for c in raw.get("classes", [])],
        concentracao=bool(raw.get("concentration")),
        ritual=bool(raw.get("ritual")),
        ataque=raw.get("attack_type"),
        resistencia=_atrib(dc["dc_type"]) if dc.get("dc_type") else None,
        tipo_dano=(dano.get("damage_type") or {}).get("index") if dano else None,
        dano=_primeiro_dano(dano) if dano else None,
        cura=bool(raw.get("heal_at_slot_level")),
        area=bool(raw.get("area_of_effect")),
        descricao="\n".join(raw.get("desc") or []),
    )


def parse_equipamento(raw: dict) -> Arma | Armadura | None:
    categoria = (raw.get("equipment_category") or {}).get("index")
    if categoria == "weapon" and raw.get("damage", {}).get("damage_dice"):
        return Arma(
            id=raw["index"],
            nome=raw["name"],
            categoria="marcial" if raw.get("weapon_category") == "Martial" else "simples",
            alcance="distancia" if raw.get("weapon_range") == "Ranged" else "corpo_a_corpo",
            dano=raw["damage"]["damage_dice"],
            tipo_dano=raw["damage"].get("damage_type", {}).get("index", ""),
            propriedades=[p["index"] for p in raw.get("properties", [])],
        )
    if categoria == "armor" and raw.get("armor_category") in _ARMADURA:
        ca = raw.get("armor_class") or {}
        return Armadura(
            id=raw["index"],
            nome=raw["name"],
            categoria=_ARMADURA[raw["armor_category"]],
            ca_base=int(ca.get("base", 0)),
            soma_des=bool(ca.get("dex_bonus")),
            des_maxima=ca.get("max_bonus"),
            for_minima=int(raw.get("str_minimum") or 0),
            desvantagem_furtividade=bool(raw.get("stealth_disadvantage")),
        )
    return None


def parse_pericia(raw: dict) -> Pericia:
    return Pericia(
        id=raw["index"],
        nome=raw["name"],
        atributo=_atrib(raw["ability_score"]),
        descricao="\n".join(raw.get("desc") or []),
    )


def media_dado(expr: str) -> float:
    """Média de "2d6+3" (0 se não for uma expressão de dado)."""
    m = _RE_DADO.match(expr or "")
    if not m:
        return float(expr) if (expr or "").strip().isdigit() else 0.0
    qtd, faces, sinal, bonus = m.groups()
    return int(qtd) * (int(faces) + 1) / 2 + (int(bonus or 0) * (-1 if sinal == "-" else 1))


def parse_defesas(textos: list[str]) -> tuple[list[str], bool]:
    """Separa tipos de dano simples do caso "físico de armas não mágicas"."""
    tipos, fisico_nao_magico = [], False
    for texto in textos:
        if "nonmagical" in texto:
            fisico_nao_magico = True
        elif texto in TIPOS_DANO:
            tipos.append(texto)
    return tipos, fisico_nao_magico


def _parse_ataque_monstro(acao: dict) -> AtaqueMonstro | None:
    danos = [d for d in acao.get("damage") or [] if isinstance(d, dict) and d.get("damage_dice")]
    dc = acao.get("dc") or {}
    bonus = acao.get("attack_bonus")
    if bonus is None and not dc:
        return None
    uso = (acao.get("usage") or {}).get("type", "")
    return AtaqueMonstro(
        nome=acao.get("name", "?"),
        bonus_ataque=int(bonus) if bonus is not None else None,
        cd=int(dc["dc_value"]) if bonus is None and dc.get("dc_value") else None,
        resistencia=_atrib(dc["dc_type"]) if bonus is None and dc.get("dc_type") else None,
        dano_medio=sum(media_dado(d["damage_dice"]) for d in danos),
        tipos_dano=sorted({d.get("damage_type", {}).get("index", "") for d in danos} - {""}),
        area=bonus is None and bool(_RE_AREA.search(acao.get("desc", ""))),
        limitado=uso in ("recharge on roll", "per day", "recharge after rest"),
    )


def _rotina_monstro(multi: dict | None, ataques: list[AtaqueMonstro]) -> list[str]:
    """Ataques de um turno normal: o multiataque de maior dano, ou o melhor ataque único."""
    normais = {a.nome.lower(): a for a in ataques if not a.limitado and a.dano_medio > 0}
    combinacoes: list[list[tuple[str, object]]] = []
    if multi:
        if multi.get("actions"):
            combinacoes.append(
                [(s.get("action_name", ""), s.get("count", 1)) for s in multi["actions"]]
            )
        for op in ((multi.get("action_options") or {}).get("from") or {}).get("options", []):
            itens = op.get("items", []) if op.get("option_type") == "multiple" else [op]
            combinacoes.append([(i.get("action_name", ""), i.get("count", 1)) for i in itens])

    def expandir(comb):
        rotina = []
        for nome, qtd in comb:
            ataque = normais.get(str(nome).lower())
            if ataque:
                n = int(qtd) if str(qtd).isdigit() else (5 if "head" in str(qtd).lower() else 1)
                rotina += [ataque.nome] * n
        return rotina

    rotinas = [expandir(c) for c in combinacoes]
    melhor = max(rotinas, key=lambda r: sum(normais[n.lower()].dano_medio for n in r), default=[])
    if not melhor and normais:
        melhor = [max(normais.values(), key=lambda a: a.dano_medio).nome]
    return melhor


def parse_monstro(raw: dict) -> Monstro:
    atributos = {
        ATRIBUTO_SRD[k]: int(raw.get(nome, 10))
        for k, nome in (
            ("str", "strength"), ("dex", "dexterity"), ("con", "constitution"),
            ("int", "intelligence"), ("wis", "wisdom"), ("cha", "charisma"),
        )
    }  # fmt: skip
    resist = {a: (v - 10) // 2 for a, v in atributos.items()}
    for p in raw.get("proficiencies", []):
        idx = p.get("proficiency", {}).get("index", "")
        if idx.startswith("saving-throw-"):
            resist[ATRIBUTO_SRD[idx.removeprefix("saving-throw-")]] = int(p["value"])

    imunes, imune_fisico = parse_defesas(raw.get("damage_immunities", []))
    resistentes, resiste_fisico = parse_defesas(raw.get("damage_resistances", []))
    vulneraveis, _ = parse_defesas(raw.get("damage_vulnerabilities", []))
    ataques, multi = [], None
    for acao in raw.get("actions", []):
        if acao.get("name", "").lower().startswith("multiattack"):
            multi = acao
        elif (a := _parse_ataque_monstro(acao)) is not None:
            ataques.append(a)

    ca = raw.get("armor_class")
    ca = (
        ca[0].get("value", 10) if isinstance(ca, list) and ca else ca if isinstance(ca, int) else 10
    )
    especiais = " ".join(s.get("name", "") for s in raw.get("special_abilities", []))
    return Monstro(
        id=raw["index"],
        nome=raw["name"],
        tipo=raw.get("type", ""),
        tamanho=raw.get("size", ""),
        cr=float(raw.get("challenge_rating", 0)),
        xp=int(raw.get("xp", 0)),
        ca=int(ca),
        pv=int(raw.get("hit_points", 1)),
        atributos=atributos,
        resistencias_bonus=resist,
        imunidades_dano=imunes,
        resistencias_dano=resistentes,
        vulnerabilidades_dano=vulneraveis,
        fisico_nao_magico="imune" if imune_fisico else "resiste" if resiste_fisico else None,
        imunidades_condicao=[c["index"] for c in raw.get("condition_immunities", [])],
        voa="fly" in (raw.get("speed") or {}),
        acoes_lendarias=len(raw.get("legendary_actions") or []),
        resistencia_lendaria="Legendary Resistance" in especiais,
        ataques=ataques,
        rotina=_rotina_monstro(multi, ataques),
    )


def montar_catalogo(registros: Iterable[tuple[str, str, object]]) -> Catalogo:
    """Monta o catálogo a partir de registros (recurso, id, json).

    `recurso` é a pasta de origem: races, classes, class_levels, spells, equipment, skills.
    """
    por_recurso: dict[str, dict[str, object]] = {}
    for recurso, id_, dados in registros:
        por_recurso.setdefault(recurso, {})[id_] = dados

    niveis = por_recurso.get("class_levels", {})
    equipamentos = [parse_equipamento(e) for e in por_recurso.get("equipment", {}).values()]
    return Catalogo(
        racas=sorted((parse_raca(r) for r in por_recurso.get("races", {}).values()), key=_id),
        classes=sorted(
            (parse_classe(c, niveis.get(i)) for i, c in por_recurso.get("classes", {}).items()),
            key=_id,
        ),
        magias=sorted((parse_magia(m) for m in por_recurso.get("spells", {}).values()), key=_id),
        armas=sorted((e for e in equipamentos if isinstance(e, Arma)), key=_id),
        armaduras=sorted((e for e in equipamentos if isinstance(e, Armadura)), key=_id),
        pericias=sorted(
            (parse_pericia(p) for p in por_recurso.get("skills", {}).values()), key=_id
        ),
        monstros=sorted(
            (parse_monstro(m) for m in por_recurso.get("monsters", {}).values()), key=_id
        ),
    )


def _id(x) -> str:
    return x.id


def ler_pasta(pasta: str | Path) -> list[tuple[str, str, object]]:
    """Lê `pasta/<recurso>/<id>.json` no formato de registros de `montar_catalogo`."""
    registros = []
    for arquivo in sorted(Path(pasta).glob("*/*.json")):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        registros.append((arquivo.parent.name, arquivo.stem, dados))
    return registros
