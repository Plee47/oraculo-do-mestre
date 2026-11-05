"""Gerador de fichas de D&D 5e: personagens válidos pelas regras, com cada escolha explicada.

O gerador é determinístico dado um `seed`, então a mesma entrada gera sempre a mesma ficha
(útil para testes e para compartilhar resultados).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from oraculo.nucleo.ficha import Ficha
from oraculo.nucleo.sistema import Classe, obter_regras
from oraculo.sistemas.dnd5e import modificador
from oraculo.sistemas.dnd5e.catalogo import Arma, Armadura, Catalogo, ClasseSRD, Magia, Raca

PAPEIS = ("defensor", "atacante", "conjurador", "suporte")
NOMES = (
    "Aelin", "Borin", "Caia", "Dorian", "Elowen", "Faris", "Garren", "Hana", "Ilyra", "Joran",
    "Kael", "Lira", "Mirela", "Nadir", "Orin", "Pell", "Quilla", "Ravi", "Sora", "Tamsin",
    "Ulric", "Vesna", "Wren", "Yara", "Zev",
)  # fmt: skip
CONJUNTO_PADRAO = (15, 14, 13, 12, 10, 8)
# Druidas não usam armadura de metal (SRD 5.1).
ARMADURAS_SEM_METAL = {"padded-armor", "leather-armor", "studded-leather-armor", "hide-armor"}
_ABREV = {"for": "FOR", "des": "DES", "con": "CON", "int": "INT", "sab": "SAB", "car": "CAR"}


@dataclass(frozen=True)
class Equipamento:
    armadura: Armadura | None
    escudo: Armadura | None
    arma: Arma | None
    arma_distancia: Arma | None
    ca: int


# --------------------------------------------------------------------------- atributos


def _peso(prioridade: list[str], atributo: str) -> int:
    """3 para o atributo principal, 2 para o segundo, 1 para o terceiro, 0 para o resto."""
    i = prioridade.index(atributo)
    return max(0, 3 - i)


def pontuar_raca(raca: Raca, prioridade: list[str]) -> float:
    pontos = sum(b * _peso(prioridade, a) for a, b in raca.bonus.items())
    opcoes = sorted((_peso(prioridade, a) for a in raca.bonus_escolha_opcoes), reverse=True)
    return pontos + sum(opcoes[: raca.bonus_escolha])


def aplicar_raca(atributos: dict[str, int], raca: Raca, prioridade: list[str]) -> list[str]:
    """Aplica os bônus raciais. Retorna os atributos escolhidos nos bônus livres."""
    for a, b in raca.bonus.items():
        atributos[a] += b
    livres = [a for a in prioridade if a in raca.bonus_escolha_opcoes and a not in raca.bonus]
    escolhidos = livres[: raca.bonus_escolha]
    for a in escolhidos:
        atributos[a] += 1
    return escolhidos


def aplicar_asis(atributos: dict[str, int], n_asis: int, prioridade: list[str]) -> list[str]:
    """Cada melhoria de atributo dá +2 pontos, na ordem de prioridade, até o limite 20."""
    log = []
    for _ in range(n_asis):
        pontos = 2
        for a in prioridade:
            while pontos and atributos[a] < 20:
                atributos[a] += 1
                pontos -= 1
                log.append(a)
            if not pontos:
                break
    return log


# --------------------------------------------------------------------------- equipamento


def _proficiente(arma: Arma, proficiencias: list[str]) -> bool:
    if arma.categoria in proficiencias:
        return True
    variantes = {arma.id, arma.id + "s", arma.id.replace("crossbow", "crossbows")}
    return any(p in variantes for p in proficiencias)


def _media(dado: str) -> float:
    qtd, _, faces = dado.partition("d")
    return int(qtd) * (int(faces) + 1) / 2 if faces else float(qtd)


def calcular_ca(
    atributos: dict[str, int],
    classe_id: str,
    armadura: Armadura | None,
    escudo: Armadura | None,
) -> int:
    des = modificador(atributos["des"])
    if armadura is None:
        ca = 10 + des
        if classe_id == "barbaro":
            ca += modificador(atributos["con"])
        elif classe_id == "monge" and escudo is None:
            ca += modificador(atributos["sab"])
    else:
        bonus_des = 0
        if armadura.soma_des:
            bonus_des = des if armadura.des_maxima is None else min(des, armadura.des_maxima)
        ca = armadura.ca_base + bonus_des
    return ca + (escudo.ca_base if escudo else 0)


def escolher_equipamento(
    cat: Catalogo, classe: Classe, srd: ClasseSRD, atributos: dict[str, int]
) -> Equipamento:
    # Armadura: a de maior CA que a classe sabe usar e que a FOR permite.
    candidatas: list[Armadura | None] = [None]
    candidatas += [
        a
        for a in cat.armaduras
        if a.categoria in srd.armaduras and a.categoria != "escudo"
        and a.for_minima <= atributos["for"]
        and (classe.id != "druida" or a.id in ARMADURAS_SEM_METAL)
    ]  # fmt: skip
    armadura = max(
        candidatas,
        key=lambda a: (
            calcular_ca(atributos, classe.id, a, None),
            not (a and a.desvantagem_furtividade),
            a is None,
        ),
    )

    usa_des = atributos["des"] > atributos["for"]
    usaveis = [a for a in cat.armas if _proficiente(a, srd.armas)]

    def pode_usar(a: Arma) -> bool:
        if a.alcance == "distancia" or "special" in a.propriedades:  # ex.: lança, rede
            return False
        return not usa_des or "finesse" in a.propriedades

    corpo = [a for a in usaveis if pode_usar(a)]
    # Bárbaro prefere arma de duas mãos (Fúria dá dano extra, não defesa).
    quer_escudo = "escudo" in srd.armaduras and classe.id != "barbaro"
    if quer_escudo:
        corpo = [a for a in corpo if "two-handed" not in a.propriedades] or corpo
    arma = max(corpo, key=lambda a: (_media(a.dano), a.id), default=None)
    distancia = [a for a in usaveis if a.alcance == "distancia"]
    arma_dist = max(distancia, key=lambda a: (_media(a.dano), a.id), default=None)

    escudo = None
    if quer_escudo and arma and "two-handed" not in arma.propriedades:
        escudo = next((a for a in cat.armaduras if a.categoria == "escudo"), None)

    return Equipamento(
        armadura=armadura,
        escudo=escudo,
        arma=arma,
        arma_distancia=arma_dist,
        ca=calcular_ca(atributos, classe.id, armadura, escudo),
    )


# --------------------------------------------------------------------------- magias

_PESOS_FUNCAO = {
    "conjurador": {"dano": 3.0, "controle": 2.5, "cura": 0.5, "utilidade": 1.0},
    "suporte": {"dano": 2.0, "controle": 2.0, "cura": 3.0, "utilidade": 1.0},
    "defensor": {"dano": 2.0, "controle": 1.5, "cura": 2.0, "utilidade": 1.0},
    "atacante": {"dano": 2.5, "controle": 1.5, "cura": 1.0, "utilidade": 1.0},
}


def _pontuar_magia(m: Magia, papel: str) -> float:
    pontos = _PESOS_FUNCAO[papel][m.funcao] + 0.6 * m.circulo
    if m.area and m.funcao in ("dano", "controle"):
        pontos += 1.0
    return pontos


def escolher_magias(
    cat: Catalogo, srd: ClasseSRD, papel: str, nivel: int, mod_conjuracao: int, rng
) -> tuple[list[Magia], list[Magia], int]:
    """Retorna (truques, magias, círculo máximo)."""
    info = srd.nivel(nivel)
    circulo = info.circulo_maximo
    if info.magias_conhecidas is not None:
        n = info.magias_conhecidas
    elif circulo == 0:
        n = 0
    elif srd.id == "paladin":
        n = max(1, mod_conjuracao + nivel // 2)
    else:
        n = max(1, mod_conjuracao + nivel)

    def ordenar(lista: list[Magia]) -> list[Magia]:
        return sorted(lista, key=lambda m: (-_pontuar_magia(m, papel), rng.random()))

    truques = ordenar([m for m in cat.magias_da_classe(srd.id, 0) if m.circulo == 0])
    truques = truques[: info.truques]

    disponiveis = [m for m in cat.magias_da_classe(srd.id, circulo) if m.circulo >= 1]
    escolhidas: list[Magia] = []
    concentracoes = 0
    while len(escolhidas) < n and disponiveis:
        # Evita encher a lista de magias de concentração (só uma fica ativa por vez).
        melhor = max(
            disponiveis,
            key=lambda m: _pontuar_magia(m, papel) - (concentracoes * 0.8 if m.concentracao else 0),
        )
        escolhidas.append(melhor)
        disponiveis.remove(melhor)
        concentracoes += melhor.concentracao
    escolhidas.sort(key=lambda m: (m.circulo, m.nome))
    return truques, escolhidas, circulo


# --------------------------------------------------------------------------- ficha


def gerar_ficha(
    catalogo: Catalogo,
    nivel: int,
    *,
    classe: str | None = None,
    papel: str | None = None,
    raca: str | None = None,
    nome: str | None = None,
    seed: int | None = None,
) -> Ficha:
    """Gera uma ficha de PJ.

    `classe` usa os ids do projeto (ex.: "mago"); `raca` usa os ids do SRD (ex.: "half-elf").
    Sem `classe`, sorteia uma classe do `papel` (ou de qualquer papel).
    """
    rng = random.Random(seed)
    defn = obter_regras("dnd5e").definicao
    nomes_racas = defn.extras.get("racas", {})
    expl: list[str] = []

    # 1. Classe
    if classe:
        cls = defn.classe(classe)
        if cls is None:
            raise ValueError(f"classe desconhecida: {classe!r}")
    else:
        if papel and papel not in PAPEIS:
            raise ValueError(f"papel deve ser um de {PAPEIS}")
        opcoes = [c for c in defn.classes if papel is None or c.papel == papel]
        cls = rng.choice(opcoes)
        expl.append(f"Classe {cls.nome}: sorteada entre as classes do papel {cls.papel}.")
    papel = cls.papel or "atacante"
    srd = catalogo.classe(cls.srd)
    pri = cls.prioridade

    # 2. Atributos pelo conjunto padrão
    atributos = dict(zip(pri, CONJUNTO_PADRAO, strict=True))
    ordem = " > ".join(_ABREV[a] for a in pri[:3])
    expl.append(f"Atributos: conjunto padrão (15, 14, 13, 12, 10, 8) priorizando {ordem}.")

    # 3. Raça
    if raca:
        r = catalogo.raca(raca)
    else:
        r = max(catalogo.racas, key=lambda x: (pontuar_raca(x, pri), rng.random()))
        expl.append(
            f"Raça {nomes_racas.get(r.id, r.nome)}: os bônus raciais combinam melhor com "
            f"{_ABREV[pri[0]]} e {_ABREV[pri[1]]}."
        )
    livres = aplicar_raca(atributos, r, pri)
    if livres:
        expl.append(f"Bônus raciais livres em {', '.join(_ABREV[a] for a in livres)}.")

    # 4. Melhorias de atributo
    n_asis = srd.nivel(nivel).asi_acumulados
    if n_asis:
        log = aplicar_asis(atributos, n_asis, pri)
        resumo = ", ".join(f"+{log.count(a)} {_ABREV[a]}" for a in dict.fromkeys(log))
        expl.append(f"{n_asis} melhoria(s) de atributo até o nível {nivel}: {resumo}.")

    # 5. Perícias
    pericias = sorted(
        srd.pericias_opcoes,
        key=lambda p: (pri.index(catalogo.pericia(p).atributo), rng.random()),
    )[: srd.pericias_escolha]
    expl.append(
        f"Perícias: as {srd.pericias_escolha} opções da classe ligadas aos atributos mais altos."
    )

    # 6. Equipamento
    eq = escolher_equipamento(catalogo, cls, srd, atributos)
    if eq.armadura:
        expl.append(f"Armadura {eq.armadura.nome}: a maior CA possível para esta ficha.")
    elif cls.id in ("barbaro", "monge"):
        expl.append("Sem armadura: a Defesa sem Armadura da classe dá CA maior.")
    if eq.escudo:
        expl.append("Escudo (+2 CA): troca o dano de uma arma de duas mãos por proteção.")
    if eq.arma:
        estilo = "acuidade (usa DES)" if "finesse" in eq.arma.propriedades else "corpo a corpo"
        expl.append(f"Arma principal {eq.arma.nome} ({eq.arma.dano}, {estilo}).")

    # 7. Magias
    poderes: list[str] = []
    if srd.conjuracao:
        mod = modificador(atributos[srd.conjuracao])
        truques, magias, circulo = escolher_magias(catalogo, srd, papel, nivel, mod, rng)
        poderes = [m.id for m in truques + magias]
        if magias or truques:
            foco = {
                "conjurador": "dano em área e controle",
                "suporte": "cura e controle",
                "defensor": "cura e reforço em combate",
                "atacante": "dano e mobilidade",
            }[papel]
            expl.append(
                f"Magias até o {circulo}º círculo ({len(truques)} truques, {len(magias)} magias), "
                f"priorizando {foco} e evitando várias magias de concentração."
            )

    equipamento = [x.id for x in (eq.armadura, eq.escudo, eq.arma, eq.arma_distancia) if x]
    return Ficha(
        nome=nome or rng.choice(NOMES),
        sistema="dnd5e",
        tipo="pj",
        nivel=nivel,
        classe=cls.id,
        atributos=atributos,
        metodo_atributos="livre",
        origem=r.id,
        pericias=pericias,
        equipamento=equipamento,
        poderes=poderes,
        explicacoes=expl,
        tags=[papel],
    )
