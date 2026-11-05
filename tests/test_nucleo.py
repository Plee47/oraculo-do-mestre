import pytest
from pydantic import ValidationError

from oraculo.nucleo import SISTEMAS_DISPONIVEIS, Ficha, obter_regras


def test_todos_os_sistemas_carregam():
    for sistema_id in SISTEMAS_DISPONIVEIS:
        regras = obter_regras(sistema_id)
        assert regras.definicao.id == sistema_id
        assert regras.definicao.atributos and regras.definicao.classes


def test_sistema_desconhecido():
    with pytest.raises(KeyError):
        obter_regras("gurps")


def test_ficha_exige_nome_e_nivel_positivo():
    with pytest.raises(ValidationError):
        Ficha(nome="", sistema="dnd5e")
    with pytest.raises(ValidationError):
        Ficha(nome="X", sistema="dnd5e", nivel=0)


def test_ficha_serializa_ida_e_volta():
    f = Ficha(nome="Lia", sistema="dnd5e", classe="mago", atributos={"int": 16}, tags=["npc"])
    assert Ficha.model_validate_json(f.model_dump_json()) == f
