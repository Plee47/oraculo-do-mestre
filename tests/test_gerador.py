"""Gerador de fichas sobre o catálogo público completo (dados/publicos/dnd5e/catalogo.json)."""

from pathlib import Path

import pytest

from oraculo.nucleo import obter_regras
from oraculo.sistemas.dnd5e.catalogo import Armadura, Catalogo
from oraculo.sistemas.dnd5e.gerador import (
    ARMADURAS_SEM_METAL,
    PAPEIS,
    aplicar_asis,
    calcular_ca,
    gerar_ficha,
)
from oraculo.sistemas.dnd5e.tabelas import (
    catalogo_para_linhas,
    linhas_para_catalogo,
    validar_catalogo,
)

CATALOGO = Path(__file__).parents[1] / "dados" / "publicos" / "dnd5e" / "catalogo.json"
REGRAS = obter_regras("dnd5e")
CLASSES = [c.id for c in REGRAS.definicao.classes]


@pytest.fixture(scope="module")
def cat() -> Catalogo:
    return Catalogo.carregar(CATALOGO)


def test_catalogo_publico_passa_nas_expectativas(cat):
    assert validar_catalogo(cat) == []


def test_tabelas_ida_e_volta(cat):
    linhas = catalogo_para_linhas(cat)
    assert set(linhas) == {
        "racas",
        "classes",
        "magias",
        "armas",
        "armaduras",
        "pericias",
        "monstros",
    }
    jsons = {t: [linha["dados_json"] for linha in ls] for t, ls in linhas.items()}
    assert linhas_para_catalogo(jsons) == cat


@pytest.mark.parametrize("classe", CLASSES)
@pytest.mark.parametrize("nivel", [1, 4, 8, 12, 16, 20])
def test_toda_ficha_gerada_e_valida(cat, classe, nivel):
    ficha = gerar_ficha(cat, nivel, classe=classe, seed=nivel)
    erros = [p for p in REGRAS.validar(ficha) if p.gravidade == "erro"]
    assert erros == []
    assert all(v <= 20 for v in ficha.atributos.values())
    assert ficha.explicacoes


def test_mesma_seed_mesma_ficha(cat):
    assert gerar_ficha(cat, 7, seed=42) == gerar_ficha(cat, 7, seed=42)


@pytest.mark.parametrize("papel", PAPEIS)
def test_papel_filtra_classes(cat, papel):
    for seed in range(5):
        ficha = gerar_ficha(cat, 5, papel=papel, seed=seed)
        assert REGRAS.definicao.classe(ficha.classe).papel == papel


def test_parametros_invalidos(cat):
    with pytest.raises(ValueError):
        gerar_ficha(cat, 5, classe="astronauta")
    with pytest.raises(ValueError):
        gerar_ficha(cat, 5, papel="bardo-de-guerra")


def test_magias_respeitam_lista_da_classe_e_circulo(cat):
    ficha = gerar_ficha(cat, 5, classe="mago", seed=1)
    magias = {m.id: m for m in cat.magias}
    assert ficha.poderes
    for mid in ficha.poderes:
        assert "wizard" in magias[mid].classes
        assert magias[mid].circulo <= 3


def test_conjurador_que_conhece_magias_tem_a_quantidade_da_tabela(cat):
    ficha = gerar_ficha(cat, 5, classe="feiticeiro", seed=1)
    nivel5 = cat.classe("sorcerer").nivel(5)
    magias = {m.id: m for m in cat.magias}
    truques = [m for m in ficha.poderes if magias[m].circulo == 0]
    assert len(truques) == nivel5.truques
    assert len(ficha.poderes) - len(truques) == nivel5.magias_conhecidas


def test_paladino_nivel_1_nao_tem_magias(cat):
    assert gerar_ficha(cat, 1, classe="paladino", seed=1).poderes == []


def test_druida_nao_usa_metal_e_barbaro_nao_usa_escudo(cat):
    druida = gerar_ficha(cat, 5, classe="druida", seed=1)
    armaduras = {a.id: a for a in cat.armaduras}
    for item in druida.equipamento:
        if item in armaduras and armaduras[item].categoria != "escudo":
            assert item in ARMADURAS_SEM_METAL
    assert "shield" not in gerar_ficha(cat, 5, classe="barbaro", seed=1).equipamento


def test_defensor_com_escudo_nao_usa_arma_de_duas_maos(cat):
    ficha = gerar_ficha(cat, 5, classe="guerreiro", seed=1)
    armas = {a.id: a for a in cat.armas}
    assert "shield" in ficha.equipamento
    principal = next(armas[i] for i in ficha.equipamento if i in armas)
    assert "two-handed" not in principal.propriedades
    assert "special" not in principal.propriedades  # nada de lança como arma principal


def test_raca_escolhida_pelo_usuario_e_respeitada(cat):
    assert gerar_ficha(cat, 3, classe="mago", raca="dwarf", seed=1).origem == "dwarf"


def test_asis_vao_para_o_atributo_principal_ate_20():
    attrs = {"for": 17, "con": 14, "des": 10}
    aplicar_asis(attrs, 3, ["for", "con", "des"])
    assert attrs == {"for": 20, "con": 17, "des": 10}


def test_calculo_de_ca():
    attrs = {"for": 15, "des": 16, "con": 14, "int": 10, "sab": 14, "car": 8}
    couro = Armadura(id="l", nome="L", categoria="leve", ca_base=11, soma_des=True)
    media = Armadura(id="m", nome="M", categoria="media", ca_base=14, soma_des=True, des_maxima=2)
    escudo = Armadura(id="s", nome="S", categoria="escudo", ca_base=2, soma_des=False)
    assert calcular_ca(attrs, "ladino", couro, None) == 14
    assert calcular_ca(attrs, "guerreiro", media, escudo) == 18
    assert calcular_ca(attrs, "barbaro", None, None) == 10 + 3 + 2
    assert calcular_ca(attrs, "monge", None, None) == 10 + 3 + 2
    assert calcular_ca(attrs, "monge", None, escudo) == 10 + 3 + 2  # monge com escudo perde SAB
