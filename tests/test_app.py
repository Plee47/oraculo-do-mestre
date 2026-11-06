"""Smoke tests do site: o fluxo começa pelo livro, e as ferramentas seguem o sistema validado."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app" / "streamlit_app.py")
TRECHO_DND = (
    "Armor Class 14, Hit Points 27 (5d8 + 5). STR 15 (+2) DEX 14 (+2). The target must "
    "succeed on a DC 12 saving throw. Your character adds the proficiency bonus. "
) * 4
SEMPRE = ("Início", "Bastidores do leitor", "Roteiro", "Conteúdo e licenças")
COM_LIVRO = ("Gerador de fichas", "Ficha rápida", "Análises")


def abrir(sistema: str | None = None) -> AppTest:
    """Abre o site; com `sistema`, já com um livro de demonstração validado."""
    at = AppTest.from_file(APP, default_timeout=30)
    if sistema:
        at.session_state["livro"] = {
            "sistema": sistema, "nome": "demo", "nota": None, "demo": True,
        }  # fmt: skip
    return at.run()


def ir(at: AppTest, pagina: str) -> AppTest:
    at.sidebar.radio[0].set_value(pagina).run()
    assert not at.exception
    return at


def erros_de_ficha(at: AppTest) -> list[str]:
    # Achados das análises começam com o título em negrito; o resto seriam erros de validação.
    return [e.value for e in at.error if not e.value.startswith("**")]


# --------------------------------------------------------------------------- sem livro


def test_sem_livro_so_aparecem_inicio_e_paginas_gerais():
    at = abrir()
    assert not at.exception
    assert tuple(at.sidebar.radio[0].options) == SEMPRE
    for pagina in SEMPRE:
        ir(at, pagina)


def test_texto_de_rpg_aceito_libera_as_ferramentas():
    at = abrir()
    at.text_area[0].set_value(TRECHO_DND).run()
    assert any("Livro aceito pelo porteiro" in s.value for s in at.success)
    at.button[0].click().run()  # "Usar este livro e criar fichas"
    assert not at.exception
    assert at.session_state.livro["sistema"] == "dnd5e"
    assert at.session_state.pagina == "Gerador de fichas"
    assert set(COM_LIVRO) <= set(at.sidebar.radio[0].options)
    assert at.title[0].value == "Gerador de fichas · D&D 5e"


def test_texto_que_nao_e_rpg_nao_libera_nada():
    at = abrir()
    at.text_area[0].set_value("The old knight walked home and she said goodbye. " * 30).run()
    assert any("Não parece um livro de RPG" in i.value for i in at.info)
    assert tuple(at.sidebar.radio[0].options) == SEMPRE


def test_rpg_de_sistema_desconhecido_explica():
    at = abrir()
    at.text_area[0].set_value(TRECHO_DND + " Tagmar karma estágio tabela de resolução " * 8).run()
    assert any("ainda não conhece" in w.value for w in at.warning)
    assert tuple(at.sidebar.radio[0].options) == SEMPRE


def test_demonstracao_e_troca_de_livro():
    at = abrir()
    at.button(key="demo_fm").click().run()
    assert at.session_state.livro["sistema"] == "fm"
    assert at.title[0].value == "Gerador de fichas · Feiticeiros & Maldições"
    at.sidebar.button[0].click().run()  # "Trocar de livro"
    assert "livro" not in at.session_state
    assert tuple(at.sidebar.radio[0].options) == SEMPRE


# --------------------------------------------------------------------------- D&D 5e


@pytest.mark.parametrize("pagina", COM_LIVRO)
@pytest.mark.parametrize("sistema", ["dnd5e", "fm"])
def test_paginas_renderizam_em_cada_sistema(sistema, pagina):
    ir(abrir(sistema), pagina)


def test_ficha_rapida_dnd_calcula_e_valida():
    at = ir(abrir("dnd5e"), "Ficha rápida")
    pv = next(m for m in at.metric if m.label == "PV máximo")
    assert pv.value == "11"  # guerreiro nível 1, CON 13
    assert at.success  # conjunto 15/14/13/12/10/8 custa exatamente 27 pontos
    at.number_input(key="attr_car").set_value(15).run()  # estoura o orçamento
    assert at.error


def test_gerador_dnd_gera_e_regera():
    at = ir(abrir("dnd5e"), "Gerador de fichas")
    assert not at.error  # a ficha gerada é válida
    titulo = at.subheader[0].value
    at.button[0].click().run()  # "Gerar outra"
    assert not at.exception
    assert at.subheader[0].value != titulo or at.session_state.semente == 2


def test_analises_dnd_grupo_e_encontro():
    at = ir(abrir("dnd5e"), "Análises")
    assert at.dataframe  # tabela do grupo
    assert any(m.label == "Dificuldade oficial (XP)" for m in at.metric)
    at.multiselect[0].set_value(["Adult Red Dragon (CR 17)"]).run()
    assert not at.exception
    assert any("num único turno" in e.value for e in at.error)


# --------------------------------------------------------------------------- F&M


def test_fm_gerador_e_ficha_rapida():
    at = abrir("fm")  # com livro escolhido, a navegação começa no Início
    at = ir(at, "Gerador de fichas")
    assert not erros_de_ficha(at)
    assert any(m.label == "PV máximo" for m in at.metric)
    at = ir(at, "Ficha rápida")
    assert any("Ficha válida" in s.value for s in at.success)
    at.selectbox(key="fm_r_classe").set_value("Restringido").run()
    assert any("exige a origem Restringido" in e.value for e in at.error)


def test_fm_analises():
    at = ir(abrir("fm"), "Análises")
    assert at.dataframe
    assert any("Ninguém cura" in e.value for e in at.error)  # grupo padrão não tem Suporte
    assert any("não tem bestiário" in i.value for i in at.info)


def test_bastidores_mostra_a_comparacao_dos_llms():
    at = ir(abrir(), "Bastidores do leitor")
    assert at.dataframe
