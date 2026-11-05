"""Smoke tests do site: cada página renderiza sem exceção."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app" / "streamlit_app.py")
PAGINAS = (
    "Início",
    "Gerador de fichas (D&D 5e)",
    "Análise de grupo e encontro (D&D 5e)",
    "Detector de livros de RPG",
    "Ficha rápida (D&D 5e)",
    "Roteiro",
    "Conteúdo e licenças",
)


@pytest.mark.parametrize("pagina", PAGINAS)
def test_pagina_renderiza(pagina):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value(pagina).run()
    assert not at.exception


def test_ficha_rapida_calcula_e_valida():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value("Ficha rápida (D&D 5e)").run()
    pv = next(m for m in at.metric if m.label == "PV máximo")
    assert pv.value == "11"  # guerreiro nível 1, CON 13
    assert at.success  # conjunto 15/14/13/12/10/8 custa exatamente 27 pontos

    at.number_input(key="attr_car").set_value(15).run()  # estoura o orçamento
    assert at.error


def test_gerador_de_fichas_gera_e_regera():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value("Gerador de fichas (D&D 5e)").run()
    assert not at.exception
    assert not at.error  # a ficha gerada é válida
    titulo = at.subheader[0].value
    at.button[0].click().run()  # "Gerar outra"
    assert not at.exception
    assert at.subheader[0].value != titulo or at.session_state.semente == 2


def test_analise_de_grupo_e_encontro():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value("Análise de grupo e encontro (D&D 5e)").run()
    assert not at.exception
    assert at.dataframe  # tabela do grupo
    assert any(m.label == "Dificuldade oficial (XP)" for m in at.metric)
    at.multiselect[0].set_value(["Adult Red Dragon (CR 17)"]).run()
    assert not at.exception
    assert any("num único turno" in e.value for e in at.error)


def test_detector_com_texto_colado():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value("Detector de livros de RPG").run()
    assert not at.exception
    trecho = (
        "Armor Class 14, Hit Points 27 (5d8 + 5). STR 15 (+2) DEX 14 (+2). The target must "
        "succeed on a DC 12 saving throw. Your character adds the proficiency bonus. "
    ) * 4
    at.text_area[0].set_value(trecho).run()
    assert not at.exception
    assert any("Parece um livro de RPG" in s.value for s in at.success)
