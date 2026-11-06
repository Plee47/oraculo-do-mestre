"""Feiticeiros & Maldições: fórmulas, validação, gerador e análise de grupo."""

import pytest

from oraculo.nucleo import Ficha, obter_regras
from oraculo.sistemas.fm import bonus_treinamento, custo_compra_pontos, modificador
from oraculo.sistemas.fm.analise import analisar_grupo, perfil
from oraculo.sistemas.fm.gerador import PAPEIS, gerar_ficha

REGRAS = obter_regras("fm")
PADRAO = {"for": 15, "des": 12, "con": 14, "int": 13, "sab": 10, "pre": 8}


def ficha(classe="lutador", nivel=1, origem="inato", **kw) -> Ficha:
    atributos = kw.pop("atributos", PADRAO)
    return Ficha(
        nome=kw.pop("nome", "Teste"), sistema="fm", classe=classe, nivel=nivel, origem=origem,
        atributos=atributos, **kw,
    )  # fmt: skip


# --------------------------------------------------------------------------- fórmulas


def test_tabelas_basicas():
    assert [modificador(v) for v in (1, 8, 10, 11, 15, 20, 30)] == [-5, -1, 0, 0, 2, 5, 10]
    assert [bonus_treinamento(n) for n in (1, 4, 5, 9, 13, 17, 20)] == [2, 2, 3, 4, 5, 6, 6]


def test_exemplo_do_livro_especialista_em_combate():
    # Passo a passo de criação do livro: CON 16 (+3) → 12 + 3 = 15 PV; 4 PE no nível 1.
    d = REGRAS.derivados(ficha("especialista_combate", atributos=PADRAO | {"for": 18, "con": 16}))
    assert d["pv_maximo"] == 15 and d["pe"] == 4
    assert d["cd_especializacao"] == 10 + 0 + 4 + 2  # FOR 18 é o melhor atributo-chave


def test_pv_pe_e_valores_de_combate_por_nivel():
    d = REGRAS.derivados(ficha("especialista_tecnica", nivel=5, atributos=PADRAO | {"int": 16}))
    # 10 + CON(+2) no 1º; depois (d8 fixo 5) + 2 por nível
    assert d["pv_maximo"] == 12 + 4 * 7
    assert d["integridade_alma"] == d["pv_maximo"]
    assert d["pe"] == 6 * 5 + 3  # soma o mod. do atributo de técnica uma única vez
    assert d["defesa"] == 10 + 1 + 2  # DES 12 + metade do nível
    assert d["cd_tecnica"] == 10 + 2 + 3 + 3
    assert d["ataque_amaldicoado"] == 3 + 2 + 3
    assert d["deslocamento"] == 9


def test_restringido_usa_estamina_e_treina_dois_testes():
    d = REGRAS.derivados(ficha("restringido", nivel=3, origem="restringido"))
    assert "pe" not in d and d["estamina"] == 12
    assert d["deslocamento"] == 12
    assert d["resistencia_fortitude"] == 2 + 1 + 2 and d["resistencia_reflexos"] == 1 + 1 + 2
    assert d["resistencia_vontade"] == 0 + 1  # sem treino


def test_teste_de_resistencia_escolhido_e_mestre_no_nivel_9():
    base = REGRAS.derivados(ficha("suporte"))
    assert base["resistencia_astucia"] == 1 + 0 + 2  # INT 13 > SAB 10: escolhe Astúcia
    vontade = REGRAS.derivados(ficha("suporte", pericias=["vontade"]))
    assert vontade["resistencia_vontade"] == 0 + 2 and vontade["resistencia_astucia"] == 1
    n9 = REGRAS.derivados(ficha("suporte", nivel=9))
    assert n9["resistencia_astucia"] == 1 + 4 + 4 + 2  # mestre: +metade do treinamento
    assert n9["resistencia_vontade"] == 0 + 4 + 4  # segundo teste treinado


def test_pericias_e_atencao():
    d = REGRAS.derivados(ficha(pericias=["percepcao"]))
    assert d["pericia_percepcao"] == 0 + 0 + 2
    assert d["atencao"] == 12
    assert d["pericia_atletismo"] == 2  # sem treino: só o modificador


# --------------------------------------------------------------------------- validação


def test_ficha_valida_e_metodos():
    assert REGRAS.validar(ficha(metodo_atributos="padrao")) == []
    assert custo_compra_pontos(PADRAO) == 7 + 3 + 5 + 4 + 0 - 2
    caro = PADRAO | {"des": 15, "sab": 15}
    assert any("limite é 17" in p.mensagem for p in REGRAS.validar(
        ficha(atributos=caro, metodo_atributos="compra_pontos")))  # fmt: skip


def test_restringido_exige_origem_e_especializacao_juntas():
    assert not REGRAS.ficha_valida(ficha("restringido", origem="inato"))
    assert not REGRAS.ficha_valida(ficha("lutador", origem="restringido"))
    assert REGRAS.ficha_valida(ficha("restringido", origem="restringido"))


def test_avisos():
    fraca = ficha("especialista_tecnica", atributos=PADRAO | {"int": 10, "sab": 10, "con": 8})
    mensagens = [p.mensagem for p in REGRAS.validar(fraca)]
    assert any("CD de especialização" in m for m in mensagens)
    assert any("CON abaixo de 10" in m for m in mensagens)
    assert REGRAS.ficha_valida(fraca)  # avisos não invalidam
    acima = REGRAS.validar(ficha(atributos=PADRAO | {"for": 22}))
    assert any("limite comum" in p.mensagem for p in acima)


# --------------------------------------------------------------------------- gerador


@pytest.mark.parametrize("classe", [c.id for c in REGRAS.definicao.classes])
@pytest.mark.parametrize("nivel", [1, 4, 9, 20])
def test_gerador_produz_fichas_validas(classe, nivel):
    f = gerar_ficha(nivel, classe=classe, seed=7)
    assert REGRAS.ficha_valida(f), REGRAS.validar(f)
    assert all(v <= 20 for v in f.atributos.values())
    assert f.explicacoes


def test_gerador_origens_e_pontos():
    inato = gerar_ficha(1, classe="lutador", seed=1)
    assert inato.origem == "inato" and inato.atributos["for"] == 17  # 15 + 2
    sem = gerar_ficha(1, classe="lutador", origem="sem_tecnica", seed=1)
    assert sum(sem.atributos.values()) == sum((15, 14, 13, 12, 10, 8)) + 4
    assert sem.poderes == []
    r = gerar_ficha(1, origem="restringido", seed=1)
    assert r.classe == "restringido" and r.poderes == ["estilo marcial"]
    n8 = gerar_ficha(8, classe="lutador", seed=1)
    assert sum(n8.atributos.values()) == sum(inato.atributos.values()) + 4


def test_gerador_respeita_papel_e_e_deterministico():
    for papel in PAPEIS:
        f = gerar_ficha(3, papel=papel, seed=3)
        assert REGRAS.definicao.classe(f.classe).papel == papel
    assert gerar_ficha(5, seed=42) == gerar_ficha(5, seed=42)


# --------------------------------------------------------------------------- análise


def _titulos(achados):
    return [a.titulo for a in achados]


def test_grupo_so_de_combatentes():
    grupo = [
        gerar_ficha(3, classe="lutador", nome="A", seed=1),
        gerar_ficha(3, classe="lutador", nome="B", seed=2),
    ]
    titulos = _titulos(analisar_grupo(grupo))
    assert "Ninguém cura com energia reversa" in titulos
    assert "Pouca energia amaldiçoada no grupo" in titulos
    assert "Ninguém treinado em armas à distância" in titulos
    assert any(t.startswith("Ninguém treinado em Vontade") for t in titulos)


def test_grupo_equilibrado_tem_menos_alertas():
    grupo = [
        gerar_ficha(5, classe=c, nome=c, seed=1)
        for c in ("lutador", "especialista_tecnica", "suporte", "especialista_combate")
    ]
    achados = analisar_grupo(grupo)
    assert "Há cura no grupo" in _titulos(achados)
    assert not [a for a in achados if a.severidade == "alerta"]


def test_origens_raras_repetidas_e_perfil():
    grupo = [ficha(origem="derivado", nome="A"), ficha(origem="derivado", nome="B")]
    assert any("origem rara Derivado" in t for t in _titulos(analisar_grupo(grupo)))
    p = perfil(ficha("restringido", origem="restringido"))
    assert p.tipo_energia == "estamina" and p.distancia
