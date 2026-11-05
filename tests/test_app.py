"""Smoke tests do site: cada página renderiza sem exceção."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app" / "streamlit_app.py")
PAGINAS = ("Início", "Ficha rápida (D&D 5e)", "Roteiro", "Conteúdo e licenças")


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
