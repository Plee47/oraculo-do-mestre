"""Smoke tests do site: o fluxo começa pelo livro, e as ferramentas seguem o sistema validado."""

import json
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app" / "streamlit_app.py")
# Trecho de RPG genérico (sem as classes do D&D): vai para a leitura com IA.
TRECHO_RPG = (
    "Armor Class 14, Hit Points 27 (5d8 + 5). STR 15 (+2) DEX 14 (+2). The target must "
    "succeed on a DC 12 saving throw. Your character adds the proficiency bonus. "
) * 4
# Com as classes e termos da 5ª edição: regras prontas de D&D 5e.
TRECHO_DND = (
    TRECHO_RPG
    + (
        "Barbarian, Bard, Cleric, Druid, Fighter, Monk, Paladin, Ranger, Rogue, Wizard. "
        "Use a bonus action after a short rest. "
    )
    * 2
)
SEMPRE = ("Início", "Bastidores do leitor", "Roteiro", "Conteúdo e licenças")
COM_LIVRO = ("Resumo do sistema", "Gerador de fichas", "Ficha rápida", "Análises")

SISTEMA_2D8 = {
    "nome": "Ninjas 2d8",
    "resumo": "Um RPG de ninjas com testes de 2d8.",
    "mecanica": {
        "dado_base": "2d8",
        "resolucao": "2d8 + precisão contra a dificuldade.",
        "dano_basico": "teto(Força/2) + 1",
        "multiplicador_dano_medio": 2,
    },
    "niveis": {"usa_niveis": True, "nivel_inicial": 4, "variavel": "nc"},
    "atributos": [
        {"id": i, "nome": n, "sigla": i.upper(), "minimo": 0, "maximo": 4}
        for i, n in (("for", "Força"), ("agi", "Agilidade"), ("vig", "Vigor"), ("esp", "Espírito"))
    ],
    "geracao": {
        "metodo": "pontos",
        "pontos": 8,
        "valor_inicial": 0,
        "explicacao": "8 pontos entre os atributos.",
    },
    "derivados": [
        {"nome": "Vitalidade", "formula": "10 + 3*vig + 5*nc"},
        {"nome": "Chakra", "formula": "10 + 3*esp"},
    ],
    "arquetipos": [
        {"nome": "Clã da Folha", "papel": "combate", "atributos_chave": ["for"]},
        {"nome": "Clã da Névoa", "papel": "suporte", "atributos_chave": ["esp"]},
    ],
    "criaturas": [{"nome": "Lobo", "vida": 20, "ataques": [{"nome": "Mordida", "dano": "1d6"}]}],
}


ETAPAS_2D8 = [
    {
        "id": "cla",
        "nome": "Clã",
        "tipo": "escolha",
        "principal": True,
        "opcoes": [
            {"nome": "Clã da Folha", "atributos_chave": ["for"], "papel": "combate", "pagina": 1},
            {"nome": "Clã da Névoa", "atributos_chave": ["esp"], "papel": "suporte", "pagina": 1},
        ],
    },
    {
        "id": "estilo",
        "nome": "Estilo",
        "tipo": "escolha",
        "depende_de": "cla",
        "opcoes": [
            {"nome": "Punho Leve", "pai": "Clã da Folha"},
            {"nome": "Bruma Densa", "pai": "Clã da Névoa"},
        ],
    },
]
DETALHE = {
    "descricao": "Clã de guerreiros.",
    "equipamento": ["Kunai"],
    "habilidades": [{"nome": "Golpe da Folha", "resumo": "Dano extra.", "nivel": 1, "pagina": 1}],
}


class LLMFalso:
    """Responde como o LLM do Databricks, sem rede (usado só nos testes)."""

    def completar(self, sistema: str, usuario: str, max_tokens: int = 6000) -> str:
        if "ESTRUTURA" in usuario:
            return json.dumps({"nome_arquetipo": "clã", "etapas": ETAPAS_2D8})
        if "da decisão" in usuario:
            return json.dumps(DETALHE)
        if "Trechos do início" in usuario:
            return json.dumps(
                {
                    "e_livro_de_rpg": True,
                    **{k: SISTEMA_2D8[k] for k in ("nome", "resumo", "mecanica")},
                }
            )
        if "criação de personagem" in usuario:
            return json.dumps(
                {
                    k: SISTEMA_2D8[k]
                    for k in ("atributos", "geracao", "derivados", "arquetipos", "niveis")
                }
            )
        return json.dumps({"criaturas": SISTEMA_2D8["criaturas"]})


def abrir(sistema: str | None = None, llm: object | None = None) -> AppTest:
    """Abre o site; com `sistema`, já com um livro validado ("lido" usa SISTEMA_2D8)."""
    at = AppTest.from_file(APP, default_timeout=60)
    if sistema:
        livro = {"sistema": sistema, "nome": "demo", "nota": None, "demo": True}
        if sistema == "lido":
            livro["lido"] = SISTEMA_2D8
        at.session_state["livro"] = livro
    if llm is not None:
        at.session_state["_cliente_llm_teste"] = llm
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


def test_livro_de_dnd_usa_as_regras_prontas():
    at = abrir()
    at.text_area[0].set_value(TRECHO_DND).run()
    assert any("Livro aceito pelo porteiro" in s.value for s in at.success)
    at.button[0].click().run()  # "Usar as regras prontas de D&D 5e"
    assert not at.exception
    assert at.session_state.livro["sistema"] == "dnd5e"
    assert at.session_state.pagina == "Resumo do sistema"
    assert set(COM_LIVRO) <= set(at.sidebar.radio[0].options)
    assert at.title[0].value == "Resumo do sistema · D&D 5e"
    ir(at, "Gerador de fichas")
    assert at.title[0].value == "Gerador de fichas · D&D 5e"


def test_texto_que_nao_e_rpg_nao_libera_nada():
    at = abrir()
    at.text_area[0].set_value("The old knight walked home and she said goodbye. " * 30).run()
    assert any("Não parece um livro de RPG" in i.value for i in at.info)
    assert not [b for b in at.button if "Ler o livro" in b.label]
    assert tuple(at.sidebar.radio[0].options) == SEMPRE


def test_qualquer_rpg_e_lido_pela_ia_e_libera_as_ferramentas():
    at = abrir(llm=LLMFalso())
    at.text_area[0].set_value(TRECHO_RPG).run()
    botao = next(b for b in at.button if b.label == "Ler o livro com IA e montar o sistema")
    botao.click().run()
    assert not at.exception
    assert at.session_state.livro["sistema"] == "lido"
    assert at.title[0].value == "Resumo do sistema · Ninjas 2d8"
    assert any(m.label == "Dado base" and m.value == "2d8" for m in at.metric)
    for pagina in ("Gerador de fichas", "Ficha rápida", "Análises"):
        ir(at, pagina)
        assert not erros_de_ficha(at)
    assert at.title[0].value == "Análises · Ninjas 2d8"
    assert any(m.label == "Balanço estimado" for m in at.metric)


def test_livro_ja_lido_vem_do_cache_sem_gastar_llm():
    # Importa aqui: o job "só requirements.txt" prova que o site acha o código sozinho, sem o pacote
    # instalado, então este arquivo não pode depender dele logo ao ser carregado.
    sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
    from oraculo.leitor.cache import CacheMemoria
    from oraculo.sistemas.generico.leitura import ler_sistema

    class LLMProibido:
        def completar(self, *a, **k):
            raise AssertionError("não devia chamar o LLM")

    cache = CacheMemoria()
    ler_sistema([TRECHO_RPG], LLMFalso(), cache=cache)  # alguém já leu este livro
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["_cliente_llm_teste"] = LLMProibido()
    at.session_state["_cache_teste"] = cache
    at.run()
    at.text_area[0].set_value(TRECHO_RPG).run()
    next(b for b in at.button if b.label.startswith("Ler o livro")).click().run()
    assert not at.exception
    assert at.title[0].value == "Resumo do sistema · Ninjas 2d8"


def test_ficha_por_etapas_com_leitura_a_fundo():
    at = abrir(llm=LLMFalso())
    at.text_area[0].set_value(TRECHO_RPG).run()
    next(b for b in at.button if b.label.startswith("Ler o livro")).click().run()
    ir(at, "Gerador de fichas")
    at.selectbox(key="lido_etapa_cla").set_value("Clã da Folha").run()
    assert not at.exception
    # a etapa filha só oferece as opções do clã escolhido
    assert at.selectbox(key="lido_etapa_estilo").options == ["Automático", "Punho Leve"]
    assert "Clã da Folha" in at.subheader[0].value
    # a leitura a fundo entrou na ficha e ficou guardada no livro da sessão
    opcoes = at.session_state.livro["lido"]["etapas"][0]["opcoes"]
    assert next(o for o in opcoes if o["nome"] == "Clã da Folha")["detalhada"]
    assert at.dataframe  # tabela de habilidades do nível
    assert any("Kunai" in m.value for m in at.markdown)
    assert not [e for e in at.error]


@pytest.mark.parametrize("sistema", ["dnd5e", "fm", "lido"])
def test_sugestao_criativa_em_qualquer_sistema(sistema):
    class LLMCriativo:
        def completar(self, sistema, usuario, max_tokens=6000, pequeno=False):
            assert pequeno
            return json.dumps({"aparencia": "Alta e calada.", "assinatura_nome": "Corte Duplo"})

    at = ir(abrir(sistema, llm=LLMCriativo()), "Gerador de fichas")
    next(b for b in at.button if b.label.startswith("Sugerir aparência")).click().run()
    assert not at.exception
    assert any("Alta e calada." in m.value for m in at.markdown)
    assert any("Sugestão criativa" in c.value for c in at.caption)


def test_sem_credencial_a_leitura_explica_o_motivo(monkeypatch):
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    at = abrir()
    at.text_area[0].set_value(TRECHO_RPG).run()
    next(b for b in at.button if b.label.startswith("Ler o livro")).click().run()
    assert any("não está configurada" in e.value for e in at.error)
    assert "livro" not in at.session_state


def test_demonstracao_e_troca_de_livro():
    at = abrir()
    at.button(key="demo_fm").click().run()
    assert at.session_state.livro["sistema"] == "fm"
    assert at.title[0].value == "Resumo do sistema · Feiticeiros & Maldições"
    at.sidebar.button[0].click().run()  # "Trocar de livro"
    assert "livro" not in at.session_state
    assert tuple(at.sidebar.radio[0].options) == SEMPRE


# --------------------------------------------------------------------------- D&D 5e


@pytest.mark.parametrize("pagina", COM_LIVRO)
@pytest.mark.parametrize("sistema", ["dnd5e", "fm", "lido"])
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


@pytest.mark.parametrize("sistema", ["dnd5e", "fm", "lido"])
def test_ficha_oferece_pdf_em_qualquer_sistema(sistema):
    at = ir(abrir(sistema), "Gerador de fichas")
    rotulos = [b.proto.label for b in at.get("download_button")]
    assert "Baixar ficha em PDF" in rotulos and "Baixar em JSON" in rotulos


def test_bastidores_mostra_a_comparacao_das_buscas():
    at = ir(abrir(), "Bastidores do leitor")
    assert len(at.dataframe) == 2
    assert any("páginas certas" in s.value for s in at.subheader)
