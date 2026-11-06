"""Ficha em PDF: conteúdo legível, temas por gênero e textos difíceis."""

import io

import pytest
from pypdf import PdfReader

from oraculo.fichas_pdf import (
    TEMAS,
    FichaImpressa,
    ValorImpresso,
    gerar_pdf,
    tema_para,
    texto_seguro,
)
from oraculo.sistemas.generico.gerador import gerar_ficha
from oraculo.sistemas.generico.impressao import ficha_impressa, tema_do_sistema
from oraculo.sistemas.generico.modelo import SistemaLido, normalizar


def _texto(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def _ficha(**k) -> FichaImpressa:
    base = dict(
        nome="Iara Çaçula",
        sistema="Jogo de Testes",
        subtitulo="Clã da Névoa · Nível 4",
        atributos=[("FOR", 15, 2), ("DES", 12, 1), ("VON", 8, -1)],
        valores=[ValorImpresso("Vitalidade", "39", anotar=True), ValorImpresso("Defesa", "14")],
        secoes=[("Perícias", ["Acrobacia, Furtividade"]), ("Vazia", [])],
        narrativa={"Aparência": "Alta, com cicatrizes."},
        credito="Regras do Jogo de Testes",
    )
    return FichaImpressa(**{**base, **k})


@pytest.mark.parametrize("tema", list(TEMAS))
def test_pdf_tem_tudo_em_qualquer_tema(tema):
    pdf = gerar_pdf(_ficha(), TEMAS[tema])
    assert pdf.startswith(b"%PDF")
    texto = _texto(pdf)
    for trecho in (
        "Iara Çaçula",
        "Clã da Névoa",
        "FOR",
        "15",
        "+2",
        "-1",
        "Vitalidade",
        "39",
        "Atual",
        "Acrobacia",
        "Alta, com cicatrizes.",
        "Anotações",
        "Regras do Jogo de Testes",
    ):
        assert trecho in texto, (tema, trecho)
    assert "Vazia" not in texto  # seção sem conteúdo não aparece


def test_temas_mudam_conforme_o_genero():
    assert tema_para("horror cósmico").id == "horror"
    assert tema_para("fantasia ninja").id == "oriental"  # ninja vem antes de fantasia
    assert tema_para("fantasia épica").id == "fantasia"
    assert tema_para("Vampiro: A Máscara").id == "gotico"
    assert tema_para("ficção científica").id == "scifi"
    assert tema_para("comédia de escritório").id == "padrao"


def test_caracteres_fora_da_fonte_nao_quebram():
    assert texto_seguro("a → b — c “d” ≥ 3") == 'a -> b - c "d" >= 3'
    assert texto_seguro("ação ñ ç") == "ação ñ ç"
    assert texto_seguro("日本") == "??"
    pdf = gerar_pdf(
        _ficha(nome="日本 → Nome", secoes=[("Título — 🎲", ["x " * 50])]), TEMAS["padrao"]
    )
    assert pdf.startswith(b"%PDF")


def test_ficha_longa_vira_mais_paginas_sem_perder_conteudo():
    linhas = [f"Habilidade {i}: efeito longo " + "palavra " * 30 for i in range(60)]
    pdf = gerar_pdf(_ficha(secoes=[("Habilidades", linhas)]), TEMAS["fantasia"])
    assert len(PdfReader(io.BytesIO(pdf)).pages) >= 2
    assert "Habilidade 59" in _texto(pdf)


def test_muitos_atributos_e_nomes_longos_cabem():
    atributos = [(f"ATRIB{i}", i, None) for i in range(14)]
    valores = [ValorImpresso("Nome de um valor derivado bem comprido " * 3, "1") for _ in range(9)]
    pdf = gerar_pdf(_ficha(atributos=atributos, valores=valores), TEMAS["scifi"])
    assert "ATRIB13" in _texto(pdf)


def test_ficha_de_sistema_lido():
    s = normalizar(SistemaLido.model_validate({
        "nome": "Horror d100",
        "genero": "horror cósmico",
        "autores": "Fulana",
        "mecanica": {"resolucao": "Role abaixo do valor."},
        "modificador": "piso((valor-10)/2)",
        "niveis": {"usa_niveis": True, "nivel_inicial": 2, "nome": "Rank"},
        "atributos": [{"id": "pod", "nome": "Poder", "sigla": "POD", "rolagem": "3d6*5"}],
        "derivados": [{"nome": "Sanidade", "formula": "pod"}, {"nome": "Sorte", "formula": ""}],
        "etapas": [{"id": "ocup", "nome": "Ocupação", "tipo": "escolha", "principal": True,
                    "opcoes": [{"nome": "Detetive", "habilidades_detalhe": [
                        {"nome": "Faro", "resumo": "Acha pistas.", "nivel": 1, "pagina": 12},
                        {"nome": "Golpe Final", "resumo": "Depois.", "nivel": 9},
                    ], "pericias": ["Investigar"], "equipamento": ["Lupa"]}]}],
    }))  # fmt: skip
    f = gerar_ficha(s, seed=1)
    impressa = ficha_impressa(s, f)
    assert tema_do_sistema(s).id == "horror"
    assert impressa.subtitulo == "Detetive · Rank 2"
    assert impressa.credito == "Regras de Horror d100 (Fulana)"
    assert [v.anotar for v in impressa.valores] == [True]  # Sanidade; Sorte sem fórmula sai
    texto = _texto(gerar_pdf(impressa, tema_do_sistema(s)))
    for trecho in ("Faro: Acha pistas. (p. 12)", "Investigar", "Lupa", "Role abaixo", "Sanidade"):
        assert trecho in texto
    assert "Golpe Final" not in texto  # habilidade de nível acima do personagem
