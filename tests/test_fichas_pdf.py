"""Ficha em PDF: conteúdo legível, temas por gênero e textos difíceis."""

import io

import pytest
from pypdf import PdfReader

from oraculo.fichas_pdf import (
    TEMAS,
    BlocoImpresso,
    FichaImpressa,
    ValorImpresso,
    atributo_em_branco,
    gerar_pdf,
    tema_para,
    texto_seguro,
)
from oraculo.sistemas.generico.gerador import gerar_ficha
from oraculo.sistemas.generico.impressao import (
    ficha_em_branco,
    ficha_impressa,
    formula_legivel,
    tema_do_sistema,
)
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
    assert texto_seguro("10\u202fm e 2\u2009m") == "10 m e 2 m"  # espaços Unicode do LLM
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
    # Sorte não tem fórmula: fica com o espaço para o jogador preencher.
    assert [v.nome for v in impressa.valores] == ["Sanidade", "Sorte"]
    assert impressa.valores[0].valor and impressa.valores[1].valor == ""
    texto = _texto(gerar_pdf(impressa, tema_do_sistema(s)))
    for trecho in ("Faro: Acha pistas. (p. 12)", "Investigar", "Lupa", "Role abaixo", "Sanidade"):
        assert trecho in texto
    assert "Golpe Final" not in texto  # habilidade de nível acima do personagem


def test_secao_so_com_linha_vazia_nao_aparece():
    # A ficha rápida não tem perícias nem poderes: "".join([]) não pode virar um título solto.
    assert "Sem nada" not in _texto(
        gerar_pdf(_ficha(secoes=[("Sem nada", ["", " "])]), TEMAS["padrao"])
    )


def test_carimbo_do_dossie_fica_so_na_primeira_pagina():
    linhas = [f"Habilidade {i}: " + "palavra " * 40 for i in range(60)]
    paginas = PdfReader(
        io.BytesIO(gerar_pdf(_ficha(secoes=[("H", linhas)]), TEMAS["horror"]))
    ).pages
    assert len(paginas) >= 2
    assert "FICHA" in paginas[0].extract_text()
    assert "FICHA" not in paginas[1].extract_text()


@pytest.mark.parametrize("tema", list(TEMAS))
def test_ficha_em_branco_tem_espaco_para_escrever_em_qualquer_tema(tema):
    branca = FichaImpressa(
        nome="",
        sistema="Jogo de Testes",
        subtitulo="Ficha em branco",
        atributos=[atributo_em_branco("FOR", True), atributo_em_branco("DES", True)],
        valores=[ValorImpresso("Vitalidade", anotar=True), ValorImpresso("Defesa")],
        campos=["Nome", "Jogador", "Clã"],
        blocos=[BlocoImpresso("Equipamento", linhas=4)],
    )
    texto = _texto(gerar_pdf(branca, TEMAS[tema]))
    for trecho in ("Jogo de Testes", "Ficha em branco", "Jogador", "Clã", "FOR", "Vitalidade",
                   "Máximo", "Atual", "Equipamento", "Anotações"):  # fmt: skip
        assert trecho in texto, (tema, trecho)


def test_ficha_em_branco_de_sistema_lido_usa_o_que_o_livro_diz():
    s = normalizar(SistemaLido.model_validate({
        "nome": "Horror d100",
        "genero": "horror cósmico",
        "mecanica": {"resolucao": "Role abaixo do valor."},
        "modificador": "piso((valor-10)/2)",
        "niveis": {"usa_niveis": True, "nome": "Rank"},
        "atributos": [{"id": "pod", "nome": "Poder", "sigla": "POD"}],
        "derivados": [
            {"nome": "Sanidade", "formula": "pod", "tipo": "vida"},
            {"nome": "Sorte", "formula": "", "explicacao": "Role 3d6 e multiplique por 5."},
        ],
        "etapas": [{"id": "ocup", "nome": "Ocupação", "tipo": "escolha", "principal": True,
                    "opcoes": [{"nome": "Detetive", "pagina": 12}, {"nome": "Médica"}]}],
    }))  # fmt: skip
    branca = ficha_em_branco(s)
    assert branca.campos == ["Nome", "Jogador", "Ocupação", "Rank"]
    assert [b.titulo for b in branca.blocos][:2] == ["Perícias", "Habilidades e poderes"]
    assert branca.atributos == [("POD", None, 0)]
    assert [(v.nome, v.valor, v.anotar) for v in branca.valores] == [
        ("Sanidade", "", True),
        ("Sorte", "", True),  # sem fórmula, mas é um campo que a ficha do livro tem
    ]
    texto = _texto(gerar_pdf(branca, tema_do_sistema(s)))
    for trecho in ("Sanidade: Poder", "Sorte: Role 3d6", "Modificador de atributo",
                   "Ocupação: Detetive (p. 12), Médica", "Role abaixo do valor"):  # fmt: skip
        assert trecho in texto, trecho


def test_ficha_em_branco_sem_etapas_nem_modificador():
    s = normalizar(SistemaLido.model_validate({
        "nome": "Simples",
        "nome_arquetipo": "clã",
        "atributos": [{"id": "forca", "nome": "Força"}],
        "arquetipos": [{"nome": "Lobo"}],
    }))  # fmt: skip
    branca = ficha_em_branco(s)
    assert "Clã" in branca.campos
    assert branca.atributos == [("Força", None, None)]
    assert gerar_pdf(branca, tema_do_sistema(s)).startswith(b"%PDF")


def _campos(pdf: bytes) -> dict:
    return PdfReader(io.BytesIO(pdf)).get_fields() or {}


@pytest.mark.parametrize("tema", list(TEMAS))
def test_ficha_em_branco_se_preenche_no_leitor_de_pdf(tema):
    branca = FichaImpressa(
        nome="",
        sistema="Jogo",
        atributos=[atributo_em_branco("FOR", True)],
        valores=[ValorImpresso("Vitalidade", anotar=True), ValorImpresso("Defesa")],
        campos=["Nome", "Clã"],
        blocos=[
            BlocoImpresso("Resistências", "valores", [ValorImpresso("Fortitude")]),
            BlocoImpresso("Perícias", "marcas", [ValorImpresso("Atletismo")]),
            BlocoImpresso("Técnica", itens=[ValorImpresso("Descrição da Técnica")], linhas=2),
            BlocoImpresso("Equipamento", linhas=4),
        ],
    )
    campos = _campos(gerar_pdf(branca, TEMAS[tema]))
    for nome in ("Nome", "Clã", "FOR", "mod FOR", "Vitalidade Máximo", "Vitalidade Atual", "Defesa",
                 "Fortitude", "Atletismo", "Atletismo bônus", "Técnica Descrição da Técnica",
                 "Equipamento", "Anotações"):  # fmt: skip
        assert nome in campos, nome
    assert campos["Atletismo"]["/FT"] == "/Btn"
    assert campos["Equipamento"]["/FT"] == "/Tx"


def test_ficha_gerada_deixa_digitar_so_o_que_muda_em_jogo():
    campos = _campos(gerar_pdf(_ficha(), TEMAS["padrao"]))
    assert "Vitalidade Atual" in campos and "Anotações" in campos
    assert "FOR" not in campos and "Defesa" not in campos  # já vêm impressos


def test_campos_de_mesmo_nome_nao_colidem():
    blocos = [BlocoImpresso("Notas", linhas=2), BlocoImpresso("Notas", linhas=2)]
    assert {"Notas", "Notas 2"} <= set(_campos(gerar_pdf(_ficha(blocos=blocos), TEMAS["scifi"])))


def test_pericia_treinada_vem_marcada():
    s = normalizar(SistemaLido.model_validate({
        "nome": "Jogo", "atributos": [{"id": "for", "nome": "Força"}],
        "pericias": [{"nome": "Atletismo"}, {"nome": "Furtividade"}],
    }))  # fmt: skip
    f = gerar_ficha(s, seed=1).model_copy(update={"pericias": ["Atletismo", "Pilotar"]})
    campos = _campos(gerar_pdf(ficha_impressa(s, f), tema_do_sistema(s)))
    assert campos["Atletismo"]["/V"] == "/Sim"
    assert campos["Furtividade"]["/V"] == "/Off"
    assert campos["Pilotar"]["/V"] == "/Sim"  # concedida pela opção, fora da lista lida


def test_ficha_usa_as_partes_que_o_livro_descreve():
    s = normalizar(SistemaLido.model_validate({
        "nome": "Jogo",
        "atributos": [{"id": "for", "nome": "Força"}],
        "ficha": [
            {"titulo": "Testes de Resistência", "tipo": "valores", "itens": ["Fortitude"]},
            {"titulo": "Pontos Temporários", "tipo": "contadores", "itens": ["Vida Temporária"]},
            {"titulo": "Perfil Amaldiçoado", "tipo": "texto", "itens": ["Técnica"]},
        ],
    }))  # fmt: skip
    for impressa in (ficha_em_branco(s), ficha_impressa(s, gerar_ficha(s, seed=1))):
        pdf = gerar_pdf(impressa, tema_do_sistema(s))
        texto = _texto(pdf)
        for trecho in ("Testes de Resistência", "Perfil Amaldiçoado", "Vida Temporária", "Técnica"):
            assert trecho in texto
        assert "Vida Temporária Atual" in _campos(pdf)


def test_formula_legivel_usa_os_nomes_do_livro():
    s = normalizar(SistemaLido.model_validate({
        "nome": "Jogo",
        "niveis": {"usa_niveis": True, "nome": "Rank", "variavel": "nc"},
        "atributos": [{"id": "des", "nome": "Destreza"}, {"id": "vig", "nome": "Vigor"}],
    }))  # fmt: skip
    assert formula_legivel(s, "10 + mod_des + 0") == "10 + modificador de Destreza"
    assert formula_legivel(s, "3*vig + 5*nc") == "3 x Vigor + 5 x Rank"
    assert formula_legivel(s, "mod_destreza") == "modificador de Destreza"
    assert formula_legivel(s, "piso((valor-10)/2)") == "(valor-10)/2, arredondado para baixo"
    assert formula_legivel(s, "teto(nc/2)") == "Rank/2, arredondado para cima"


def test_ficha_gerada_deixa_espaco_para_o_que_ainda_nao_tem():
    s = normalizar(SistemaLido.model_validate({
        "nome": "Jogo", "atributos": [{"id": "for", "nome": "Força"}],
    }))  # fmt: skip
    f = gerar_ficha(s, seed=1).model_copy(update={"equipamento": ["Lupa"], "poderes": []})
    titulos = [b.titulo for b in ficha_impressa(s, f).blocos]
    assert "Habilidades e poderes" in titulos and "Aparência e história" in titulos
    assert "Equipamento" not in titulos  # já vem preenchido, numa seção impressa
