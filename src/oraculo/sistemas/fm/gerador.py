"""Gerador de fichas de Feiticeiros & Maldições, com cada escolha explicada.

Determinístico dado um `seed`. Cobre a parte mecânica da ficha (especialização, origem,
atributos, perícias, resistências, equipamento inicial padrão). A técnica inata e os feitiços
são criados pelo jogador no sistema, então a ficha só reserva os espaços deles.
"""

from __future__ import annotations

import random

from oraculo.nucleo.ficha import Ficha
from oraculo.sistemas.fm import (
    ATRIBUTOS,
    Regras,
    melhor_atributo,
    modificador,
)

PAPEIS = ("combatente", "tecnico", "controlador", "suporte")
NOMES = (
    "Akemi", "Daichi", "Emi", "Haru", "Hikari", "Isamu", "Kaede", "Kenji", "Mei", "Minoru",
    "Nanase", "Ren", "Rin", "Satoshi", "Shion", "Sora", "Takumi", "Yui", "Yuna", "Zen",
)  # fmt: skip
_ABREV = {a: a.upper() for a in ATRIBUTOS}
LIMITE_CRIACAO = 20


def _distribuir(
    atributos: dict[str, int],
    pontos: int,
    ordem: list[str],
    *,
    maximo_por_atributo: int | None = None,
) -> list[str]:
    """Distribui pontos um a um na ordem, preferindo deixar valores pares (mod sobe a cada 2)."""
    log: list[str] = []
    recebido = dict.fromkeys(ordem, 0)

    def pode(a: str) -> bool:
        teto = maximo_por_atributo is None or recebido[a] < maximo_por_atributo
        return teto and atributos[a] < LIMITE_CRIACAO

    while pontos:
        impares = [a for a in ordem if atributos[a] % 2 and pode(a)]
        candidatos = impares or [a for a in ordem if pode(a)]
        if not candidatos:
            break
        a = candidatos[0]
        # Sem ímpar para completar e com 1 ponto só, ele ainda vale (fica para o próximo nível).
        atributos[a] += 1
        recebido[a] += 1
        pontos -= 1
        log.append(a)
    return log


def aplicar_origem(atributos: dict[str, int], origem: dict, prioridade: list[str]) -> list[str]:
    log: list[str] = []
    for a, b in origem.get("fixo", {}).items():
        atributos[a] += b
        log += [a] * b
    livres = [a for a in prioridade if a not in origem.get("fixo", {})]
    for bonus, a in zip(origem.get("livres", []), livres, strict=False):
        atributos[a] += bonus
        log += [a] * bonus
    if origem.get("pontos"):
        ordem = [a for a in prioridade if a in origem.get("pontos_em", prioridade)]
        log += _distribuir(
            atributos,
            origem["pontos"],
            ordem,
            maximo_por_atributo=origem.get("maximo_por_atributo"),
        )
    return log


def _resumo(log: list[str]) -> str:
    return ", ".join(f"+{log.count(a)} {_ABREV[a]}" for a in dict.fromkeys(log))


def escolher_pericias(
    regras: Regras, classe_id: str, atributos: dict[str, int], extras: int, rng: random.Random
) -> tuple[list[str], str]:
    regra = regras.extras["pericias_especializacao"][classe_id]
    tabela = regras.extras["pericias"]
    escolhidas: list[str] = []
    if regra.get("oficios"):
        escolhidas.append("oficio")
    escolhidas += regra.get("fixas", [])
    if regra.get("uma_de"):
        escolhidas.append(
            max(regra["uma_de"], key=lambda p: (atributos[tabela[p]["atributo"]], rng.random()))
        )
    proibidas = set(regra.get("proibidas", []))
    resto = sorted(
        (p for p in tabela if p not in escolhidas and p not in proibidas),
        key=lambda p: (-atributos[tabela[p]["atributo"]], rng.random()),
    )
    n_livres = regra.get("livres", 0) + extras
    escolhidas += resto[:n_livres]
    oficios = regra.get("oficios", 0)
    texto = (
        f"Perícias: {oficios} de Ofício, as obrigatórias da especialização e {n_livres} livres "
        "ligadas aos atributos mais altos."
    )
    return escolhidas, texto


def gerar_ficha(
    nivel: int,
    *,
    classe: str | None = None,
    papel: str | None = None,
    origem: str | None = None,
    nome: str | None = None,
    seed: int | None = None,
) -> Ficha:
    """Gera uma ficha de PJ. `classe` é o id da especialização; `origem`, o id da origem."""
    rng = random.Random(seed)
    regras = Regras()
    defn = regras.definicao
    origens = regras.extras["origens"]
    expl: list[str] = []

    # 1. Especialização (Restringido só com a origem Restringido, e vice-versa)
    if origem == "restringido":
        classe = classe or "restringido"
    if classe:
        cls = defn.classe(classe)
        if cls is None:
            raise ValueError(f"especialização desconhecida: {classe!r}")
    else:
        if papel and papel not in PAPEIS:
            raise ValueError(f"papel deve ser um de {PAPEIS}")
        opcoes = [
            c for c in defn.classes
            if (papel is None or c.papel == papel) and (c.id != "restringido" or origem is None)
        ]  # fmt: skip
        cls = rng.choice(opcoes)
        expl.append(f"Especialização {cls.nome}: sorteada entre as do papel {cls.papel}.")
    pri = cls.prioridade

    # 2. Origem
    if cls.id == "restringido":
        origem = "restringido"
    elif origem is None:
        origem = "inato"
        expl.append(
            "Origem Inato: a mais versátil, combina com qualquer especialização "
            "(+2 e +1 em atributos e um talento no 1º nível)."
        )
    if origem not in origens:
        raise ValueError(f"origem desconhecida: {origem!r}")

    # 3. Atributos: valores fixos na ordem de prioridade + bônus da origem
    atributos = dict(zip(pri, defn.extras["conjunto_padrao"], strict=True))
    ordem = " > ".join(_ABREV[a] for a in pri[:3])
    expl.append(f"Atributos: valores fixos (15, 14, 13, 12, 10, 8) priorizando {ordem}.")
    log = aplicar_origem(atributos, origens[origem], pri)
    if log:
        expl.append(f"Bônus da origem {origens[origem]['nome']}: {_resumo(log)}.")

    # 4. Pontos de atributo a cada 4 níveis
    n = sum(1 for n_ in defn.extras["niveis_pontos_atributo"] if n_ <= nivel)
    if n:
        log = _distribuir(atributos, 2 * n, pri)
        expl.append(f"{2 * n} pontos de atributo até o nível {nivel}: {_resumo(log)}.")

    # 5. Perícias e teste de resistência
    pericias, texto = escolher_pericias(
        regras, cls.id, atributos, origens[origem].get("pericias_extras", 0), rng
    )
    expl.append(texto)
    res = regras.extras["resistencias"]
    if not cls.resistencias_escolha:
        nomes = " e ".join(res[x]["nome"] for x in cls.resistencias)
        expl.append(f"Testes de resistência treinados: {nomes} (os dois da especialização).")
    else:
        r = melhor_atributo({x: atributos[res[x]["atributo"]] for x in cls.resistencias},
                            cls.resistencias)  # fmt: skip
        pericias.append(r)
        expl.append(
            f"Teste de resistência treinado: {res[r]['nome']}, o do melhor atributo entre as "
            "opções da especialização."
        )

    # 6. Equipamento inicial padrão: 2 itens de custo 1, uniforme comum e um kit
    if cls.papel == "combatente":
        itens = ["arma corpo a corpo (custo 1)", "escudo leve (custo 1)"]
        if cls.id in regras.extras["armas_distancia"] and atributos["des"] >= atributos["for"]:
            itens[1] = "arma à distância (custo 1)"
    elif cls.papel == "suporte":
        itens = ["arma simples (custo 1)", "item especial de cura (custo 1)"]
    else:
        itens = ["arma à distância (custo 1)", "arma simples (custo 1)"]
    equipamento = [*itens, "uniforme comum", "kit de ferramentas"]
    expl.append(
        "Equipamento inicial padrão do sistema: dois itens de custo 1, uniforme comum e um kit."
    )

    # 7. Técnica e feitiços (criados pelo jogador)
    if cls.id == "restringido":
        poderes = ["estilo marcial"]
        expl.append("Restringido não tem energia amaldiçoada: usa estamina e um estilo marcial.")
    elif origem == "sem_tecnica":
        poderes = []
        expl.append("Sem Técnica: não recebe técnica inata nem feitiços iniciais.")
    else:
        poderes = ["técnica inata", "feitiço 1", "feitiço 2"]
        if origem == "inato":
            poderes.append("feitiço de marca registrada (custo -1 PE)")
        tecnica = regras.atributo_tecnica(
            Ficha(nome="x", sistema="fm", classe=cls.id, atributos=atributos)
        )
        expl.append(
            f"Técnica: {len(poderes) - 1} feitiços para montar no capítulo de criação de técnica; "
            f"atributo do jujutsu {_ABREV[tecnica]} ({modificador(atributos[tecnica]):+d})."
        )

    return Ficha(
        nome=nome or rng.choice(NOMES),
        sistema="fm",
        tipo="pj",
        nivel=nivel,
        classe=cls.id,
        atributos=atributos,
        metodo_atributos="livre",
        origem=origem,
        pericias=pericias,
        equipamento=equipamento,
        poderes=poderes,
        explicacoes=expl,
        tags=[cls.papel or "combatente"],
    )
