import pytest

from oraculo.nucleo import Ficha, obter_regras
from oraculo.sistemas.dnd5e import bonus_proficiencia, custo_compra_pontos, modificador

REGRAS = obter_regras("dnd5e")
PADRAO = {"for": 15, "des": 14, "con": 13, "int": 12, "sab": 10, "car": 8}


def ficha(**kw) -> Ficha:
    base = dict(nome="Teste", sistema="dnd5e", classe="guerreiro", atributos=dict(PADRAO))
    return Ficha(**{**base, **kw})


@pytest.mark.parametrize(
    ("valor", "mod"), [(1, -5), (8, -1), (9, -1), (10, 0), (11, 0), (15, 2), (20, 5), (30, 10)]
)
def test_modificador(valor, mod):
    assert modificador(valor) == mod


@pytest.mark.parametrize(("nivel", "prof"), [(1, 2), (4, 2), (5, 3), (9, 4), (13, 5), (17, 6)])
def test_proficiencia(nivel, prof):
    assert bonus_proficiencia(nivel) == prof


def test_pv_guerreiro_nivel_1_e_5():
    # d10, CON 13 (+1): nível 1 = 10+1; cada nível seguinte = 6+1
    assert REGRAS.derivados(ficha(nivel=1))["pv_maximo"] == 11
    assert REGRAS.derivados(ficha(nivel=5))["pv_maximo"] == 11 + 4 * 7


def test_pv_minimo_de_1_por_nivel():
    attrs = {**PADRAO, "con": 1}  # mod -5
    assert REGRAS.derivados(ficha(classe="mago", nivel=3, atributos=attrs))["pv_maximo"] == 3


def test_resistencias_proficientes_da_classe():
    d = REGRAS.derivados(ficha())  # guerreiro: FOR e CON
    assert d["resistencia_for"] == 2 + 2
    assert d["resistencia_con"] == 1 + 2
    assert d["resistencia_des"] == 2


def test_cd_de_magia_so_para_conjuradores():
    attrs = {**PADRAO, "int": 16}
    assert REGRAS.derivados(ficha(classe="mago", atributos=attrs))["cd_magia"] == 8 + 2 + 3
    assert "cd_magia" not in REGRAS.derivados(ficha())


def test_defesa_sem_armadura_barbaro_e_monge():
    assert REGRAS.derivados(ficha(classe="barbaro"))["ca_sem_armadura"] == 10 + 2 + 1
    assert REGRAS.derivados(ficha(classe="monge"))["ca_sem_armadura"] == 10 + 2 + 0


def test_ficha_padrao_valida():
    assert REGRAS.validar(ficha(metodo_atributos="padrao")) == []


def test_compra_de_pontos():
    assert custo_compra_pontos(PADRAO) == 27
    ok = ficha(metodo_atributos="compra_pontos")
    caro = ficha(metodo_atributos="compra_pontos", atributos={**PADRAO, "car": 15})
    fora = ficha(metodo_atributos="compra_pontos", atributos={**PADRAO, "for": 17})
    assert REGRAS.ficha_valida(ok)
    assert not REGRAS.ficha_valida(caro)
    assert not REGRAS.ficha_valida(fora)


def test_conjunto_padrao_invalido():
    f = ficha(metodo_atributos="padrao", atributos={**PADRAO, "for": 16})
    assert not REGRAS.ficha_valida(f)


@pytest.mark.parametrize(
    "kw",
    [
        {"classe": "astronauta"},
        {"nivel": 21},
        {"atributos": {"for": 10}},
        {"atributos": {**PADRAO, "sorte": 12}},
        {"atributos": {**PADRAO, "for": 31}},
        {"sistema": "fm"},
    ],
)
def test_erros_de_regra(kw):
    assert not REGRAS.ficha_valida(ficha(**kw))


def test_aviso_atributo_principal_baixo():
    attrs = {"for": 8, "des": 10, "con": 14, "int": 12, "sab": 13, "car": 15}
    problemas = REGRAS.validar(ficha(classe="mago", atributos=attrs))
    assert REGRAS.ficha_valida(ficha(classe="mago", atributos=attrs))  # aviso não invalida
    assert any(p.gravidade == "aviso" and "Mago" in p.mensagem for p in problemas)


def test_npc_nao_precisa_de_classe():
    assert REGRAS.ficha_valida(ficha(tipo="npc", classe=None))
