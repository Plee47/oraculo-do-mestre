"""Busca nas páginas (BM25, híbrida), cache das leituras e avaliação contra o gabarito do SRD."""

import json
import urllib.error
from pathlib import Path

import pytest

from oraculo.leitor.avaliacao_generica import SUBCLASSES_SRD, avaliar_leitura
from oraculo.leitor.cache import CacheDatabricks, CacheMemoria, hash_livro
from oraculo.leitor.indice import IndiceLivro, texto_para_vetores, tokens, vetores_para_texto
from oraculo.leitor.llm import ClienteDatabricks, ErroLLM, cliente_configurado, espera
from oraculo.sistemas.dnd5e.catalogo import Catalogo
from oraculo.sistemas.generico.leitura import leitura_guardada, ler_sistema, selecionar_por_busca
from oraculo.sistemas.generico.modelo import SistemaLido

CATALOGO = Path(__file__).parents[1] / "dados" / "publicos" / "dnd5e" / "catalogo.json"
ENCHIMENTO = "texto corrido de ambientação sem nada de especial " * 20


def _paginas() -> list[str]:
    paginas = [f"Página {i}. {ENCHIMENTO}" for i in range(30)]
    paginas[5] = "Criação de personagem: distribua os pontos nos atributos e escolha a classe. " * 8
    paginas[6] = "Continuação: pontos de vida iniciais e nível inicial. " + ENCHIMENTO
    paginas[12] = "Teste: role os dados, some a dificuldade e veja o sucesso ou a falha. " * 8
    paginas[20] = "Bestiário: criaturas, monstros, inimigos, ataque e pontos de vida. " * 8
    return paginas


# --------------------------------------------------------------------------- índice


def test_tokens_ignoram_acento_caixa_e_palavras_vazias():
    assert tokens("A Criação de Força!") == ["criacao", "forca"]


def test_bm25_acha_a_pagina_do_assunto():
    indice = IndiceLivro(_paginas())
    assert indice.buscar("bestiário criaturas monstros", k=1) == [20]
    assert indice.buscar("criação de personagem atributos", k=1) == [5]
    assert indice.buscar("palavra_que_nao_existe", k=3) == []


def test_busca_hibrida_usa_os_vetores():
    paginas = _paginas()
    vetores = [[1.0, 0.0] for _ in paginas]
    vetores[9] = [0.0, 1.0]  # sem nenhuma palavra da consulta, mas com o sentido certo
    indice = IndiceLivro(paginas, vetores)
    assert indice.tem_vetores
    assert indice.buscar("bestiário", k=1, vetor_consulta=[0.0, 1.0], peso_semantico=0.9) == [9]
    assert indice.buscar("bestiário", k=1) == [20]  # sem vetor da consulta: só BM25


def test_vizinhas_respeitam_o_orcamento_e_a_ordem():
    indice = IndiceLivro(["x" * 100 for _ in range(10)])
    assert indice.com_vizinhas([5, 2], 1000) == [2, 3, 5, 6]
    assert indice.com_vizinhas([5, 2], 250) == [5, 6]
    assert indice.com_vizinhas([9], 1000) == [9]  # última página não tem seguinte


def test_vetores_ida_e_volta():
    vetores = [[0.5, -0.25, 1.0], [0.0, 0.125, -1.0]]
    assert texto_para_vetores(vetores_para_texto(vetores)) == vetores
    assert texto_para_vetores("") == [] and vetores_para_texto([]) == ""


def test_selecao_por_busca_cobre_as_partes():
    sel = selecionar_por_busca(IndiceLivro(_paginas()))
    assert 5 in sel["criacao"] and 6 in sel["criacao"]  # a página seguinte vem junto
    assert 12 in sel["visao"] and 20 in sel["criaturas"]


# --------------------------------------------------------------------------- cache


class LLMContador:
    def __init__(self):
        self.chamadas = 0
        self.embeddings = 0

    def completar(self, sistema, usuario, max_tokens=6000, pequeno=False):
        self.chamadas += 1
        if "Trechos do início" in usuario:
            return json.dumps({"e_livro_de_rpg": True, "nome": "Teste", "resumo": "Um RPG."})
        if "criação de personagem" in usuario:
            return json.dumps({"atributos": [{"nome": "Força"}]})
        return json.dumps({"criaturas": []})

    def embutir(self, textos):
        self.embeddings += 1
        return [[float(len(t) % 7), 1.0] for t in textos]


def test_livro_lido_uma_vez_nao_gasta_llm_de_novo():
    llm, cache = LLMContador(), CacheMemoria()
    primeira = ler_sistema(_paginas(), llm, cache=cache, estrategia="bm25")
    assert not primeira.do_cache and llm.chamadas == 4
    segunda = ler_sistema(_paginas(), llm, cache=cache, estrategia="bm25")
    assert segunda.do_cache and llm.chamadas == 4
    assert segunda.sistema == primeira.sistema
    assert leitura_guardada(_paginas(), cache, "bm25") is not None
    assert leitura_guardada(["outro livro"], cache, "bm25") is None


def test_vetores_ficam_no_cache():
    llm, cache = LLMContador(), CacheMemoria()
    ler_sistema(_paginas(), llm, cache=cache, estrategia="hibrida")
    assert llm.embeddings == 2  # páginas + consultas
    assert any(chave[1] == "vetores" for chave in cache.dados)
    cache.dados = {k: v for k, v in cache.dados.items() if k[1] == "vetores"}
    ler_sistema(_paginas(), llm, cache=cache, estrategia="hibrida")
    assert llm.embeddings == 3  # só as consultas: as páginas vieram do cache


def test_arquivo_que_nao_e_rpg_nao_fica_guardado():
    class NaoRpg(LLMContador):
        def completar(self, sistema, usuario, max_tokens=6000, pequeno=False):
            if "Trechos do início" in usuario:
                return json.dumps({"e_livro_de_rpg": False, "nome": "Manual"})
            return "{}"

    cache = CacheMemoria()
    assert not ler_sistema(_paginas(), NaoRpg(), cache=cache, estrategia="bm25").e_rpg
    assert not cache.dados


def test_hash_muda_com_o_texto():
    assert hash_livro(["a", "b"]) != hash_livro(["ab"])
    assert hash_livro(["a"]) == hash_livro(["a"])


class CacheFalso(CacheDatabricks):
    """Responde como a API SQL, sem rede; guarda as instruções para os testes olharem."""

    def __init__(self, respostas=None, erro=None):
        super().__init__("https://x", "t", warehouse_id="w")
        self.instrucoes = []
        self.respostas = respostas or []
        self.erro = erro

    def _api(self, metodo, caminho, corpo=None):
        if self.erro:
            raise self.erro
        self.instrucoes.append(corpo)
        linhas = self.respostas.pop(0) if self.respostas else []
        return {"status": {"state": "SUCCEEDED"}, "result": {"data_array": linhas}}


def test_cache_databricks_usa_parametros_e_cria_a_tabela():
    cache = CacheFalso(respostas=[[], [["conteudo guardado"]]])
    assert cache.ler("h'; DROP TABLE x", "sistema", "bm25", "v1") == "conteudo guardado"
    criar, selecionar = cache.instrucoes
    assert "CREATE TABLE IF NOT EXISTS" in criar["statement"]
    assert "DROP" not in selecionar["statement"]  # valor vai como parâmetro, nunca no SQL
    assert {"name": "livro", "value": "h'; DROP TABLE x", "type": "STRING"} in selecionar[
        "parameters"
    ]


def test_falha_no_cache_nao_derruba_a_leitura():
    cache = CacheFalso(erro=urllib.error.URLError("sem rede"))
    assert cache.ler("h", "sistema", "bm25", "v1") is None
    cache.gravar("h", "sistema", "bm25", "v1", "x")
    assert len(cache.avisos) == 2
    llm = LLMContador()
    assert ler_sistema(_paginas(), llm, cache=cache, estrategia="bm25").sistema.nome == "Teste"


def test_identificador_invalido_e_recusado():
    with pytest.raises(ValueError):
        CacheDatabricks("https://x", "t", catalogo="a; DROP")


# --------------------------------------------------------------------------- cliente


def test_cliente_configurado_pelos_segredos(monkeypatch):
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    assert cliente_configurado({}) is None
    c = cliente_configurado({"DATABRICKS_HOST": "dbc.exemplo", "DATABRICKS_TOKEN": "t"})
    assert isinstance(c, ClienteDatabricks) and c.host == "https://dbc.exemplo"


def test_embeddings_em_lotes_na_ordem_certa(monkeypatch):
    c = ClienteDatabricks("https://x", "t")
    lotes = []

    def falso(endpoint, corpo):
        lotes.append(len(corpo["input"]))
        dados = [{"index": i, "embedding": [float(i)]} for i in range(len(corpo["input"]))]
        return {"data": list(reversed(dados))}

    monkeypatch.setattr(c, "_post", falso)
    vetores = c.embutir(["a"] * 20)
    assert lotes == [16, 4] and len(vetores) == 20 and vetores[:2] == [[0.0], [1.0]]


# --------------------------------------------------------------------------- gabarito


@pytest.fixture(scope="module")
def gabarito() -> Catalogo:
    return Catalogo.carregar(CATALOGO)


def test_leitura_perfeita_tira_nota_maxima(gabarito):
    s = SistemaLido.model_validate(
        {
            "nome": "D&D",
            "mecanica": {"dado_base": "1d20"},
            "modificador": "piso((valor-10)/2)",
            "atributos": [
                {"nome": n}
                for n in (
                    "Strength",
                    "Dexterity",
                    "Constitution",
                    "Intelligence",
                    "Wisdom",
                    "Charisma",
                )
            ],
            "arquetipos": [{"nome": c.nome} for c in gabarito.classes],
            "etapas": [
                {"nome": "Raça", "opcoes": [{"nome": r.nome} for r in gabarito.racas]},
                {
                    "nome": "Subclasse",
                    "opcoes": [{"nome": sub, "pai": c} for sub, c in SUBCLASSES_SRD.items()],
                },
            ],
            "criaturas": [
                {"nome": m.nome, "vida": m.pv, "defesa": m.ca} for m in gabarito.monstros[:5]
            ],
        }
    )
    m = avaliar_leitura(s, gabarito)
    assert m["nota_geral"] == 1.0
    assert m["criaturas_lidas"] == 5
    assert m["subclasses_na_classe_certa"] == 1.0


def test_erros_derrubam_as_metricas_certas(gabarito):
    real = gabarito.monstros[0]
    s = SistemaLido.model_validate(
        {
            "nome": "D&D",
            "mecanica": {"dado_base": "2d8"},
            "atributos": [{"nome": "Força"}, {"nome": "Sorte"}],
            "arquetipos": [{"nome": "Guerreiro"}, {"nome": "Caçador de Dragões"}],
            "criaturas": [{"nome": real.nome, "vida": real.pv + 1}, {"nome": "Monstro Inventado"}],
        }
    )
    m = avaliar_leitura(s, gabarito)
    assert m["atributos_recall"] == pytest.approx(1 / 6) and m["atributos_precisao"] == 0.5
    assert m["classes_recall"] == pytest.approx(1 / 12) and m["classes_precisao"] == 0.5
    assert m["criaturas_precisao"] == 0.5 and m["criaturas_pv_acerto"] == 0.0
    assert m["mecanica_d20"] == 0.0 and m["modificador_certo"] == 0.0


def test_espera_e_mais_paciente_no_limite_de_cota():
    assert espera(429, 0) == 10 and espera(429, 2) == 40
    assert espera(429, 0, "30") == 30 and espera(429, 0, "9999") == 90
    assert espera(429, 0, "sem número") == 10
    assert espera(503, 0) == 2 and espera(None, 1) == 4


def test_sem_embeddings_a_leitura_segue_com_bm25():
    class SemEmbeddings(LLMContador):
        def embutir(self, textos):
            raise ErroLLM("limite")

    leitura = ler_sistema(_paginas(), SemEmbeddings(), estrategia="hibrida")
    assert leitura.sistema.nome == "Teste"
