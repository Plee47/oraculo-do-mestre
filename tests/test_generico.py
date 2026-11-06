"""Motor genérico: qualquer sistema lido de um livro (fórmulas, normalização, fichas, análises,
leitura com um LLM falso). As especificações abaixo foram escritas para os testes, no formato
de quatro famílias de sistema: rolagem por atributo (Call of Cthulhu), valores fixos
(Vampiro), pontos com grupo separado (sistema 2d8 brasileiro) e d20 com modificador.
"""

import json
import math
import random
from pathlib import Path

import pytest

from oraculo.leitor.cache import CacheMemoria
from oraculo.sistemas.generico.analise import (
    ALVOS_DIFICULDADE,
    analisar_encontro,
    analisar_grupo,
    criatura_de_ficha,
    sugerir_encontro,
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
    detalhar_opcao,
    extrair_json,
    ler_mais_criaturas,
    ler_sistema,
    mapa_do_livro,
    selecionar_paginas,
)
from oraculo.sistemas.generico.modelo import SistemaLido, normalizar
from oraculo.sistemas.generico.narrativa import (
    Narrativa,
    contexto_lido,
    sugerir_narrativa,
)

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
    assert leitura.e_rpg and s.nome == "Ninjas 2d8" and len(llm.chamadas) == 4
    assert [a.nome for a in s.arquetipos] == ["Clã da Folha", "Clã da Névoa"]
    assert any("Arquétipo ignorado" in a for a in s.avisos)  # item malformado vira aviso
    assert s.criaturas[0].nome == "Lobo" and s.niveis.nivel_inicial == 4


def test_leitura_tenta_de_novo_quando_nao_vem_json():
    llm = LLMFalso(ruim_primeiro=True)
    s = ler_sistema(_paginas(), llm).sistema
    assert len(llm.chamadas) == 5 and s.atributos


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


# --------------------------------------------------------------------------- etapas de criação

FANTASIA = {
    **D20,
    "etapas": [
        {"id": "raca", "nome": "Raça", "tipo": "escolha", "opcoes": [
            {"nome": "Anão", "pagina": 10, "bonus_atributos": {"Constituição": 2}},
            {"nome": "Elfo", "pagina": 12, "bonus_atributos": {"DES": 2, "Inexistente": 5}},
        ]},
        {"id": "classe", "nome": "Classe", "tipo": "escolha", "principal": True, "opcoes": [
            {"nome": "Guerreiro", "pagina": 30, "atributos_chave": ["Força", "CON"],
             "papel": "combate", "formulas": {"pv": "10 + mod_con + (nivel-1)*(6+mod_con)"}},
            {"nome": "Mago", "pagina": 50, "atributos_chave": ["Inteligência"], "papel": "magia",
             "formulas": {"Pontos de Vida": "6 + mod_con"}},
        ]},
        {"id": "sub", "nome": "Subclasse", "tipo": "escolha", "depende_de": "classe",
         "nivel_minimo": 3, "opcoes": [
            {"nome": "Campeão", "pai": "Guerreiro"},
            {"nome": "Evocador", "pai": "Mago"},
            {"nome": "Perdida", "pai": "Classe Inventada"},
        ]},
        {"id": "atrib", "nome": "Atributos", "tipo": "atributos"},
    ],
}  # fmt: skip


def test_etapas_normalizadas():
    s = sistema(FANTASIA)
    assert [e.id for e in s.etapas_de_escolha(1)] == ["raca", "classe"]
    assert [e.id for e in s.etapas_de_escolha(3)] == ["raca", "classe", "sub"]
    assert s.etapa_principal().id == "classe"
    assert [a.nome for a in s.arquetipos] == ["Guerreiro", "Mago"]  # espelha a etapa principal
    assert s.etapa("raca").opcao("Elfo").bonus_atributos == {"des": 2}  # atributo inexistente sai
    assert s.etapa("classe").opcao("Mago").formulas == {"pv": "6 + mod_con"}  # nome vira id
    assert s.etapa("sub").opcao("Perdida").pai == ""  # pai inexistente vira aviso
    assert any("Classe Inventada" in a for a in s.avisos)
    assert [o.nome for o in s.etapa("sub").opcoes_de("Mago")] == ["Evocador", "Perdida"]


def test_principal_inferida_quando_o_llm_nao_marca():
    dados = json.loads(json.dumps(FANTASIA))
    dados["etapas"][1]["principal"] = False
    dados["etapas"][1]["nome"] = "Caminho"  # sem nome de classe, vale quem tem mais opções
    dados["etapas"][0]["opcoes"].append({"nome": "Humano"})
    assert sistema(dados).etapa_principal().id == "raca"  # a escolha livre com mais opções


def test_ficha_segue_as_etapas_do_livro():
    s = sistema(FANTASIA)
    f = gerar_ficha(s, nivel=3, seed=1, escolhas={"classe": "Guerreiro", "raca": "Anão"})
    assert f.classe == "Guerreiro"
    assert f.escolhas["raca"] == "Anão" and f.escolhas["sub"] in ("Campeão", "Perdida")
    assert any("Raça: Anão (p. 10), escolha." in e for e in f.explicacoes)
    assert any("Bônus de Anão: +2" in e for e in f.explicacoes)
    assert sum(f.atributos.values()) == sum((15, 14, 13, 12, 10, 8)) + 2
    n1 = gerar_ficha(s, nivel=1, seed=1, escolhas={"classe": "Mago"})
    assert "sub" not in n1.escolhas  # subclasse só a partir do nível 3
    assert f.escolhas != n1.escolhas
    assert not [p for p in validar(s, f) if p.gravidade == "erro"]


def test_opcao_filha_respeita_a_opcao_pai():
    s = sistema(FANTASIA)
    for seed in range(15):
        f = gerar_ficha(s, nivel=3, seed=seed, escolhas={"classe": "Mago"})
        assert f.escolhas["sub"] in ("Evocador", "Perdida")


def test_pedido_invalido_para_a_classe_e_sorteado_de_novo():
    s = sistema(FANTASIA)
    f = gerar_ficha(s, nivel=3, seed=2, escolhas={"classe": "Mago", "sub": "Campeão"})
    assert f.escolhas["sub"] != "Campeão"


class LLMDetalhe:
    def __init__(self):
        self.prompts = []

    def completar(self, sistema, usuario, max_tokens=6000, pequeno=False):
        self.prompts.append(usuario)
        return json.dumps({
            "descricao": "Combatente treinado.",
            "atributos_chave": ["Destreza"],
            "bonus_atributos": {"Força": 1},
            "pericias": ["Atletismo"],
            "equipamento": ["Espada"],
            "dano_tipico": "1d8+mod_for",
            "habilidades": [
                {"nome": "Retomar o Fôlego", "resumo": "Recupera PV.", "nivel": 1, "pagina": 31},
                {"nome": "Ataque Extra", "nivel": 5, "pagina": 32},
                {"sem_nome": True},
            ],
            "poderes": ["Golpe"],
            "subopcoes": [{"nome": "Mestre de Batalha", "descricao": "Táticas."}],
        })  # fmt: skip


def _livro_fantasia() -> list[str]:
    paginas = [f"Página {i}. " + "texto corrido de ambientação " * 30 for i in range(40)]
    paginas[29] = "Guerreiro: classe de combate. Guerreiro usa armas e armaduras. " * 20
    return paginas


def test_leitura_a_fundo_de_uma_opcao():
    s = sistema(FANTASIA)
    llm, cache = LLMDetalhe(), CacheMemoria()
    o = detalhar_opcao(s, "classe", "Guerreiro", _livro_fantasia(), llm, cache)
    assert o.detalhada and o.descricao == "Combatente treinado."
    assert o.atributos_chave == ["des"] and o.bonus_atributos == {"for": 1}
    assert [h.nome for h in o.habilidades_detalhe] == ["Retomar o Fôlego", "Ataque Extra"]
    assert "=== PÁGINA 30 ===" in llm.prompts[0]  # a página citada na estrutura vai junto
    assert s.etapa("sub").opcao("Mestre de Batalha").pai == "Guerreiro"  # subopção achada
    assert s.arquetipo("Guerreiro").dano_tipico == "1d8+mod_for"
    # segunda vez: já detalhada, nenhuma chamada
    detalhar_opcao(s, "classe", "Guerreiro", _livro_fantasia(), llm, cache)
    assert len(llm.prompts) == 1
    # outra sessão, mesmo livro: vem do cache, nenhuma chamada
    outra = sistema(FANTASIA)
    detalhar_opcao(outra, "classe", "Guerreiro", _livro_fantasia(), llm, cache)
    assert len(llm.prompts) == 1 and outra.etapa("classe").opcao("Guerreiro").detalhada
    # a ficha passa a usar o que foi lido
    f = gerar_ficha(s, seed=1, nivel=1, escolhas={"classe": "Guerreiro"})
    assert "Espada" in f.equipamento and "Retomar o Fôlego" in f.poderes and "Golpe" in f.poderes
    assert "Atletismo" in f.pericias


def test_opcao_desconhecida_da_erro():
    with pytest.raises(ValueError):
        detalhar_opcao(sistema(FANTASIA), "classe", "Bardo", _livro_fantasia(), LLMDetalhe())


# --------------------------------------------------------------------------- encontros


def _grupo_d20(s):
    return [
        gerar_ficha(s, arquetipo=a, nivel=3, seed=i)
        for i, a in enumerate(("Guerreiro", "Guerreiro", "Mago"))
    ]


@pytest.mark.parametrize("dificuldade", ["fácil", "equilibrado", "difícil"])
def test_sugestao_fica_perto_da_dificuldade_pedida(dificuldade):
    s = sistema(D20)
    s.criaturas += sistema(
        {
            "nome": "x",
            "criaturas": [
                {"nome": "Rato", "vida": 2, "ataques": [{"nome": "Mordida", "dano": "1d2"}]},
                {"nome": "Urso", "vida": 34, "ataques": [{"nome": "Garra", "dano": "2d6+4"}]},
            ],
        }
    ).criaturas
    sug = sugerir_encontro(s, _grupo_d20(s), dificuldade)
    assert sug.origem == "livro" and sug.criaturas
    razao = sug.resumo.rodadas_para_perder / sug.resumo.rodadas_para_vencer
    assert abs(math.log(razao / ALVOS_DIFICULDADE[dificuldade])) < 0.5


def test_dificuldades_ficam_em_ordem():
    s = sistema(D20)
    razoes = []
    for d in ("fácil", "equilibrado", "difícil"):
        r = sugerir_encontro(s, _grupo_d20(s), d).resumo
        razoes.append(r.rodadas_para_perder / r.rodadas_para_vencer)
    assert razoes[0] > razoes[1] > razoes[2]


def test_sem_criaturas_usa_inimigos_pelas_regras():
    s = sistema(SHINOBI)
    grupo = [gerar_ficha(s, seed=i) for i in range(3)]
    sug = sugerir_encontro(s, grupo)
    assert sug is not None and sug.origem == "regras"
    assert all("PdM" in c.nome for c, _ in sug.criaturas)


def test_sem_numeros_nao_inventa_sugestao():
    s = sistema(VAMPIRO)  # sem dano básico
    assert sugerir_encontro(s, [gerar_ficha(s, seed=1)]) is None
    with pytest.raises(ValueError):
        sugerir_encontro(sistema(D20), [], "impossível")


def test_ler_mais_criaturas_nao_repete_e_guarda():
    class LLMCriaturas:
        chamadas = 0

        def completar(self, sistema, usuario, max_tokens=6000, pequeno=False):
            type(self).chamadas += 1
            return json.dumps(
                {
                    "criaturas": [
                        {"nome": "Lobo", "vida": 11},  # já conhecida
                        {"nome": "Grifo", "vida": 59, "atributos": {"FOR": 18}, "pagina": 21},
                        {"sem_nome": True},
                    ]
                }
            )

    paginas = [f"Página {i}. " + "texto de ambientação " * 30 for i in range(30)]
    paginas[20] = "Bestiário: criaturas, monstros, ataque e pontos de vida. " * 20
    s, cache = sistema(D20), CacheMemoria()
    s.paginas_fonte["criaturas"] = []
    assert ler_mais_criaturas(s, paginas, LLMCriaturas(), cache) == 1
    assert [c.nome for c in s.criaturas].count("Lobo") == 1
    grifo = next(c for c in s.criaturas if c.nome == "Grifo")
    assert grifo.atributos == {"for": 18} and 21 in s.paginas_fonte["criaturas"]
    assert LLMCriaturas.chamadas == 1
    # as páginas já lidas não voltam: o próximo lote é outro
    antes = set(s.paginas_fonte["criaturas"])
    ler_mais_criaturas(s, paginas, LLMCriaturas(), cache)
    assert set(s.paginas_fonte["criaturas"]) >= antes


# --------------------------------------------------------------------------- narrativa


class LLMNarrativa:
    def __init__(self, resposta=None):
        self.usuario = ""
        self.pequeno = None
        self.resposta = resposta

    def completar(self, sistema, usuario, max_tokens=6000, pequeno=False):
        self.usuario, self.pequeno = usuario, pequeno
        return self.resposta or json.dumps(
            {
                "aparencia": "Alta, com cicatrizes.",
                "personalidade": "Teimosa.",
                "historia": "Cresceu no norte.",
                "gancho": "Procura o irmão.",
                "assinatura_rotulo": "Técnica",
                "assinatura_nome": "Corte Duplo",
                "assinatura_descricao": "Dois golpes rápidos.",
            }
        )


def test_narrativa_usa_as_escolhas_o_status_e_o_livro():
    s = sistema(FANTASIA)
    s.etapa("classe").opcao("Guerreiro").descricao = "Combatente treinado."
    f = gerar_ficha(s, nivel=3, seed=1, escolhas={"classe": "Guerreiro", "raca": "Anão"})
    llm = LLMNarrativa()
    n = sugerir_narrativa(contexto_lido(s, f), f, llm, _livro_fantasia())
    assert llm.pequeno  # modelo pequeno: menos cota
    assert "Classe: Guerreiro" in llm.usuario and "Raça: Anão" in llm.usuario
    assert "Combatente treinado." in llm.usuario
    assert f"Força {f.atributos['for']}" in llm.usuario
    assert "=== PÁGINA 30 ===" in llm.usuario  # trecho do livro sobre a escolha
    campos = n.para_ficha()
    assert campos["Aparência"] == "Alta, com cicatrizes."
    assert campos["Técnica"] == "Corte Duplo: Dois golpes rápidos."


def test_narrativa_ruim_nao_vira_ficha():
    s = sistema(FANTASIA)
    f = gerar_ficha(s, seed=1)
    for resposta in ("sem json nenhum", json.dumps({"aparencia": None})):
        with pytest.raises(ErroLeitura):
            sugerir_narrativa(contexto_lido(s, f), f, LLMNarrativa(resposta))


def test_narrativa_sem_rotulo_e_sem_campos_vazios():
    n = Narrativa(aparencia="x", assinatura_nome="Golpe", gancho=None)
    assert n.para_ficha() == {"Aparência": "x", "Assinatura": "Golpe"}


# --------------------------------------------------------------- regressões do livro real


def test_dano_negativo_vira_zero_e_nao_quebra_a_sugestao():
    dados = json.loads(json.dumps(D20))
    dados["mecanica"]["dano_basico"] = "0 + Modificador de Força"
    s = sistema(dados)
    fracos = [gerar_ficha(s, arquetipo="Mago", seed=i) for i in range(2)]
    for f in fracos:
        f.atributos["for"] = 6
    sug = sugerir_encontro(s, fracos)  # grupo sem dano: não há como estimar
    assert sug is None


def test_classe_ganha_de_raca_como_etapa_principal():
    s = sistema(
        {
            "nome": "x",
            "etapas": [
                {
                    "id": "raca",
                    "nome": "Raça",
                    "tipo": "escolha",
                    "principal": True,
                    "opcoes": [{"nome": f"R{i}"} for i in range(9)],
                },
                {"id": "classe", "nome": "Classe", "tipo": "escolha", "opcoes": [{"nome": "Mago"}]},
            ],
        }
    )
    assert s.etapa_principal().id == "classe"
    assert not s.etapa("raca").principal


def test_formula_acha_o_valor_pelo_tipo():
    s = sistema(
        {
            "nome": "x",
            "atributos": [{"id": "con", "nome": "Constituição"}],
            "derivados": [
                {"nome": "Pontos de Vida Máximos", "formula": ""},
                {"nome": "Defesa", "formula": "10"},
            ],
            "etapas": [
                {
                    "nome": "Classe",
                    "tipo": "escolha",
                    "opcoes": [
                        {"nome": "Mago", "formulas": {"PV_max": "6 + con"}},
                        {"nome": "Bardo", "formulas": {"PV": "8 + con"}},
                        {"nome": "Monge", "formulas": {"Mana": "1"}},  # não existe esse valor
                    ],
                }
            ],
        }
    )
    e = s.etapa_principal()
    assert e.opcao("Mago").formulas == {"pontos_de_vida_maximos": "6 + con"}
    assert e.opcao("Bardo").formulas == {"pontos_de_vida_maximos": "8 + con"}
    assert e.opcao("Monge").formulas == {}


def test_sem_faixa_em_sistema_d20_usa_a_escala_do_modificador():
    s = sistema(
        {
            "nome": "x",
            "modificador": "piso((valor-10)/2)",
            "atributos": [{"nome": n} for n in ("Força", "Destreza", "Vigor")],
        }
    )
    f = gerar_ficha(s, seed=1)
    assert sorted(f.atributos.values(), reverse=True) == [15, 14, 13]
    assert any("valores típicos" in e for e in f.explicacoes)


def test_mapa_do_livro_lista_titulos_e_ignora_cabecalhos():
    paginas = [
        f"CABEÇALHO\nParágrafo corrido que termina com ponto final.\nTítulo {i}\n"
        for i in range(30)
    ]
    paginas[7] = "CABEÇALHO\nPaladin\nClass Features\ntexto muito longo " + "palavra " * 40
    mapa = mapa_do_livro(paginas)
    assert "p.8: Paladin | Class Features" in mapa
    assert "CABEÇALHO" not in mapa and "Parágrafo" not in mapa


def test_pericias_e_equipamento_nao_sao_escolhas_da_ficha():
    s = sistema(
        {
            "nome": "x",
            "etapas": [
                {
                    "id": "classe",
                    "nome": "Classe",
                    "tipo": "escolha",
                    "opcoes": [{"nome": "Monge"}],
                },
                {
                    "id": "skills",
                    "nome": "Class Skills",
                    "tipo": "escolha",
                    "depende_de": "classe",
                    "opcoes": [{"nome": "Monge Skills", "pai": "Monge"}],
                },
                {
                    "id": "equip",
                    "nome": "Equipamento",
                    "tipo": "escolha",
                    "opcoes": [{"nome": "Kit"}],
                },
            ],
        }
    )
    assert [e.id for e in s.etapas_de_escolha(1)] == ["classe"]
    assert s.etapa("skills").tipo == "pericias" and s.etapa("equip").tipo == "equipamento"


def test_sugestao_aceita_personagem_sem_dano_se_o_grupo_causa_dano():
    s = sistema(SHINOBI)
    grupo = [gerar_ficha(s, seed=i) for i in range(3)]
    grupo[0].atributos["for"] = 0
    grupo[1].atributos["for"] = 4
    assert sugerir_encontro(s, grupo) is not None


class LLMComLacunas:
    """Primeira leitura sem dano e sem vida; a segunda, só das lacunas, traz as duas."""

    def __init__(self):
        self.lacunas = 0

    def completar(self, sistema, usuario, max_tokens=6000, pequeno=False):
        if "Faltam estas regras" in usuario:
            self.lacunas += 1
            return json.dumps(
                {
                    "dano_basico": "1d6 + mod_forca",
                    "dano_explicacao": "Dano da arma + Força.",
                    "vida_por_opcao": {"Lutador": "12 + mod_vigor", "Inventada": "1"},
                }
            )
        if "Trechos do início" in usuario:
            return json.dumps(
                {"e_livro_de_rpg": True, "nome": "Jogo", "mecanica": {"dado_base": "1d20"}}
            )
        if "ESTRUTURA" in usuario:
            return json.dumps(
                {
                    "etapas": [
                        {
                            "nome": "Classe",
                            "tipo": "escolha",
                            "opcoes": [
                                {"nome": "Lutador"},
                                {"nome": "Mago", "formulas": {"Vida": "6 + mod_vigor"}},
                            ],
                        }
                    ]
                }
            )
        if "criação de personagem" in usuario:
            return json.dumps(
                {
                    "modificador": "piso((valor-10)/2)",
                    "atributos": [
                        {"id": "forca", "nome": "Força"},
                        {"id": "vigor", "nome": "Vigor"},
                    ],
                    "derivados": [{"nome": "Vida", "formula": ""}],
                }
            )
        return "{}"


def test_segunda_leitura_so_preenche_o_que_falta():
    llm = LLMComLacunas()
    s = ler_sistema(_paginas(), llm).sistema
    assert llm.lacunas == 1 and s.mecanica.dano_basico == "1d6 + mod_forca"
    classe = s.etapa_principal()
    assert classe.opcao("Lutador").formulas == {"vida": "12 + mod_vigor"}
    assert classe.opcao("Mago").formulas == {"vida": "6 + mod_vigor"}  # a da 1ª leitura fica
    assert "lacunas" in s.paginas_fonte
    f = gerar_ficha(s, arquetipo="Lutador", seed=1)
    vida = dict((d.nome, v) for d, v in calcular_derivados(s, f.atributos, 1, f.classe))["Vida"]
    assert vida == 12 + (f.atributos["vigor"] - 10) // 2


def test_sem_lacunas_nao_gasta_chamada_extra():
    llm = LLMFalso()
    ler_sistema(_paginas(), llm)
    assert not [c for c in llm.chamadas if "Faltam estas regras" in c]
