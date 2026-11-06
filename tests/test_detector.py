"""Detector "é livro de RPG?" com o modelo publicado (dados/publicos/modelos/detector_rpg.json).

Os trechos abaixo foram escritos para os testes (não são cópias de livros).
"""

from pathlib import Path

import pytest

from oraculo.leitor.corpus import paginas_de_texto
from oraculo.leitor.detector import (
    FEATURES,
    ModeloDetector,
    _contar,
    avaliar_documento,
    extrair_features,
    sistema_provavel,
)

MODELO = Path(__file__).parents[1] / "dados" / "publicos" / "modelos" / "detector_rpg.json"

RPG_EN = (
    """
Shadow Wolf. Medium beast. Armor Class 13. Hit Points 22 (4d8 + 4). Speed 40 ft.
STR 14 (+2) DEX 15 (+2) CON 12 (+1) INT 3 (-4) WIS 12 (+1) CHA 6 (-2)
Senses darkvision 60 ft. Challenge 1. Bite. Melee Weapon Attack: +4 to hit, one target.
Hit: 7 (2d4 + 2) piercing damage. If the target is a creature, it must succeed on a DC 12
Strength saving throw or be knocked prone. When you take a short rest, you can spend Hit Dice.
Your character gains a bonus action and adds the proficiency bonus to the attack roll.
"""
    * 3
)

RPG_PT = (
    """
Lobo das Sombras. Classe de Armadura 13, Pontos de Vida 22 (4d8 + 4), Deslocamento 12 m.
FOR 14 (+2) DES 15 (+2) CON 12 (+1). Ataque: +4 para acertar, dano 1d6 + 2 perfurante.
O personagem deve fazer um teste de resistência de Força com dificuldade 12. Quando você
rolar o dado, some o modificador do atributo e o bônus de proficiência. O mestre decide o
alcance e a duração da magia, e o jogador anota a penalidade na ficha do personagem.
"""
    * 3
)

ROMANCE = (
    """
The old wizard walked slowly along the river, and the mist rose from the water like smoke.
She had not seen the tower for many years, and her heart was heavy as she remembered the
dragon that once slept beneath it. "We must go before the moon rises," he said quietly,
and they went on together through the silent forest until the stars were bright above them.
"""
    * 4
)

XADREZ = (
    """
In this position White should advance the pawn to the fifth square, because the Black king
cannot reach it in time. The rook belongs behind the passed pawn. Notice how the knight is
less valuable than the bishop when the pawns are on both sides of the board, and how the
player who controls the open file usually wins the endgame after the exchange of queens.
"""
    * 4
)

# Contraexemplos em português: com a lista antiga de termos ("jogador", "teste", "nível",
# "resistência"...), estes trechos eram classificados como RPG (0,99 e 1,00).
XADREZ_PT = (
    "O jogador deve avançar o peão até a quinta casa, porque o rei adversário não chega a "
    "tempo. O mestre explica que a torre fica atrás do peão passado e que o cavalo vale menos "
    "que o bispo neste nível de jogo. "
) * 4
FUTEBOL_PT = (
    "O jogador recebeu o passe e o técnico pediu mais ataque pelo lado direito. No teste "
    "físico, o time mostrou resistência e habilidade, e o nível do campeonato subiu muito. "
) * 4


@pytest.fixture(scope="module")
def modelo() -> ModeloDetector:
    return ModeloDetector.carregar(MODELO)


def test_modelo_publicado_tem_as_features_do_codigo(modelo):
    assert set(modelo.coeficientes) == set(FEATURES)
    # Todo sinal de RPG deve empurrar a nota para cima (evidência positiva).
    assert all(c > 0 for c in modelo.coeficientes.values())


def test_contagem_respeita_fronteira_de_palavra():
    # Regressão: sem \b, "dado" contava dentro de "cuidado" e "you" dentro de "young".
    assert _contar("cuidado com o dado", ("dado",)) == 1
    assert _contar("the young knight", ("you",)) == 0
    assert _contar("you and your sword", ("you", "your")) == 2


def test_features_de_um_bloco_de_estatisticas():
    f = extrair_features(RPG_EN)
    for nome in ("dados_por_mil", "modificadores_por_mil", "atributos_por_mil",
                 "termos_regras_por_mil", "termos_estatistica_por_mil"):  # fmt: skip
        assert f[nome] > 1, nome
    vazio = extrair_features(ROMANCE)
    assert vazio["dados_por_mil"] == 0 and vazio["atributos_por_mil"] == 0


@pytest.mark.parametrize(("texto", "esperado"), [(RPG_EN, True), (RPG_PT, True)])
def test_reconhece_rpg_em_ingles_e_portugues(modelo, texto, esperado):
    assert avaliar_documento(modelo, [texto]).e_rpg is esperado


@pytest.mark.parametrize("texto", [ROMANCE, XADREZ, XADREZ_PT, FUTEBOL_PT])
def test_nao_confunde_fantasia_nem_regras_de_xadrez(modelo, texto):
    v = avaliar_documento(modelo, [texto])
    assert not v.e_rpg
    assert v.nota < 0.5


def test_motivos_explicam_a_decisao(modelo):
    v = avaliar_documento(modelo, [RPG_EN])
    assert len(v.motivos) == 3
    assert all("parecido com RPG" in m for m in v.motivos)


def test_paginas_curtas_ou_vazias(modelo):
    v = avaliar_documento(modelo, ["", "capítulo 1", "   "])
    assert (v.e_rpg, v.paginas_analisadas) == (False, 0)
    assert "escaneado" in v.motivos[0]


CLASSES_EN = "Barbarian, Bard, Cleric, Druid, Fighter, Monk, Paladin, Ranger, Rogue, Sorcerer."
TEXTO_FM = (
    "Feiticeiros & Maldições é um RPG. A técnica amaldiçoada consome energia amaldiçoada. "
) * 25
# Sistema brasileiro de base 2d8 com vocabulário comum a muitos RPGs em português.
TEXTO_2D8 = (
    "Role 2d8 e some a precisão. Faça um teste de resistência de Vigor contra a dificuldade. "
    "O mestre define o nível de desafio da cena. "
) * 30


def test_sistema_provavel_so_com_evidencia_forte():
    assert sistema_provavel(RPG_EN + CLASSES_EN * 2)[0] == "dnd5e"
    assert sistema_provavel(TEXTO_FM)[0] == "fm"
    assert sistema_provavel(ROMANCE)[0] is None
    # Regressão: termos comuns ("teste de resistência") faziam um sistema 2d8 virar D&D 5e.
    assert sistema_provavel(TEXTO_2D8)[0] is None
    # Termos de 5e sem as classes (ex.: um RPG derivado do D&D) também não bastam.
    assert sistema_provavel(RPG_EN)[0] is None
    # Quebras de linha do PDF no meio do termo não atrapalham a contagem.
    _, evid = sistema_provavel("proficiency\nbonus " * 3)
    assert evid["dnd5e_termos"] == 3


def test_modelo_json_ida_e_volta(modelo, tmp_path):
    caminho = tmp_path / "m.json"
    modelo.salvar(caminho)
    assert ModeloDetector.carregar(caminho) == modelo
    assert ModeloDetector.carregar(caminho).prob_pagina(RPG_EN) == modelo.prob_pagina(RPG_EN)


def test_paginas_de_texto_remove_cabecalho_do_gutenberg():
    bruto = (
        "Licença blá\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\n"
        + "Parágrafo de história.\n\n" * 400
        + "*** END OF THE PROJECT GUTENBERG EBOOK X ***\nRodapé"
    )
    paginas = paginas_de_texto(bruto, tamanho=1000)
    assert len(paginas) > 1
    assert not any("Licença" in p or "Rodapé" in p for p in paginas)
