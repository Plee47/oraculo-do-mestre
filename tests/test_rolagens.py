"""Rolagem de dados: notação, regras de cada dado e probabilidades contra valores conhecidos."""

import random

import pytest

from oraculo.rolagens import (
    LIMITE_DADOS,
    ErroRolagem,
    distribuicao,
    ler,
    montar,
    rolar,
)


def _uma(texto: str, semente: int = 1):
    return rolar(texto, random.Random(semente))[0]


# --------------------------------------------------------------------------- rolar
@pytest.mark.parametrize("semente", range(30))
def test_soma_com_modificador(semente):
    r = _uma("2d6+3", semente)
    assert r.total == sum(d.valor for d in r.grupos[0].dados) + 3
    assert 5 <= r.total <= 15


@pytest.mark.parametrize(
    ("texto", "total"),
    [
        ("5", 5),
        ("2+3*4", 14),
        ("(2+3)*4", 20),
        ("7/2", 3),  # arredonda para baixo, como a maioria dos RPGs
        ("-7/2", -4),
        ("teto(7/2)", 4),
        ("piso(7/2)", 3),
        ("max(1,3-5)", 1),
        ("min(4,2,9)", 2),
        ("10 - 2 - 3", 5),
        ("2×3", 6),
        ("2x3", 6),
        ("8÷2", 4),
        ("-(2+3)", -5),
    ],
)
def test_contas_sem_dados(texto, total):
    assert _uma(texto).total == total


def test_maiusculas_e_espacos_nao_importam():
    assert _uma("2D6 + 3", 4).total == _uma("2d6+3", 4).total


def test_mantem_os_maiores_e_marca_os_descartados():
    r = _uma("4d6kh3")
    dados = r.grupos[0].dados
    fora = [d for d in dados if not d.mantido]
    assert len(dados) == 4 and len(fora) == 1
    assert fora[0].valor == min(d.valor for d in dados)
    assert r.total == sum(d.valor for d in dados) - fora[0].valor
    assert f"~{fora[0].valor}" in r.detalhe


@pytest.mark.parametrize(("curto", "longo"), [("4d6dl1", "4d6kh3"), ("4d6dh1", "4d6kl3")])
def test_descartar_equivale_a_manter(curto, longo):
    assert _uma(curto, 7).total == _uma(longo, 7).total


@pytest.mark.parametrize(("atalho", "dado"), [("vant", "2d20kh1"), ("desv", "2d20kl1")])
def test_vantagem_e_desvantagem(atalho, dado):
    assert _uma(f"{atalho}+5", 3).total == _uma(f"{dado}+5", 3).total


def test_explosao_acrescenta_dados_e_para_no_limite():
    # d2 explode quase sempre em 2; o limite impede rolar para sempre.
    for semente in range(50):
        r = _uma("1d2!", semente)
        dados = r.grupos[0].dados
        assert r.total == sum(d.valor for d in dados)
        assert len(dados) <= 21
        assert all(d.valor == 2 for d in dados[:-1])
        assert all(d.explosao for d in dados[1:])


def test_explosao_com_condicao():
    for semente in range(50):
        dados = _uma("1d6!>=5", semente).grupos[0].dados
        assert all(d.valor >= 5 for d in dados[:-1])


def test_rola_de_novo_uma_vez_guarda_o_valor_antigo():
    vistos = [_uma("1d6r1", s).grupos[0].dados[0] for s in range(200)]
    rerolados = [d for d in vistos if d.rerolado_de == 1]
    assert rerolados and any(d.valor == 1 for d in rerolados)  # a segunda rolagem pode dar 1


def test_rola_de_novo_ate_sair():
    assert all(_uma("1d6rr<=2", s).total >= 3 for s in range(200))


def test_conta_sucessos_e_falhas():
    r = _uma("10d10>=8f1", 5)
    dados = r.grupos[0].dados
    sucessos = sum(d.valor >= 8 for d in dados)
    falhas = sum(d.valor == 1 for d in dados)
    assert r.total == sucessos - falhas
    assert {d.resultado for d in dados if d.valor >= 8} <= {"sucesso"}
    assert {d.resultado for d in dados if d.valor == 1} <= {"falha"}


def test_fudge_e_percentual():
    assert all(-4 <= _uma("4dF", s).total <= 4 for s in range(50))
    assert all(1 <= _uma("d%", s).total <= 100 for s in range(50))


def test_marca_face_maxima_e_minima():
    for semente in range(100):
        d = _uma("1d4", semente).grupos[0].dados[0]
        assert d.extremo == {4: "max", 1: "min"}.get(d.valor, "")


def test_varias_rolagens_e_repeticao():
    assert [r.expressao for r in rolar("1d20+5, 2d6+3", random.Random(1))] == ["1d20+5", "2d6+3"]
    assert len(rolar("6#4d6kh3", random.Random(1))) == 6
    assert len(rolar("max(1,1d4-2), 2#d6", random.Random(1))) == 3  # vírgula do max não separa


def test_mesma_semente_mesmo_resultado():
    assert rolar("3d6!+2", random.Random(9)) == rolar("3d6!+2", random.Random(9))


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "   ",
        "abc",
        "2d",
        "d1",
        "0d6",
        "2d6+",
        "(2d6",
        "2d6)",
        "1d6!>=1",  # toda face explode
        "1d6r<=6",  # toda face rola de novo
        "4d6kh5",
        "4d6dl4",
        "2d6kh1kl1",
        "1/0",
        "1d6>=3>=4",
        "(2d6+3)>=10",
        "2d6;drop table",
        "__import__('os')",
        "101#d6",
        f"{LIMITE_DADOS + 1}d6",
        "1d1000000",
        "(" * 30 + "1" + ")" * 30,
        "1" * 400,
        ",".join(["d6"] * 11),
        "min(1",
        "teto(1,2)",
    ],
)
def test_expressao_invalida_vira_mensagem(texto):
    with pytest.raises(ErroRolagem) as e:
        rolar(texto, random.Random(1))
    assert str(e.value)


def test_dados_de_toda_a_expressao_contam_no_limite():
    with pytest.raises(ErroRolagem):
        ler(f"{LIMITE_DADOS}d6+1d6")
    with pytest.raises(ErroRolagem):
        ler(f"{LIMITE_DADOS}d6+vant")


@pytest.mark.parametrize(
    ("q", "f", "m", "modo", "esperado"),
    [
        (1, 20, 5, "normal", "1d20+5"),
        (2, 6, -1, "normal", "2d6-1"),
        (1, 20, 0, "normal", "1d20"),
        (1, 20, 3, "vantagem", "2d20kh1+3"),
        (1, 20, 0, "desvantagem", "2d20kl1"),
        (2, 6, 0, "vantagem", "3d6kh2"),
        (4, "F", 1, "normal", "4dF+1"),
    ],
)
def test_construtor_escreve_a_expressao(q, f, m, modo, esperado):
    assert montar(q, f, m, modo) == esperado
    assert rolar(esperado, random.Random(1))


# --------------------------------------------------------------------------- probabilidades
def test_2d6_tem_a_distribuicao_classica():
    d = distribuicao("2d6")
    assert d.exata
    assert d.probs[7] == pytest.approx(6 / 36)
    assert d.probs[2] == pytest.approx(1 / 36)
    assert d.media == pytest.approx(7)
    assert d.desvio == pytest.approx(2.41523, abs=1e-4)
    assert (d.minimo, d.maximo, d.moda) == (2, 12, 7)
    assert d.chance(">=", 10) == pytest.approx(6 / 36)
    assert d.percentil(0.5) == 7


@pytest.mark.parametrize(
    ("texto", "media"),
    [
        ("1d20+5", 15.5),
        ("4d6kh3", 12.2446),  # valor conhecido da geração clássica de atributos
        ("2d20kh1", 13.825),  # vantagem
        ("2d20kl1", 7.175),  # desvantagem
        ("d%", 50.5),
        ("4dF", 0),
        ("5d10>=8", 1.5),
        ("5d10>=8f1", 1.0),
        ("1d6r1", 3.91667),  # 1/6 x 3,5 + 5/6 x 4
        ("1d6rr1", 4),
        ("1d6!", 4.2),  # 3,5 x 6/5
        ("2d6*2", 14),
        ("max(1,1d4-2)", 1.25),  # 1, 1, 1, 2
        ("piso(1d6/2)", 1.5),  # 0, 1, 1, 2, 2, 3
        ("teto(1d6/2)", 2),  # 1, 1, 2, 2, 3, 3
        ("-1d6", -3.5),
        ("(1d4+1)*(1d4+1)", 12.25),
    ],
)
def test_media_exata_contra_o_valor_conhecido(texto, media):
    d = distribuicao(texto)
    assert d.exata
    assert d.media == pytest.approx(media, abs=1e-3)
    assert sum(d.probs.values()) == pytest.approx(1)


def test_vantagem_acerta_a_chance_de_tirar_20():
    assert distribuicao("vant").probs[20] == pytest.approx(1 - (19 / 20) ** 2)
    assert distribuicao("desv").probs[20] == pytest.approx(1 / 400)


def test_sucessos_seguem_a_binomial():
    d = distribuicao("3d10>=8")
    assert d.probs[3] == pytest.approx(0.3**3)
    assert d.probs[0] == pytest.approx(0.7**3)


@pytest.mark.parametrize(
    "texto",
    ["2d6+3", "4d6kh3", "3d6!", "1d6r1", "4d10>=7f1", "1d8rr<=2+1d4", "2d8kl1-1", "teto(2d6/3)"],
)
def test_conta_exata_bate_com_as_rolagens(texto):
    d = distribuicao(texto)
    assert d.exata
    rng = random.Random(3)
    vezes = 20_000
    soma = sum(rolar(texto, rng)[0].total for _ in range(vezes))
    assert soma / vezes == pytest.approx(d.media, abs=0.12)


def test_o_que_nao_tem_conta_exata_e_simulado_e_diz_isso():
    d = distribuicao("5d10!=10>=8")
    # Explode no 10 e conta sucessos: cada explosão é mais um dado que pode ser sucesso.
    assert not d.exata and d.simulacoes > 0
    assert sum(d.probs.values()) == pytest.approx(1)
    assert distribuicao("5d10!=10>=8") == d  # mesma semente: não muda entre interações


def test_conta_grande_demais_nao_trava():
    d = distribuicao("1000d6")
    assert not d.exata
    assert d.media == pytest.approx(3500, rel=0.01)


def test_distribuicao_recebe_uma_expressao_so():
    for texto in ("1d6, 1d8", "3#d6"):
        with pytest.raises(ErroRolagem):
            distribuicao(texto)
