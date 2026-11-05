"""Parsing do SRD 5.1 a partir de JSONs reais da API (tests/fixtures/srd51)."""

from pathlib import Path

import pytest

from oraculo.sistemas.dnd5e.catalogo import Arma, Armadura
from oraculo.sistemas.dnd5e.srd import ler_pasta, montar_catalogo, parse_equipamento

FIXTURES = Path(__file__).parent / "fixtures" / "srd51"


@pytest.fixture(scope="module")
def cat():
    return montar_catalogo(ler_pasta(FIXTURES))


def test_resumo(cat):
    assert cat.resumo() == {
        "racas": 2,
        "classes": 2,
        "magias": 4,
        "armas": 2,
        "armaduras": 2,
        "pericias": 2,
    }


def test_raca_com_bonus_livres(cat):
    meio_elfo = cat.raca("half-elf")
    assert meio_elfo.bonus == {"car": 2}
    assert meio_elfo.bonus_escolha == 2
    assert "car" not in meio_elfo.bonus_escolha_opcoes
    assert cat.raca("human").bonus == dict.fromkeys(("for", "des", "con", "int", "sab", "car"), 1)


def test_classe_conjuradora(cat):
    mago = cat.classe("wizard")
    assert (mago.dado_vida, mago.conjuracao, mago.resistencias) == (6, "int", ["int", "sab"])
    assert mago.armaduras == []
    assert mago.pericias_escolha == 2 and "arcana" in mago.pericias_opcoes
    n5 = mago.nivel(5)
    assert (n5.proficiencia, n5.truques, n5.espacos[:3], n5.circulo_maximo) == (3, 4, [4, 3, 2], 3)
    assert n5.magias_conhecidas is None  # mago prepara magias


def test_classe_marcial(cat):
    guerreiro = cat.classe("fighter")
    assert guerreiro.armaduras == ["escudo", "leve", "media", "pesada"]
    assert guerreiro.armas == ["simples", "marcial"]
    assert [n.nivel for n in guerreiro.niveis] == list(range(1, 21))
    # guerreiro ganha melhorias extras nos níveis 6 e 14
    assert guerreiro.nivel(6).asi_acumulados == 2
    assert guerreiro.nivel(20).circulo_maximo == 0


def test_magias(cat):
    bola = next(m for m in cat.magias if m.id == "fireball")
    assert (bola.circulo, bola.dano, bola.resistencia, bola.area, bola.funcao) == (
        3,
        "8d6",
        "des",
        True,
        "dano",
    )
    assert next(m for m in cat.magias if m.id == "cure-wounds").funcao == "cura"
    assert next(m for m in cat.magias if m.id == "hold-person").funcao == "controle"
    truque = next(m for m in cat.magias if m.id == "fire-bolt")
    assert (truque.circulo, truque.dano, truque.ataque) == (0, "1d10", "ranged")


def test_equipamentos(cat):
    cota = next(a for a in cat.armaduras if a.id == "chain-mail")
    assert (cota.categoria, cota.ca_base, cota.soma_des, cota.for_minima) == (
        "pesada",
        16,
        False,
        13,
    )
    escudo = next(a for a in cat.armaduras if a.id == "shield")
    assert (escudo.categoria, escudo.ca_base) == ("escudo", 2)
    rapieira = next(a for a in cat.armas if a.id == "rapier")
    assert (rapieira.categoria, rapieira.dano, rapieira.propriedades) == (
        "marcial",
        "1d8",
        ["finesse"],
    )


def test_equipamento_que_nao_e_arma_nem_armadura_e_ignorado():
    assert (
        parse_equipamento(
            {"index": "backpack", "equipment_category": {"index": "adventuring-gear"}}
        )
        is None
    )
    assert isinstance(
        parse_equipamento(
            {
                "index": "x",
                "name": "X",
                "equipment_category": {"index": "weapon"},
                "damage": {"damage_dice": "1d6", "damage_type": {"index": "slashing"}},
            }
        ),
        Arma,
    )
    assert not isinstance(parse_equipamento({"index": "y", "equipment_category": {}}), Armadura)
