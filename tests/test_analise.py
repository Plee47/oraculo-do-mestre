"""Análises de grupo e encontro: cenários com resultado conhecido por quem joga D&D."""

from pathlib import Path

import pytest

from oraculo.sistemas.dnd5e.analise import (
    analisar_encontro,
    analisar_grupo,
    dificuldade_oficial,
    perfil,
    prob_acerto,
    prob_falha,
)
from oraculo.sistemas.dnd5e.catalogo import Catalogo
from oraculo.sistemas.dnd5e.gerador import gerar_ficha

CATALOGO = Path(__file__).parents[1] / "dados" / "publicos" / "dnd5e" / "catalogo.json"


@pytest.fixture(scope="module")
def cat() -> Catalogo:
    return Catalogo.carregar(CATALOGO)


def grupo(cat, classes, nivel):
    return [gerar_ficha(cat, nivel, classe=c, seed=i + 1) for i, c in enumerate(classes)]


def titulos(achados):
    return [a.titulo for a in achados]


@pytest.fixture(scope="module")
def padrao(cat):
    return grupo(cat, ["guerreiro", "clerigo", "ladino", "mago"], 5)


def encontro(cat, fichas, *monstros):
    return analisar_encontro(fichas, [(cat.monstro(m), q) for m, q in monstros], cat)


# --------------------------------------------------------------------------- probabilidades


def test_probabilidades():
    assert prob_acerto(5, 15) == pytest.approx(0.55)
    assert prob_acerto(0, 40) == 0.05 and prob_acerto(30, 5) == 0.95
    assert prob_falha(15, 4) == pytest.approx(0.5)
    assert prob_falha(5, 10) == 0


def test_dificuldade_oficial():
    # 4 PJs nível 1 contra 4 goblins: 200 XP x2 = 400 = limiar mortal
    assert dificuldade_oficial([1] * 4, [50] * 4) == (400, "Mortal")
    assert dificuldade_oficial([5] * 4, [450]) == (450, "Trivial")


# --------------------------------------------------------------------------- perfil


def test_perfil_do_mago_tem_dano_magico_e_area(cat, padrao):
    mago = perfil(padrao[3], cat)
    assert mago.dano_magico and mago.area and mago.distancia
    assert mago.truque_dano > 0
    assert not mago.arma_magica  # truque mágico não deixa a adaga mágica


def test_perfil_do_guerreiro(cat, padrao):
    g = perfil(padrao[0], cat)
    assert g.ataques == 2  # ataque extra no nível 5
    assert g.ca >= 18 and not g.dano_magico


# --------------------------------------------------------------------------- grupo


def test_grupo_equilibrado_nao_tem_alertas(cat, padrao):
    achados = analisar_grupo(padrao, cat)
    assert not [a for a in achados if a.severidade == "alerta"]
    assert "Há cura no grupo" in titulos(achados)


def test_grupo_so_de_combatentes(cat):
    achados = analisar_grupo(grupo(cat, ["guerreiro", "barbaro", "ladino", "monge"], 3), cat)
    t = titulos(achados)
    assert "Ninguém do grupo cura" in t
    assert "Todo o dano do grupo é físico e não mágico" in t
    assert "Nenhum dano em área" in t
    assert any(x.startswith("Resistência de SAB fraca") for x in t)
    assert achados[0].severidade == "alerta"  # ordenado por gravidade


def test_monge_de_nivel_6_tem_golpes_magicos(cat):
    achados = analisar_grupo(grupo(cat, ["guerreiro", "barbaro", "ladino", "monge"], 6), cat)
    assert "Todo o dano do grupo é físico e não mágico" not in titulos(achados)


def test_todo_achado_explica_a_regra(cat):
    fichas = grupo(cat, ["guerreiro", "barbaro"], 2)
    for a in analisar_grupo(fichas, cat):
        assert a.regra and a.detalhe


def test_grupo_vazio(cat):
    assert analisar_grupo([], cat) == []


# --------------------------------------------------------------------------- encontro


def test_dragao_adulto_contra_nivel_5(cat, padrao):
    resumo, achados = encontro(cat, padrao, ("adult-red-dragon", 1))
    t = titulos(achados)
    assert resumo.dificuldade_oficial == "Mortal"
    assert resumo.rodadas_para_perder < resumo.rodadas_para_vencer
    assert "O grupo tende a cair antes" in t
    assert any("num único turno" in x for x in t)
    assert any(x.startswith("Frightful Presence") for x in t)
    assert "Adult Red Dragon tem Resistência Lendária" in t


def test_horda_de_goblins_e_facil_no_nivel_5(cat, padrao):
    resumo, achados = encontro(cat, padrao, ("goblin", 8))
    assert resumo.dificuldade_oficial == "Fácil"
    assert resumo.rodadas_para_vencer < resumo.rodadas_para_perder
    assert not [a for a in achados if a.severidade == "alerta"]


def test_horda_sem_area_gera_alerta(cat):
    marciais = grupo(cat, ["guerreiro", "barbaro", "ladino", "monge"], 3)
    _, achados = encontro(cat, marciais, ("goblin", 10))
    assert "10 inimigos e nenhum dano em área" in titulos(achados)


def test_gargula_reduz_dano_fisico(cat, padrao):
    _, achados = encontro(cat, padrao, ("gargoyle", 2))
    reduz = [a for a in achados if a.titulo.startswith("Gargoyle reduz à metade")]
    assert reduz
    nomes_mago_clerigo = {padrao[1].nome, padrao[3].nome}
    assert not any(n in reduz[0].titulo for n in nomes_mago_clerigo)


def test_esqueleto_vulneravel_a_contundente(cat, padrao):
    _, achados = encontro(cat, padrao, ("skeleton", 4))
    assert any(a.severidade == "ok" and "dano dobrado em Skeleton" in a.titulo for a in achados)


def test_monstro_solo_sem_acoes_lendarias(cat, padrao):
    _, achados = encontro(cat, padrao, ("ogre", 1))
    assert any("age 1 vez para cada 4" in t for t in titulos(achados))


def test_voador_contra_grupo_sem_ataque_a_distancia(cat):
    fichas = grupo(cat, ["guerreiro"], 3)
    fichas[0].equipamento = [i for i in fichas[0].equipamento if "crossbow" not in i]
    _, achados = encontro(cat, fichas, ("giant-eagle", 1))
    assert any("voa(m) e ninguém ataca à distância" in t for t in titulos(achados))


def test_encontro_vazio(cat, padrao):
    with pytest.raises(ValueError):
        analisar_encontro(padrao, [], cat)
