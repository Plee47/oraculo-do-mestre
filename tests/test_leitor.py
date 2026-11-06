"""Leitor de livros: limpeza, janelas, respostas do LLM, porteiro e avaliação (sem chamar LLM)."""

import json
from pathlib import Path

import pytest

from oraculo.leitor.avaliacao import avaliar_extracao, esperadas_na_pagina, normalizar
from oraculo.leitor.detector import ModeloDetector
from oraculo.leitor.extracao import (
    converter,
    interpretar_resposta,
    janelas,
    limpar_texto_pdf,
    parece_ter_entradas,
    prompt_unico,
)
from oraculo.leitor.porteiro import decidir
from oraculo.sistemas.dnd5e.catalogo import Catalogo

RAIZ = Path(__file__).parents[1]
MODELO = RAIZ / "dados" / "publicos" / "modelos" / "detector_rpg.json"
CATALOGO = RAIZ / "dados" / "publicos" / "dnd5e" / "catalogo.json"

# Páginas no formato "sujo" em que o PDF do SRD sai (tabs, vários hífens, uma palavra por linha).
PAGINA_MAGIA = "Fireball\t \n3rd-‐‑level\t evocation\nCasting Time: 1 action\n" + "x " * 120
PAGINA_TRUQUE = "Acid\nSplash\nConjuration\ncantrip\nCasting\nTime:\n1\naction\n" + "y " * 120
PAGINA_MONSTRO = (
    "Goblin\nSmall humanoid (goblinoid), neutral evil\nArmor Class 15\nHit Points 7 (2d6)\n"
    + "z " * 120
)


@pytest.fixture(scope="module")
def gabarito() -> Catalogo:
    return Catalogo.carregar(CATALOGO)


# --------------------------------------------------------------------------- texto


def test_limpeza_do_pdf():
    limpo = limpar_texto_pdf("4th-‐‑level\t  conjuration’s \xadx\n\n  \n")
    assert limpo == "4th-level conjuration's x"


def test_janelas_juntam_a_continuacao_da_proxima_pagina():
    paginas = ["a " * 150, "curta", "b " * 150, "c " * 150]
    js = janelas(paginas, continuacao=20)
    assert [j.pagina for j in js] == [1, 3, 4]  # páginas curtas não viram janela
    assert "PÁGINA B" in js[0].texto
    continuacao = js[1].texto.split("(continuação) ===\n", 1)[1]
    assert continuacao.strip() == ("c " * 150)[:20].strip()  # só o começo da página seguinte
    assert js[0].texto in prompt_unico(js[0])


def test_pre_filtro():
    assert parece_ter_entradas(PAGINA_MAGIA)
    assert parece_ter_entradas(PAGINA_MONSTRO)
    assert not parece_ter_entradas("Era uma vez um reino distante. " * 30)


# --------------------------------------------------------------------------- respostas do LLM

RESPOSTA = {
    "magias": [
        {"nome": "Fireball", "circulo": 3, "escola": "Evocation", "concentracao": False,
         "ritual": False, "dano": "8d6", "tipo_dano": "Fire", "resistencia": "DEX",
         "area": True, "cura": False},
    ],
    "monstros": [
        {"nome": "Goblin", "tamanho": "small", "tipo": "Humanoid", "cr": "1/4", "ca": 15,
         "pv": 7, "atributos": {"str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8},
         "imunidades_dano": ["charmed", "Poison"], "resistencias_dano": [],
         "vulnerabilidades_dano": None, "voa": False, "acoes_lendarias": 0},
    ],
}  # fmt: skip


@pytest.mark.parametrize(
    "formato",
    [
        lambda d: json.dumps(d),
        lambda d: f"```json\n{json.dumps(d)}\n```",
        lambda d: f"Aqui está o resultado:\n{json.dumps(d)}\nEspero ter ajudado!",
    ],
)
def test_interpreta_json_em_varios_formatos(formato):
    assert interpretar_resposta(formato(RESPOSTA)) == RESPOSTA


def test_converte_e_normaliza_campos():
    ext = converter([(1, json.dumps(RESPOSTA))])
    magia, monstro = ext.magias[0], ext.monstros[0]
    assert (magia.id, magia.escola, magia.tipo_dano, magia.resistencia) == (
        "fireball", "evocation", "fire", "des",
    )  # fmt: skip
    assert monstro.cr == 0.25 and monstro.tamanho == "Small" and monstro.tipo == "humanoid"
    assert monstro.atributos["des"] == 14
    assert monstro.imunidades_dano == ["poison"]  # "charmed" é condição, não tipo de dano


def test_respostas_ruins_viram_erros_sem_derrubar_o_resto():
    ext = converter(
        [(1, "não sei"), (2, '{"magias": [{"sem_nome": 1}]}'), (3, json.dumps(RESPOSTA))]
    )
    assert len(ext.magias) == 1 and len(ext.monstros) == 1
    assert len(ext.erros) == 2


def test_deduplica_entradas_repetidas():
    ext = converter([(1, json.dumps(RESPOSTA)), (2, json.dumps(RESPOSTA))])
    assert len(ext.magias) == 1


# --------------------------------------------------------------------------- porteiro

RPG = (
    "Armor Class 14, Hit Points 27 (5d8 + 5). STR 15 (+2) DEX 14 (+2). The target must succeed "
    "on a DC 12 saving throw. Your character adds the proficiency bonus to the attack roll. "
) * 6


def test_porteiro():
    modelo = ModeloDetector.carregar(MODELO)
    # Qualquer RPG é aceito: sistema desconhecido vai para a leitura com LLM.
    outro = decidir(modelo, [RPG])
    assert outro.aceito and outro.caminho == "leitura" and not outro.incerto
    romance = decidir(modelo, ["The old knight walked home and she said goodbye. " * 30])
    assert not romance.aceito and romance.caminho == "barrado" and "não parece" in romance.motivo
    tagmar = decidir(modelo, [RPG + " Tagmar karma estágio tabela de resolução " * 5])
    assert tagmar.aceito and tagmar.caminho == "leitura"
    fm = decidir(modelo, [RPG + " Feiticeiros & Maldições, energia amaldiçoada. " * 25])
    assert fm.aceito and fm.caminho == "pronto" and "Feiticeiros & Maldições" in fm.motivo
    vazio = decidir(modelo, ["", " "])
    assert not vazio.aceito and "escaneado" in vazio.motivo


# --------------------------------------------------------------------------- avaliação


def test_esperadas_mesmo_com_uma_palavra_por_linha(gabarito):
    assert esperadas_na_pagina(PAGINA_MAGIA, gabarito) == ({"fireball"}, set())
    assert esperadas_na_pagina(PAGINA_TRUQUE, gabarito) == ({"acid-splash"}, set())
    assert esperadas_na_pagina(PAGINA_MONSTRO, gabarito) == (set(), {"goblin"})
    # nome só citado no texto, sem a linha de nível, não conta
    assert esperadas_na_pagina("como a magia Fireball explica, " * 20, gabarito) == (set(), set())


def test_avaliacao_mede_precisao_recall_e_campos(gabarito):
    resposta = json.loads(json.dumps(RESPOSTA))
    resposta["magias"].append({"nome": "Magia Inventada", "circulo": 1})
    resposta["monstros"][0]["pv"] = 99  # erro proposital
    ext = converter([(1, json.dumps(resposta))])
    r = avaliar_extracao(ext, {"fireball", "acid-splash"}, {"goblin"}, gabarito)
    assert r.metricas["magias_precisao"] == 0.5  # 1 certa, 1 inventada
    assert r.metricas["magias_recall"] == 0.5  # achou fireball, perdeu acid splash
    assert r.metricas["monstros_recall"] == 1.0
    assert r.metricas["monstros_campo_pv"] == 0.0
    assert r.metricas["monstros_campo_ca"] == 1.0
    assert r.metricas["magias_campo_dano"] == 1.0
    assert 0 < r.metricas["nota_geral"] < 1
    errado = next(c for c in r.campos if c["campo"] == "pv")
    assert (errado["extraido"], errado["gabarito"], errado["acertou"]) == ("99", "7", False)


def test_normalizar_nomes():
    assert normalizar("Arcanist's Magic Aura") == normalizar("Arcanists Magic  Aura")
