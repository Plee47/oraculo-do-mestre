"""Avaliador seguro das fórmulas lidas dos livros ("(CON+TAM)/10", "3d6*5", "2d8+VIG").

As fórmulas vêm de um LLM, então nunca passam por `eval`: o texto vira uma árvore sintática do
Python e só nós da lista permitida são calculados (números, nomes conhecidos, + − × ÷, min,
max, arredondamentos e dados). Qualquer outra coisa vira `ErroFormula`.

Notação de dados: "XdY" (X opcional). Em modo `media`, vale a média (2d8 → 9); com um gerador
aleatório (`rng`), o dado é rolado.
"""

from __future__ import annotations

import ast
import itertools
import math
import operator
import random
import re
import unicodedata

# XdY, com "khN"/"klN" opcional: manter os N maiores/menores ("4d6kh3" = 4d6 descarta o menor)
_RE_DADO = re.compile(
    r"(?<![A-Za-z_0-9])(\d*)\s*[dD]\s*(\d+)(?:\s*(kh|kl)\s*(\d+))?(?![A-Za-z_])", re.I
)
# Vírgula NÃO vira ponto: ela separa argumentos em min(a, b). O prompt pede ponto decimal.
_SUBSTITUICOES = {"×": "*", "÷": "/", "−": "-", "–": "-", "—": "-", "^": "**"}
_BINARIOS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_RE_NOME = re.compile(r"(?<![\w.])[A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ_0-9]*(?![A-Za-zÀ-ÿ_0-9])(?!\s*\()")
_FUNCOES = {
    "min": min,
    "max": max,
    "piso": math.floor,
    "floor": math.floor,
    "teto": math.ceil,
    "ceil": math.ceil,
    "arredondar": round,
    "round": round,
    "abs": abs,
}
LIMITE_DADOS = 100  # "100d100" é aceito; mais que isso é erro de leitura


class ErroFormula(ValueError):
    """A fórmula não pôde ser entendida ou usa algo fora da lista permitida."""


def tem_dado(formula: str) -> bool:
    return bool(_RE_DADO.search(formula or ""))


def normalizar_id(texto: str) -> str:
    """'Força de Vontade' → 'forca_de_vontade' (identificador estável e sem acentos)."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_") or "x"


def _preparar(formula: str) -> str:
    texto = formula.strip()
    # "x" só é multiplicação entre números/fechamento de parêntese e número ("3d6 x 5").
    texto = re.sub(r"(?<=[\d)\s])x(?=\s*[\d(])", "*", texto)
    texto = re.sub(r"(?<=[\d)])\s*[xX](?=\s)", "*", texto)  # "3x Vigor"
    for velho, novo in _SUBSTITUICOES.items():
        texto = texto.replace(velho, novo)

    def dado(m: re.Match) -> str:
        n, faces = m.group(1) or "1", m.group(2)
        if m.group(3):
            sinal = 1 if m.group(3).lower() == "kh" else -1
            return f"_dado({n},{faces},{m.group(4)},{sinal})"
        return f"_dado({n},{faces})"

    texto = _RE_DADO.sub(dado, texto)
    # Todo nome vira "v_<id>": assim "for" (Força) não colide com a palavra reservada do
    # Python e acentos não atrapalham. Funções (nome seguido de "(") ficam como estão.
    return _RE_NOME.sub(lambda m: m.group(0) if m.group(0) == "_dado" else
                        f"v_{normalizar_id(m.group(0))}", texto)  # fmt: skip


def _nomes(variaveis: dict[str, float]) -> dict[str, float]:
    return {normalizar_id(k): v for k, v in variaveis.items()}


def _juntar_frases(formula: str, nomes: dict[str, float]) -> str:
    """'1d8 + Modificador de Força' → '1d8 + modificador_de_forca' quando esse nome existe.

    O LLM escreve nomes de várias palavras; sem isso, viram nomes soltos ("Modificador",
    "de", "Força"). Compara sem acento e sem caixa, do nome mais longo para o mais curto.
    """
    for velho, novo in _SUBSTITUICOES.items():  # antes de tirar acentos: ÷ e × não são ASCII
        formula = formula.replace(velho, novo)
    if not any("_" in n for n in nomes):
        return formula
    texto = unicodedata.normalize("NFKD", formula).encode("ascii", "ignore").decode()
    for nome in sorted((n for n in nomes if "_" in n), key=len, reverse=True):
        partes = [re.escape(p) for p in nome.split("_") if p]
        padrao = r"(?<![A-Za-z0-9_])" + r"[\s_]+".join(partes) + r"(?![A-Za-z0-9_])"
        texto = re.sub(padrao, nome, texto, flags=re.I)
    return texto


def avaliar(
    formula: str,
    variaveis: dict[str, float] | None = None,
    *,
    rng: random.Random | None = None,
) -> float:
    """Calcula a fórmula. Sem `rng`, dados valem a média; com `rng`, são rolados."""
    if not formula or not formula.strip():
        raise ErroFormula("fórmula vazia")
    if len(formula) > 300:
        raise ErroFormula("fórmula longa demais")
    nomes = _nomes(variaveis or {})
    try:
        arvore = ast.parse(_preparar(_juntar_frases(formula, nomes)), mode="eval")
    except SyntaxError as e:
        raise ErroFormula(f"não entendi a fórmula {formula!r}") from e

    def dado(n: float, faces: float, manter: float | None = None, sinal: float = 1) -> float:
        n, faces = int(n), int(faces)
        if not (1 <= n <= LIMITE_DADOS and 2 <= faces <= 1000):
            raise ErroFormula(f"dado fora do limite: {n}d{faces}")
        k = n if manter is None else int(manter)
        if not 1 <= k <= n:
            raise ErroFormula(f"não dá para manter {k} de {n} dados")
        if rng is None:
            return n * (faces + 1) / 2 if k == n else _media_mantendo(n, faces, k, sinal > 0)
        rolagens = sorted((rng.randint(1, faces) for _ in range(n)), reverse=sinal > 0)
        return float(sum(rolagens[:k]))

    def calc(no: ast.AST) -> float:
        if isinstance(no, ast.Expression):
            return calc(no.body)
        if isinstance(no, ast.Constant) and isinstance(no.value, int | float):
            return float(no.value)
        if isinstance(no, ast.BinOp) and type(no.op) in _BINARIOS:
            direita = calc(no.right)
            if isinstance(no.op, ast.Div | ast.FloorDiv | ast.Mod) and direita == 0:
                raise ErroFormula("divisão por zero")
            return float(_BINARIOS[type(no.op)](calc(no.left), direita))
        if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Pow):
            base, exp = calc(no.left), calc(no.right)
            if abs(exp) > 4:
                raise ErroFormula("potência alta demais")
            return float(base**exp)
        if isinstance(no, ast.UnaryOp) and isinstance(no.op, ast.USub | ast.UAdd):
            v = calc(no.operand)
            return -v if isinstance(no.op, ast.USub) else v
        if isinstance(no, ast.Name):
            chave = no.id[2:] if no.id.startswith("v_") else None
            if chave is None or chave not in nomes:
                raise ErroFormula(f"nome desconhecido na fórmula: {(chave or no.id)!r}")
            return float(nomes[chave])
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and not no.keywords:
            nome = no.func.id
            args = [calc(a) for a in no.args]
            if nome == "_dado" and len(args) in (2, 4):
                return dado(*args)
            if nome in _FUNCOES and args:
                return float(_FUNCOES[nome](*args) if nome in ("min", "max") else
                             _FUNCOES[nome](args[0]))  # fmt: skip
        raise ErroFormula(f"trecho não permitido na fórmula {formula!r}")

    return calc(arvore)


def _media_mantendo(n: int, faces: int, k: int, maiores: bool) -> float:
    """Média exata de "manter os k maiores (ou menores) de n dados" por enumeração."""
    if faces**n > 2_000_000:
        raise ErroFormula(f"combinação grande demais para calcular a média: {n}d{faces}")
    total = 0
    for combo in itertools.product(range(1, faces + 1), repeat=n):
        ordenado = sorted(combo, reverse=maiores)
        total += sum(ordenado[:k])
    return total / faces**n


def media(formula: str, variaveis: dict[str, float] | None = None) -> float:
    return avaliar(formula, variaveis)


def rolar(formula: str, rng: random.Random, variaveis: dict[str, float] | None = None) -> float:
    return avaliar(formula, variaveis, rng=rng)


def nomes_desconhecidos(formula: str, variaveis: dict[str, float]) -> list[str]:
    """Nomes da fórmula que não são variáveis conhecidas (ex.: "DanoArma")."""
    conhecidos = set(_nomes(variaveis)) | set(_FUNCOES)
    vistos = []
    juntada = _juntar_frases(formula or "", _nomes(variaveis))
    for m in _RE_NOME.finditer(_RE_DADO.sub("0", juntada)):
        nome = m.group(0)
        if normalizar_id(nome) not in conhecidos and nome not in vistos:
            vistos.append(nome)
    return vistos


def zerar_nomes(formula: str, nomes: list[str]) -> str:
    """Troca nomes por 0 (ex.: o dano da arma, quando se calcula o ataque desarmado)."""
    alvo = {normalizar_id(n) for n in nomes}
    return _RE_NOME.sub(lambda m: "0" if normalizar_id(m.group(0)) in alvo else m.group(0),
                        formula)  # fmt: skip


def valida(formula: str, nomes: set[str]) -> str | None:
    """None se a fórmula for calculável com esses nomes; senão, o motivo."""
    try:
        avaliar(formula, dict.fromkeys(nomes, 10))
    except ErroFormula as e:
        return str(e)
    return None
