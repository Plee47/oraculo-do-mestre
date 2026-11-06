from pathlib import Path

from oraculo.dicas import Termo, resumir, termos_html
from oraculo.sistemas.dnd5e.catalogo import Catalogo, Magia
from oraculo.sistemas.dnd5e.dicas import (
    _ATRIBUTOS,
    _DANOS,
    _ESCOLAS,
    termo_magia,
    termo_pericia,
    titulo_magia,
)
from oraculo.sistemas.generico.gerador import dicas_da_ficha, gerar_ficha
from oraculo.sistemas.generico.leitura import _aplicar_detalhes
from oraculo.sistemas.generico.modelo import (
    Etapa,
    Habilidade,
    Opcao,
    Pericia,
    SistemaLido,
)

CATALOGO = Path(__file__).parents[1] / "dados" / "publicos" / "dnd5e" / "catalogo.json"


def _sistema() -> SistemaLido:
    return SistemaLido(
        nome="Teste",
        pericias=[Pericia(nome="Furtividade", descricao="Mover-se sem ser notado.")],
        etapas=[
            Etapa(
                id="classe",
                nome="Classe",
                tipo="escolha",
                opcoes=[
                    Opcao(
                        nome="Mago",
                        habilidades=["Golpe"],
                        habilidades_detalhe=[
                            Habilidade(nome="Golpe", resumo="Bate forte.", nivel=3, pagina=47)
                        ],
                        poderes=["Raio de Gelo"],
                        poderes_detalhe=[Habilidade(nome="Raio de Gelo", resumo="Congela o alvo.")],
                    )
                ],
            )
        ],
    )


def test_termo_sem_explicacao_fica_como_texto_comum():
    saida = termos_html([Termo("Golpe")])
    assert "Golpe" in saida
    assert "termo" not in saida.replace("termos", "")
    assert "tabindex" not in saida


def test_termo_com_explicacao_recebe_foco_pelo_teclado():
    saida = termos_html([Termo("Golpe", "Bate forte.", "Básico")], "Truques")
    assert 'class="termo" tabindex="0"' in saida
    assert 'role="tooltip"' in saida
    assert "<strong>Truques:</strong>" in saida
    assert '<span class="dica-titulo">Básico</span>' in saida


def test_texto_vindo_do_livro_e_escapado():
    saida = termos_html([Termo("<img src=x>", '<script>alert("x")</script>', "<b>")])
    assert "<script" not in saida
    assert "<img" not in saida
    assert "<b>" not in saida


def test_resumir_corta_em_fim_de_frase():
    assert resumir("Primeira frase. Segunda frase bem longa.", 20) == "Primeira frase."


def test_resumir_sem_fim_de_frase_marca_o_corte():
    saida = resumir("palavra " * 20, 30)
    assert len(saida) <= 31
    assert saida.endswith("…")


def test_resumir_tira_tabela_e_markdown():
    assert (
        resumir("***Cone.*** Um cone.\n| d4 | Efeito |\n|---|---|\n### Fim") == "Cone. Um cone. Fim"
    )


def test_titulo_da_magia_em_portugues():
    m = Magia(
        id="x", nome="X", circulo=3, escola="evocation", classes=[], tipo_dano="fire", dano="8d6",
        resistencia="des", area=True, concentracao=True,
    )  # fmt: skip
    assert titulo_magia(m) == (
        "Evocação · 3º círculo · 8d6 de fogo · resistência de Destreza · em área · concentração"
    )


def test_truque_e_escola_desconhecida():
    m = Magia(id="x", nome="X", circulo=0, escola="nova", classes=[])
    assert titulo_magia(m) == "Nova · truque"


def test_todo_o_catalogo_tem_explicacao():
    cat = Catalogo.carregar(CATALOGO)
    assert all(termo_magia(m).dica for m in cat.magias)
    assert all(termo_pericia(p).dica for p in cat.pericias)
    assert all(len(termo_magia(m).dica) <= 381 for m in cat.magias)
    # Nenhuma escola, tipo de dano ou atributo ficou sem tradução.
    assert {m.escola for m in cat.magias} <= set(_ESCOLAS)
    assert {m.tipo_dano for m in cat.magias if m.tipo_dano} <= set(_DANOS)
    assert {m.resistencia for m in cat.magias if m.resistencia} <= set(_ATRIBUTOS)


def test_dicas_da_ficha_juntam_habilidade_poder_e_pericia():
    s = _sistema()
    ficha = gerar_ficha(s, seed=1, escolhas={"classe": "Mago"})
    dicas = dicas_da_ficha(s, ficha)
    assert dicas["golpe"].startswith("Bate forte.")
    assert "47" in dicas["golpe"]
    assert dicas["raio_de_gelo"] == "Congela o alvo."
    assert dicas["furtividade"] == "Mover-se sem ser notado."


def test_leitura_guarda_o_resumo_do_poder_e_aceita_so_o_nome():
    s = _sistema()
    etapa = s.etapas[0]
    o = etapa.opcoes[0]
    _aplicar_detalhes(
        s,
        etapa,
        o,
        {"poderes": [{"nome": "Bola de Fogo", "resumo": "Explode.", "pagina": 9}, "Luz"]},
    )
    assert o.poderes == ["Bola de Fogo", "Luz"]
    assert o.poderes_detalhe[0].resumo == "Explode."
    assert o.poderes_detalhe[1].resumo == ""
