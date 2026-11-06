"""Visual do livro: escolha do tema, CSS de cada tema e contraste das cores."""

import re
from pathlib import Path

import pytest

from oraculo.fichas_pdf import TEMAS
from oraculo.temas_site import (
    GRIMORIO,
    TEMAS_DO_SITE,
    cortina_html,
    css_do_tema,
    tema_do_site,
    tokens_do_tema,
)

PASTA = Path(__file__).parents[1] / "app" / "temas"
TODOS = [*TEMAS_DO_SITE, GRIMORIO]


def _luminancia(cor: str) -> float:
    r, g, b = (int(cor[i : i + 2], 16) / 255 for i in (1, 3, 5))
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contraste(a: str, b: str) -> float:
    claro, escuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


@pytest.mark.parametrize(
    ("livro", "ligado", "esperado"),
    [
        ("fantasia", True, "fantasia"),
        ("horror", True, "horror"),
        ("gotico", True, "gotico"),
        ("oriental", True, "oriental"),
        ("scifi", True, "scifi"),
        ("fantasia", False, GRIMORIO),  # opção desligada
        (None, True, GRIMORIO),  # sem livro
        ("padrao", True, GRIMORIO),  # gênero neutro
        ("desconhecido", True, GRIMORIO),
    ],
)
def test_tema_escolhido(livro, ligado, esperado):
    assert tema_do_site(livro, ligado) == esperado


def test_temas_do_site_sao_os_das_fichas():
    assert set(TEMAS_DO_SITE) <= set(TEMAS)


def test_grimorio_nao_sobrepoe_nada():
    assert css_do_tema(PASTA, GRIMORIO, "Qualquer") == ""


@pytest.mark.parametrize("tema", TEMAS_DO_SITE)
def test_css_do_tema_comeca_pelas_fontes_e_vem_depois_da_base(tema):
    css = css_do_tema(PASTA, tema, "Sistema")
    assert css.startswith('@import url("https://fonts.googleapis.com/')
    # O endereço das fontes tem ";": o @import precisa sair inteiro.
    assert css.count("@import") == 1
    assert re.match(r'@import url\("[^"]+"\);', css)
    # O tema precisa vir depois da base para vencer as regras de mesma força.
    assert css.index("O que todo tema de livro sobrepõe") < css.index("--papel:")
    assert '--inicial: "S"' in css


def test_inicial_do_selo_ignora_o_que_nao_e_letra():
    assert '--inicial: "N"' in css_do_tema(PASTA, "oriental", "«naruto»")
    assert '--inicial: "O"' in css_do_tema(PASTA, "oriental", "")
    assert (
        '"; }'
        not in css_do_tema(PASTA, "oriental", 'x"; } body { display: none').split("--inicial")[0]
    )


@pytest.mark.parametrize("tema", TEMAS_DO_SITE)
def test_tema_define_toda_variavel_que_a_base_usa(tema):
    base = (PASTA / "base.css").read_text(encoding="utf-8")
    estilo = (PASTA.parent / "estilo.css").read_text(encoding="utf-8")
    proprio = (PASTA / f"{tema}.css").read_text(encoding="utf-8")
    usadas = set(re.findall(r"var\(--([\w-]+)", base + proprio))
    locais = set(re.findall(r"--([\w-]+)\s*:", proprio))
    do_site = set(re.findall(r"--([\w-]+)\s*:", estilo))
    assert usadas - locais - do_site - {"inicial"} == set()


@pytest.mark.parametrize("tema", TEMAS_DO_SITE)
def test_contraste_do_texto_em_cada_tema(tema):
    t = tokens_do_tema(PASTA, tema)
    for fundo in ("papel", "papel-2", "papel-3"):
        assert _contraste(t["tinta"], t[fundo]) >= 7, (tema, fundo)
        assert _contraste(t["tinta-suave"], t[fundo]) >= 4.5, (tema, fundo)
        assert _contraste(t["titulo"], t[fundo]) >= 4.5, (tema, fundo)
        assert _contraste(t["link"], t[fundo]) >= 4.5, (tema, fundo)
        assert _contraste(t["ouro"], t[fundo]) >= 4.5, (tema, fundo)
    assert _contraste(t["acento-tinta"], t["acento"]) >= 4.5, tema


@pytest.mark.parametrize("tema", TODOS)
def test_barras_do_grafico_aparecem_no_fundo(tema):
    t = tokens_do_tema(PASTA, tema)
    assert _contraste(t["ouro"], t["papel"]) >= 3
    assert _contraste(t["barra-neutra"], t["papel"]) >= 2  # coadjuvante: o destaque é a outra cor
    assert _contraste(t["ouro"], t["barra-neutra"]) >= 1.3


def test_capa_so_aparece_depois_de_uma_troca():
    assert 'class="cortina"' not in cortina_html("Título", 0)
    assert 'data-troca="2"' in cortina_html("Título", 2)


def test_capa_escapa_o_titulo():
    capa = cortina_html("<script>x</script>", 1)
    assert "<script>" not in capa and "&lt;script&gt;" in capa


def test_capa_muda_a_cada_troca_e_repete_igual_entre_execucoes():
    # O HTML igual é o que impede a animação de tocar de novo ao navegar.
    assert cortina_html("A", 1) == cortina_html("A", 1)
    assert cortina_html("A", 1) != cortina_html("A", 2)


def test_d20_da_capa_vai_como_imagem_no_css_com_a_cor_do_tema():
    # O site remove <svg> do HTML: dentro do HTML, o dado sumiria sem nenhum erro.
    capa = cortina_html("A", 1, "#7a1f24")
    assert "<svg" not in capa.split("</style>")[1]
    assert "data:image/svg+xml," in capa
    assert "%237a1f24" in capa  # o "#" precisa ir codificado no endereço
    assert '"' not in capa.split('url("')[1].split('")')[0]  # as aspas não fecham o url() antes


def test_emenda_da_capa_fica_no_centro_da_tela():
    # O dado e o título ficam nos 50%. Com folhas mais largas, a linha sairia do centro.
    estilo = (PASTA.parent / "estilo.css").read_text(encoding="utf-8")
    folha = re.search(r"\.cortina \.folha \{(.*?)\}", estilo, re.S).group(1)
    assert "width: 50%" in folha and "box-sizing: border-box" in folha
