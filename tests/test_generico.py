"""Motor genérico: qualquer sistema lido de um livro (fórmulas, normalização, fichas, análises,
leitura com um LLM falso). As especificações abaixo foram escritas para os testes, no formato
de quatro famílias de sistema: rolagem por atributo (Call of Cthulhu), valores fixos
(Vampiro), pontos com grupo separado (sistema 2d8 brasileiro) e d20 com modificador.
"""

import json
import random
from pathlib import Path

import pytest

from oraculo.sistemas.generico.analise import (
    analisar_encontro,
    analisar_grupo,
    criatura_de_ficha,
)
from oraculo.sistemas.generico.formulas import (
    ErroFormula,
    avaliar,
    media,
    nomes_desconhecidos,
    tem_dado,
    zerar_nomes,
)
from oraculo.sistemas.generico.gerador import calcular_derivados, gerar_ficha, validar
from oraculo.sistemas.generico.leitura import (
    ErroLeitura,
    extrair_json,
    ler_sistema,
    selecionar_paginas,
)
from oraculo.sistemas.generico.modelo import SistemaLido, normalizar

# --------------------------------------------------------------------------- especificações


def sistema(dados: dict) -> SistemaLido:
    return normalizar(SistemaLido.model_validate(dados))


CTHULHU = {
    "nome": "Horror d100",
    "mecanica": {"dado_base": "1d100", "tipo": "rolar_abaixo"},
    "atributos": [
        {
            "id": "for",
            "nome": "Força",
            "sigla": "FOR",
            "rolagem": "3d6*5",
            "minimo": 15,
            "maximo": 90,
        },
        {
            "id": "con",
            "nome": "Constituição",
            "sigla": "CON",
            "rolagem": "3d6*5",
            "minimo": 15,
            "maximo": 90,
        },
        {
            "id": "tam",
            "nome": "Tamanho",
            "sigla": "TAM",
            "rolagem": "(2d6+6)*5",
            "minimo": 40,
            "maximo": 90,
        },
        {
            "id": "pod",
            "nome": "Poder",
            "sigla": "POD",
            "rolagem": "3d6*5",
            "minimo": 15,
            "maximo": 90,
        },
    ],
    "derivados": [
        {"nome": "Pontos de Vida", "formula": "piso((CON+TAM)/10)", "tipo": "outro"},
        {"nome": "Sanidade", "formula": "POD", "tipo": "recurso"},
    ],
    "arquetipos": [{"nome": "Detetive", "atributos_chave": ["POD"], "dano_tipico": "1d3"}],
}

VAMPIRO = {
    "nome": "Caçada noturna",
    "mecanica": {"dado_base": "parada de d10", "tipo": "parada_de_sucessos"},
    "atributos": [
        {"nome": n, "minimo": 1, "maximo": 5}
        for n in (
            "Força",
            "Destreza",
            "Vigor",
            "Carisma",
            "Manipulação",
            "Autocontrole",
            "Inteligência",
            "Raciocínio",
            "Determinação",
        )
    ],
    "geracao": {"metodo": "valores_fixos", "valores_fixos": [4, 3, 3, 3, 2, 2, 2, 2, 1]},
    "derivados": [
        {"nome": "Vitalidade", "formula": "Vigor + 3"},
        {"nome": "Força de Vontade", "formula": "Autocontrole + Determinação"},
    ],
    "arquetipos": [{"nome": "Clã das Sombras", "atributos_chave": ["Raciocínio", "Destreza"]}],
}

SHINOBI = {
    "nome": "Ninjas 2d8",
    "mecanica": {
        "dado_base": "2d8",
        "tipo": "soma_contra_alvo",
        "dano_basico": "teto(Força/2) + DanoArma",
        "multiplicador_dano_medio": 2,
        "chance_acerto_estimada": 0.5,
    },
    "niveis": {
        "usa_niveis": True,
        "nivel_inicial": 4,
        "variavel": "nc",
        "nome": "Nível de Campanha",
    },
    "atributos": [
        {"id": i, "nome": n, "minimo": 0, "maximo": 4}
        for i, n in (
            ("for", "Força"),
            ("des", "Destreza"),
            ("agi", "Agilidade"),
            ("vig", "Vigor"),
            ("esp", "Espírito"),
            ("car", "Carisma"),
            ("man", "Manipulação"),
        )
    ],
    "geracao": {
        "metodo": "pontos",
        "pontos": 12,
        "valor_inicial": 0,
        "grupos": [
            {
                "nome": "sociais",
                "atributos": ["car", "man"],
                "metodo": "pontos",
                "pontos": 2,
                "valor_inicial": 0,
            }
        ],
    },
    "derivados": [
        {"nome": "Reação de Esquiva", "formula": "esq + 9"},  # usa um derivado listado depois
        {"id": "esq", "nome": "Esquiva", "formula": "3 + agi"},
        {"nome": "Vitalidade", "formula": "10 + 3x vig + 5x nc", "tipo": "recurso"},
        {"nome": "Iniciativa", "formula": "prontidao + agi"},  # depende de perícia
    ],
    "pericias": [
        {"nome": "Acrobacia", "atributo": "agi"},
        {"nome": "Furtividade", "atributo": "agi"},
        {"nome": "Medicina", "atributo": "esp"},
    ],
    "arquetipos": [
        {"nome": "Clã da Folha", "papel": "combate", "atributos_chave": ["for", "vig"]},
        {"nome": "Clã da Névoa", "papel": "suporte", "atributos_chave": ["esp", "agi"]},
    ],
}

D20 = {
    "nome": "Fantasia d20",
    "mecanica": {"dado_base": "1d20", "dano_basico": "1d8 + Modificador de Força"},
    "niveis": {"usa_niveis": True, "nivel_inicial": 1, "nivel_maximo": 20},
    "atributos": [
        {"id": i, "nome": n, "maximo": 20}
        for i, n in (
            ("for", "Força"),
            ("des", "Destreza"),
            ("con", "Constituição"),
            ("int", "Inteligência"),
            ("sab", "Sabedoria"),
            ("car", "Carisma"),
        )
    ],
    "geracao": {"metodo": "outro", "valores_fixos": [15, 14, 13, 12, 10, 8], "rolagem": "4d6kh3"},
    "derivados": [
        {"id": "pv", "nome": "Pontos de Vida", "formula": ""},
        {"nome": "Defesa", "formula": "10 + mod_des + outros"},
    ],
    "arquetipos": [
        {
            "nome": "Guerreiro",
            "atributos_chave": ["for", "con"],
            "formulas": {"pv": "10 + mod_con + (nivel-1)*(6+mod_con)"},
        },
        {"nome": "Mago", "atributos_chave": ["int"], "formulas": {"pv": "6 + mod_con"}},
    ],
    "criaturas": [
        {
            "nome": "Lobo",
            "vida": 11,
            "defesa": 13,
            "atributos": {"FOR": 12},
            "ataques": [{"nome": "Mordida", "dano": "2d4+2"}],
        },
        {
            "nome": "Ogro",
            "vida": 59,
            "ataques": [{"nome": "Clava", "dano": "2d8+4"}],
            "habilidades": ["Fúria"],
        },
    ],
}


# --------------------------------------------------------------------------- fórmulas


def test_formulas_com_dados_e_nomes():
    v = {"for": 3, "Vigor": 2, "nc": 4, "Força de Vontade": 5}
    assert media("2d8") == 9 and media("3d6*5") == 52.5 and media("(2d6+6)x5") == 65
    assert media("4d6kh3") == pytest.approx(12.2446, abs=1e-4)
    assert media("1d8+for", v) == 7.5  # "for" é palavra reservada do Python
    assert media("10 + 3x vigor + 5x nc", v) == 36  # notação "3x Vigor" do próprio livro
    assert media("min(for, 2) + teto(for/2)", v) == 4
    assert media("forca_de_vontade + 1", v) == 6  # nomes com acento e espaço viram id
    r = random.Random(1)
    rolagens = [avaliar("4d6kh3", rng=r) for _ in range(200)]
    assert min(rolagens) >= 3 and max(rolagens) <= 18
    assert tem_dado("2d8+des") and not tem_dado("DES+2")


@pytest.mark.parametrize(
    "perigosa",
    [
        '__import__("os")',
        "for.__class__",
        "open(1)",
        "lambda: 1",
        "[1, 2]",
        "x if 1 else 2",
        "2**99",
        "1/0",
        "999d6",
        "nada + 1",
        "",
    ],
)
def test_formulas_perigosas_ou_invalidas_sao_recusadas(perigosa):
    with pytest.raises(ErroFormula):
        avaliar(perigosa, {"for": 1})


def test_nomes_desconhecidos_e_zerar():
    v = {"forca": 3}
    assert nomes_desconhecidos("teto(Força/2)+DanoArma", v) == ["DanoArma"]
    assert media(zerar_nomes("teto(Força/2)+DanoArma", ["DanoArma"]), v) == 2


# --------------------------------------------------------------------------- normalização


def test_normalizacao_conserta_o_que_da_e_avisa_o_resto():
    s = sistema(SHINOBI)
    nomes = [d.nome for d in s.derivados]
    assert nomes.index("Esquiva") < nomes.index("Reação de Esquiva")  # dependência antes
    assert s.derivado_do_tipo("vida").nome == "Vitalidade"  # tipo corrigido pelo nome
    iniciativa = next(d for d in s.derivados if d.nome == "Iniciativa")
    assert iniciativa.formula == ""  # depende de perícia: fica como texto
    assert any("prontidao" in a for a in s.avisos)
    assert s.mecanica.dano_basico.endswith("+ 0")  # DanoArma = 0, com aviso
    assert any("DanoArma" in a for a in s.avisos)
    assert s.geracao.grupos[0].atributos == ["car", "man"]


def test_nulos_e_valores_estranhos_do_llm_nao_derrubam():
    s = sistema(
        {
            "nome": "X",
            "mecanica": {"tipo": "inventado", "chance_acerto_estimada": 70, "criticos": None},
            "atributos": [{"nome": "Força", "minimo": "3", "maximo": None, "descricao": None}],
            "derivados": [{"nome": "PV", "formula": None, "tipo": "vida_maxima"}],
            "criaturas": [
                {
                    "nome": "Águia",
                    "ameaca": None,
                    "vida": "12",
                    "atributos": {"for": "8"},
                    "ataques": [{"nome": "Garras", "dano": None}],
                }
            ],
        }
    )
    assert s.mecanica.tipo == "outro" and s.mecanica.chance_acerto_estimada == 0.7
    assert s.atributos[0].minimo == 3 and s.criaturas[0].vida == 12
    # sem sigla, "for" não é associado a "Força" com segurança: a chave fica como veio
    assert s.criaturas[0].atributos == {"for": 8} and s.derivados[0].tipo == "vida"


def test_modificador_d20_inferido_e_formulas_do_arquetipo():
    s = sistema(D20)
    assert s.modificador == "piso((valor-10)/2)"
    assert any("padrão d20" in a for a in s.avisos)
    defesa = next(d for d in s.derivados if d.nome == "Defesa")
    assert defesa.formula.endswith("+ 0")  # "outros" contou como 0
    assert s.arquetipo("Guerreiro").formulas == {"pv": "10 + mod_con + (nivel-1)*(6+mod_con)"}
    assert s.criaturas[0].atributos == {"for": 12}  # sigla mapeada para o id


# --------------------------------------------------------------------------- fichas


def test_ficha_com_rolagem_por_atributo():
    s = sistema(CTHULHU)
    f = gerar_ficha(s, seed=3)
    assert set(f.atributos) == {"for", "con", "tam", "pod"}
    assert all(v % 5 == 0 for v in f.atributos.values())  # 3d6*5 e (2d6+6)*5
    assert 40 <= f.atributos["tam"] <= 90
    pv = dict((d.nome, v) for d, v in calcular_derivados(s, f.atributos))["Pontos de Vida"]
    assert pv == (f.atributos["con"] + f.atributos["tam"]) // 10
    assert not validar(s, f)


def test_ficha_com_valores_fixos():
    s = sistema(VAMPIRO)
    f = gerar_ficha(s, arquetipo="Clã das Sombras", seed=1)
    assert sorted(f.atributos.values(), reverse=True) == [4, 3, 3, 3, 2, 2, 2, 2, 1]
    assert f.atributos["raciocinio"] == 4  # atributo-chave recebe o maior valor
    valores = dict((d.nome, v) for d, v in calcular_derivados(s, f.atributos))
    assert valores["Vitalidade"] == f.atributos["vigor"] + 3


def test_ficha_com_pontos_e_grupo_separado():
    s = sistema(SHINOBI)
    for seed in range(20):
        f = gerar_ficha(s, seed=seed)
        sociais = f.atributos["car"] + f.atributos["man"]
        assert sociais == 2 and sum(f.atributos.values()) - sociais == 12
        assert all(0 <= v <= 4 for v in f.atributos.values())
        assert f.nivel == 4 and not [p for p in validar(s, f) if p.gravidade == "erro"]
    f = gerar_ficha(s, arquetipo="Clã da Folha", seed=2)
    valores = dict((d.nome, v) for d, v in calcular_derivados(s, f.atributos, f.nivel))
    assert valores["Vitalidade"] == 10 + 3 * f.atributos["vig"] + 5 * 4
    assert valores["Reação de Esquiva"] == 3 + f.atributos["agi"] + 9
    assert valores["Iniciativa"] is None
    assert gerar_ficha(s, seed=5) == gerar_ficha(s, seed=5)


def test_ficha_d20_usa_formula_da_classe():
    s = sistema(D20)
    g = gerar_ficha(s, arquetipo="Guerreiro", nivel=3, seed=1)
    assert sorted(g.atributos.values(), reverse=True) == [15, 14, 13, 12, 10, 8]
    mod_con = (g.atributos["con"] - 10) // 2
    valores = dict((d.id, v) for d, v in calcular_derivados(s, g.atributos, 3, "Guerreiro"))
    assert valores["pv"] == 10 + mod_con + 2 * (6 + mod_con)
    assert any("10 + mod_con" in e for e in g.explicacoes)
    with pytest.raises(ValueError):
        gerar_ficha(s, arquetipo="Bardo")


def test_validacao_aponta_faixa_errada():
    s = sistema(SHINOBI)
    f = gerar_ficha(s, seed=1)
    f.atributos["for"] = 9
    assert any("fora da faixa" in p.mensagem for p in validar(s, f))


# --------------------------------------------------------------------------- análises


def test_grupo_e_encontro_com_criaturas_do_livro():
    s = sistema(D20)
    grupo = [
        gerar_ficha(s, arquetipo=a, nivel=3, seed=i)
        for i, a in enumerate(("Guerreiro", "Guerreiro", "Mago"))
    ]
    resumo, achados = analisar_encontro(s, grupo, [(s.criaturas[0], 2)])
    assert resumo.vida_criaturas == 22 and resumo.veredito != "sem dados suficientes"
    assert resumo.dano_criaturas == pytest.approx(7 * 2 * 0.6)  # 2d4+2 → 7, dois lobos
    _, achados_ogro = analisar_encontro(s, grupo, [(s.criaturas[1], 1)])
    assert any("Fúria" in a.detalhe for a in achados_ogro)
    assert analisar_grupo(s, grupo) is not None


def test_encontro_com_inimigos_gerados_pelas_regras():
    s = sistema(SHINOBI)
    grupo = [gerar_ficha(s, seed=i) for i in range(3)]
    inimigos = [criatura_de_ficha(s, gerar_ficha(s, seed=10 + i)) for i in range(2)]
    assert all(c.vida and c.ataques for c in inimigos)
    resumo, achados = analisar_encontro(s, grupo, [(c, 1) for c in inimigos])
    assert resumo.rodadas_para_vencer and resumo.rodadas_para_perder
    assert any("multiplicador" in a.regra for a in achados if a.categoria == "Balanço")


def test_encontro_sem_dados_nao_inventa_numero():
    s = sistema(VAMPIRO)  # sem dano básico nem criaturas com vida
    grupo = [gerar_ficha(s, seed=1)]
    resumo, achados = analisar_encontro(s, grupo, [])
    assert resumo.veredito == "sem dados suficientes"
    assert any(a.titulo == "Estimativa incompleta" for a in achados)


def test_dano_zero_conta_como_dado():
    s = sistema(SHINOBI)
    fraco = gerar_ficha(s, seed=1)
    fraco.atributos["for"] = 0  # teto(0/2) + 0 = 0 de dano: é um número, não "sem dado"
    inimigo = criatura_de_ficha(s, fraco)
    assert inimigo.ataques and inimigo.ataques[0].dano == "0.0"


# --------------------------------------------------------------------------- leitura


class LLMFalso:
    """Responde pelo conteúdo do prompt, como o LLM de verdade faria."""

    def __init__(self, ruim_primeiro: bool = False):
        self.chamadas = []
        self.ruim_primeiro = ruim_primeiro
        self.criacao = 0

    def completar(self, sistema: str, usuario: str, max_tokens: int = 6000) -> str:
        self.chamadas.append(usuario)
        if "Trechos do início" in usuario:
            return json.dumps(
                {
                    "e_livro_de_rpg": True,
                    "nome": "Ninjas 2d8",
                    "resumo": "Um RPG.",
                    "mecanica": SHINOBI["mecanica"],
                }
            )
        if "criação de personagem" in usuario:
            self.criacao += 1
            if self.ruim_primeiro and self.criacao == 1:
                return "Claro! Aqui está um resumo sem JSON."
            corpo = {
                k: SHINOBI[k] for k in ("atributos", "geracao", "derivados", "arquetipos", "niveis")
            }
            corpo["arquetipos"] = [*corpo["arquetipos"], {"sem_nome": True}]
            return f"```json\n{json.dumps(corpo)}\n```"
        return json.dumps(
            {"criaturas": [{"nome": "Lobo", "vida": 10, "ataques": [{"nome": "x", "dano": "1d6"}]}]}
        )


def _paginas() -> list[str]:
    paginas = [f"Página {i}. " + "texto corrido de ambientação " * 30 for i in range(40)]
    paginas[2] = "SUMÁRIO\n" + "\n".join(f"Clã {i} .......... {10 + i}" for i in range(12))
    paginas[10] = "Criação de personagem: distribua pontos nos atributos e perícias. " * 20
    paginas[20] = "Teste: role 2d8, some a precisão e compare com a dificuldade. Dano. " * 20
    paginas[30] = "Bestiário: criaturas e inimigos. Ataque 2d6, vida 12, defesa 8. " * 20
    return paginas


def test_selecao_de_paginas_por_secao():
    sel = selecionar_paginas(_paginas())
    assert 2 in sel["criacao"] and 10 in sel["criacao"]  # sumário vai junto com a criação
    assert 20 in sel["visao"] and 30 in sel["criaturas"]


def test_leitura_completa_com_llm_falso():
    llm = LLMFalso()
    leitura = ler_sistema(_paginas(), llm, "livro.pdf")
    s = leitura.sistema
    assert leitura.e_rpg and s.nome == "Ninjas 2d8" and len(llm.chamadas) == 3
    assert [a.nome for a in s.arquetipos] == ["Clã da Folha", "Clã da Névoa"]
    assert any("Arquétipo ignorado" in a for a in s.avisos)  # item malformado vira aviso
    assert s.criaturas[0].nome == "Lobo" and s.niveis.nivel_inicial == 4


def test_leitura_tenta_de_novo_quando_nao_vem_json():
    llm = LLMFalso(ruim_primeiro=True)
    s = ler_sistema(_paginas(), llm).sistema
    assert len(llm.chamadas) == 4 and s.atributos


def test_leitura_sem_texto_falha_com_mensagem():
    with pytest.raises(ErroLeitura):
        ler_sistema(["", "  "], LLMFalso())


def test_extrair_json():
    assert extrair_json('Resposta: {"a": 1} fim') == {"a": 1}
    with pytest.raises(ValueError):
        extrair_json("sem json")


# --------------------------------------------------------------------------- higiene


def test_codigo_sem_caracteres_de_controle():
    """Regressão: "\\b" já virou backspace num arquivo deste projeto e quebrou um regex."""
    raiz = Path(__file__).parents[1]
    for arquivo in [*raiz.glob("src/**/*.py"), *raiz.glob("app/*.py"), *raiz.glob("tests/*.py")]:
        texto = arquivo.read_text(encoding="utf-8")
        ruins = {hex(ord(c)) for c in texto if ord(c) < 32 and c not in "\n\t\r"}
        assert not ruins, f"{arquivo}: {ruins}"
