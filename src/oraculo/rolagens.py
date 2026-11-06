"""Rolagem de dados e probabilidades: notação completa, sem `eval`.

Notação (maiúsculas ou minúsculas, com ou sem espaços):

    2d6+3            soma, subtração, *, / (arredonda para baixo) e parênteses
    d%  dF           dado de 100 faces; dado Fudge (-1, 0, +1)
    4d6kh3  2d20kl1  mantém os maiores / os menores (também dh e dl, que descartam)
    vant  desv       vantagem e desvantagem (2d20kh1 e 2d20kl1)
    3d6!  3d6!>=5    explode: rola de novo no valor máximo (ou na condição)
    2d6r1  2d6rr<=2  rola de novo uma vez (r) ou até sair da condição (rr)
    5d10>=8  5d10>=8f1  conta sucessos (e desconta as falhas em f)
    max(1,1d4-2)     também min, piso e teto
    1d20+5, 2d6+3    várias rolagens de uma vez; 6#4d6kh3 repete a mesma seis vezes

A distribuição de uma expressão é exata sempre que dá para calcular com pouco processamento; quando
não dá (sucessos com explosão, ou contas grandes demais), vem de uma simulação e diz isso.
"""

from __future__ import annotations

import itertools
import math
import random
import re
from dataclasses import dataclass, field

LIMITE_TEXTO = 300
LIMITE_DADOS = 1000  # em toda a expressão
LIMITE_FACES = 100_000
LIMITE_PROFUNDIDADE = 20
LIMITE_REPETICOES = 100
LIMITE_EXPRESSOES = 10
LIMITE_EXPLOSOES = 20  # por dado: um d2! não pode rolar para sempre
LIMITE_REROLAGENS = 1000
_LIMITE_CONTAS = 3_000_000  # contas da distribuição exata antes de partir para a simulação
_LIMITE_VALORES = 20_000
_LIMITE_COMBINACOES = 50_000
_PODA = 1e-15
SIMULACOES = 50_000
_ORCAMENTO_SIMULACAO = 2_000_000  # dados rolados no total: mantém a simulação em cerca de 1 s


class ErroRolagem(ValueError):
    """A expressão não pôde ser lida ou calculada. A mensagem é para quem digitou."""


class _SemExata(Exception):
    """Sem distribuição exata razoável: simula."""


Condicao = tuple[str, int]
_COMPARAR = {
    ">=": lambda v, n: v >= n,
    "<=": lambda v, n: v <= n,
    ">": lambda v, n: v > n,
    "<": lambda v, n: v < n,
    "=": lambda v, n: v == n,
}


def _vale(c: Condicao, v: int) -> bool:
    return _COMPARAR[c[0]](v, c[1])


def _dividir(a: int, b: int) -> int:
    if b == 0:
        raise ErroRolagem("A conta divide por zero.")
    return a // b


_BINARIOS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": _dividir,
}
_FUNCOES_UM = {"piso": "piso", "floor": "piso", "teto": "teto", "ceil": "teto"}
_FUNCOES_VARIOS = {"min": min, "max": max}


# --------------------------------------------------------------------------- árvore
@dataclass(frozen=True)
class _Numero:
    valor: int


@dataclass(frozen=True)
class _Binario:
    op: str
    a: object
    b: object


@dataclass(frozen=True)
class _Negativo:
    a: object


@dataclass(frozen=True)
class _Parenteses:
    a: object


@dataclass(frozen=True)
class _Divisao:
    """piso() e teto() de uma divisão: o único caso em que o arredondamento muda algo."""

    teto: bool
    a: object
    b: object


@dataclass(frozen=True)
class _Funcao:
    nome: str
    args: tuple


@dataclass(frozen=True)
class _Dado:
    n: int
    faces: tuple[int, ...]
    notacao: str
    manter: tuple[str, int] | None = None  # ("h" | "l", quantos ficam)
    explode: Condicao | None = None
    rerolar: Condicao | None = None
    sempre: bool = False  # rr: rola de novo até sair da condição
    sucesso: Condicao | None = None
    falha: Condicao | None = None


# --------------------------------------------------------------------------- leitura
_RE_ESPACO = re.compile(r"\s+")
_RE_DADO = re.compile(r"(\d*)d(\d+|%|f)")
_RE_NUMERO = re.compile(r"\d+")
_RE_NOME = re.compile(r"[a-z]+")
_RE_MANTER = re.compile(r"(kh|kl|dh|dl|k)(\d*)")
_RE_COND = re.compile(r"(>=|<=|>|<|=)?(\d+)")
_RE_SUCESSO = re.compile(r"(>=|<=|>|<)(\d+)")
_ATALHOS = {
    "vant": "2d20kh1", "adv": "2d20kh1", "vantagem": "2d20kh1",
    "desv": "2d20kl1", "dis": "2d20kl1", "desvantagem": "2d20kl1",
}  # fmt: skip


class _Leitor:
    def __init__(self, texto: str) -> None:
        self.t = texto
        self.i = 0
        self.fundura = 0
        self.dados = 0

    def _ve(self, c: str) -> bool:
        return self.t.startswith(c, self.i)

    def _erro(self, msg: str) -> ErroRolagem:
        return ErroRolagem(f'{msg} (perto de "{self.t[self.i : self.i + 8]}")')

    def tudo(self) -> object:
        no = self._soma()
        if self.i < len(self.t):
            if self.t[self.i] in "<>=":
                raise ErroRolagem(
                    "Comparação só vale logo depois do dado (5d10>=8). Para saber a chance de um "
                    "total atingir um alvo, use a aba Probabilidades."
                )
            raise self._erro("Não entendi esta parte")
        return no

    def _soma(self) -> object:
        no = self._produto()
        while self.i < len(self.t) and self.t[self.i] in "+-":
            op = self.t[self.i]
            self.i += 1
            no = _Binario(op, no, self._produto())
        return no

    def _produto(self) -> object:
        no = self._fator()
        while self.i < len(self.t) and self.t[self.i] in "*/":
            op = self.t[self.i]
            self.i += 1
            no = _Binario(op, no, self._fator())
        return no

    def _fator(self) -> object:
        if self._ve("-"):
            self.i += 1
            return _Negativo(self._fator())
        if self._ve("+"):
            self.i += 1
            return self._fator()
        return self._atomo()

    def _dentro(self) -> object:
        self.fundura += 1
        if self.fundura > LIMITE_PROFUNDIDADE:
            raise ErroRolagem("Parênteses demais nessa expressão.")
        no = self._soma()
        self.fundura -= 1
        return no

    def _fecha(self) -> None:
        if not self._ve(")"):
            raise self._erro("Faltou fechar um parêntese")
        self.i += 1

    def _atomo(self) -> object:
        if self.i >= len(self.t):
            raise ErroRolagem("A expressão terminou no meio de uma conta.")
        if self._ve("("):
            self.i += 1
            no = self._dentro()
            self._fecha()
            return _Parenteses(no)
        achado = _RE_DADO.match(self.t, self.i)
        if achado:
            self.i = achado.end()
            return self._dado(achado.group(1), achado.group(2), achado.group(0))
        nome = _RE_NOME.match(self.t, self.i)
        if nome:
            return self._nome(nome)
        numero = _RE_NUMERO.match(self.t, self.i)
        if numero:
            self.i = numero.end()
            if len(numero.group(0)) > 9:
                raise ErroRolagem("Número grande demais.")
            return _Numero(int(numero.group(0)))
        raise self._erro("Não entendi esta parte")

    def _nome(self, achado: re.Match) -> object:
        nome = achado.group(0)
        if nome in _ATALHOS:
            self.i = achado.end()
            feito = _Leitor(_ATALHOS[nome])
            no = feito.tudo()
            self._conta_dados(feito.dados)
            return no
        if nome not in _FUNCOES_UM and nome not in _FUNCOES_VARIOS:
            raise self._erro("Não conheço este nome")
        self.i = achado.end()
        if not self._ve("("):
            raise self._erro(f"Depois de {nome} vem um parêntese")
        self.i += 1
        args = [self._dentro()]
        while self._ve(","):
            self.i += 1
            args.append(self._dentro())
        self._fecha()
        if nome in _FUNCOES_VARIOS:
            return _Funcao(nome, tuple(args))
        if len(args) != 1:
            raise ErroRolagem(f"{nome} recebe uma conta só.")
        return self._arredondar(_FUNCOES_UM[nome], args[0])

    @staticmethod
    def _arredondar(nome: str, a: object) -> object:
        """As contas são inteiras: arredondar só muda algo numa divisão."""
        alvo = a.a if isinstance(a, _Parenteses) else a
        if isinstance(alvo, _Binario) and alvo.op == "/":
            return _Divisao(nome == "teto", alvo.a, alvo.b)
        return a

    def _conta_dados(self, n: int) -> None:
        self.dados += n
        if self.dados > LIMITE_DADOS:
            raise ErroRolagem(f"No máximo {LIMITE_DADOS} dados numa expressão.")

    def _dado(self, qtd: str, faces_txt: str, notacao: str) -> _Dado:
        n = int(qtd) if qtd else 1
        if len(qtd) > 6 or n < 1:
            raise ErroRolagem(f"A quantidade de dados em {notacao} precisa estar entre 1 e "
                              f"{LIMITE_DADOS}.")  # fmt: skip
        self._conta_dados(n)
        if faces_txt == "f":
            faces = (-1, 0, 1)
        elif faces_txt == "%":
            faces = tuple(range(1, 101))
        else:
            if len(faces_txt) > 6 or not 2 <= int(faces_txt) <= LIMITE_FACES:
                raise ErroRolagem(f"As faces em {notacao} precisam estar entre 2 e {LIMITE_FACES}.")
            faces = tuple(range(1, int(faces_txt) + 1))
        inicio = self.i
        campos: dict = {}

        def uma_vez(chave: str, valor: object) -> None:
            if chave in campos:
                raise self._erro(f"Regra repetida em {notacao}")
            campos[chave] = valor

        while self.i < len(self.t):
            if self._ve("!"):
                self.i += 1
                cond = _RE_COND.match(self.t, self.i)
                if cond and cond.group(1):
                    self.i = cond.end()
                    uma_vez("explode", (cond.group(1), int(cond.group(2))))
                else:
                    uma_vez("explode", ("=", faces[-1]))
                continue
            manter = _RE_MANTER.match(self.t, self.i)
            if manter:
                self.i = manter.end()
                k = int(manter.group(2) or 1)
                tipo = manter.group(1)
                if k < 1 or k > n or (tipo in ("dh", "dl") and k >= n):
                    raise ErroRolagem(f"{notacao}{manter.group(0)} não deixa dados válidos.")
                if tipo in ("kh", "k"):
                    uma_vez("manter", ("h", k))
                elif tipo == "kl":
                    uma_vez("manter", ("l", k))
                elif tipo == "dh":
                    uma_vez("manter", ("l", n - k))
                else:
                    uma_vez("manter", ("h", n - k))
                continue
            if self._ve("r"):
                self.i += 1
                sempre = self._ve("r")
                if sempre:
                    self.i += 1
                cond = _RE_COND.match(self.t, self.i)
                if not cond:
                    raise self._erro(f"Depois de r, diga qual valor rola de novo em {notacao}")
                self.i = cond.end()
                uma_vez("rerolar", (cond.group(1) or "=", int(cond.group(2))))
                campos["sempre"] = sempre
                continue
            sucesso = _RE_SUCESSO.match(self.t, self.i)
            if sucesso:
                self.i = sucesso.end()
                uma_vez("sucesso", (sucesso.group(1), int(sucesso.group(2))))
                continue
            if self._ve("f") and "sucesso" in campos:
                self.i += 1
                cond = _RE_COND.match(self.t, self.i)
                if not cond:
                    raise self._erro(f"Depois de f, diga qual valor é falha em {notacao}")
                self.i = cond.end()
                uma_vez("falha", (cond.group(1) or "=", int(cond.group(2))))
                continue
            break
        for chave, rotulo in (("explode", "explode"), ("rerolar", "rola de novo")):
            cond = campos.get(chave)
            if cond and all(_vale(cond, f) for f in faces):
                raise ErroRolagem(f"Em {notacao}, toda face {rotulo}: a rolagem nunca terminaria.")
        return _Dado(n, faces, notacao + self.t[inicio : self.i], **campos)


def _normalizar(texto: str) -> str:
    saida = _RE_ESPACO.sub("", str(texto)).lower()
    for velho, novo in (("×", "*"), ("÷", "/"), ("−", "-"), ("–", "-"), ("—", "-"), ("≥", ">="),
                        ("≤", "<="), ("==", "=")):  # fmt: skip
        saida = saida.replace(velho, novo)
    # "2x3" é multiplicação; o x de "2x" antes de número ou parêntese.
    return re.sub(r"(?<=[\d)])x(?=[\d(])", "*", saida)


def _partes(texto: str) -> list[str]:
    """Separa por vírgula, menos as vírgulas dentro de max(a,b)."""
    partes, atual, fundura = [], "", 0
    for c in texto:
        fundura += (c == "(") - (c == ")")
        if c == "," and fundura == 0:
            partes.append(atual)
            atual = ""
        else:
            atual += c
    partes.append(atual)
    return partes


@dataclass(frozen=True)
class Expressao:
    texto: str
    arvore: object
    dados: int


def ler(texto: str) -> list[tuple[Expressao, int]]:
    """Cada expressão e quantas vezes repetir. Levanta `ErroRolagem` com uma mensagem clara."""
    limpo = _normalizar(texto)
    if not limpo:
        raise ErroRolagem("Escreva uma rolagem, como 1d20+5.")
    if len(limpo) > LIMITE_TEXTO:
        raise ErroRolagem(f"Expressão longa demais (limite de {LIMITE_TEXTO} caracteres).")
    partes = _partes(limpo)
    if len(partes) > LIMITE_EXPRESSOES:
        raise ErroRolagem(f"No máximo {LIMITE_EXPRESSOES} rolagens de uma vez.")
    saida = []
    for parte in partes:
        vezes = 1
        achado = re.match(r"(\d+)#(.*)$", parte)
        if achado:
            vezes = int(achado.group(1)) if len(achado.group(1)) < 6 else LIMITE_REPETICOES + 1
            parte = achado.group(2)
            if not 1 <= vezes <= LIMITE_REPETICOES:
                raise ErroRolagem(f"Repita de 1 a {LIMITE_REPETICOES} vezes.")
        leitor = _Leitor(parte)
        saida.append((Expressao(parte, leitor.tudo(), leitor.dados), vezes))
    return saida


def ler_uma(texto: str) -> Expressao:
    """Para as contas de probabilidade, que valem para uma expressão só."""
    lidas = ler(texto)
    if len(lidas) > 1 or lidas[0][1] > 1:
        raise ErroRolagem("Aqui vale uma rolagem só, sem vírgula nem repetição (#).")
    return lidas[0][0]


# --------------------------------------------------------------------------- rolar
@dataclass(frozen=True)
class DadoRolado:
    valor: int
    mantido: bool = True
    explosao: bool = False  # veio de uma explosão
    rerolado_de: int | None = None
    resultado: str = ""  # "sucesso" | "falha", na contagem de sucessos
    extremo: str = ""  # "max" | "min": o dado caiu na maior ou na menor face


@dataclass(frozen=True)
class GrupoRolado:
    notacao: str
    dados: tuple[DadoRolado, ...]
    total: int


@dataclass(frozen=True)
class Rolagem:
    expressao: str
    total: int
    detalhe: str
    grupos: tuple[GrupoRolado, ...] = field(default=())


def _uma_face(no: _Dado, rng: random.Random) -> int:
    return no.faces[rng.randrange(len(no.faces))]


def _rolar_dado(no: _Dado, rng: random.Random) -> GrupoRolado:
    brutos: list[tuple[int, bool, int | None]] = []
    for _ in range(no.n):
        v = _uma_face(no, rng)
        antes = None
        if no.rerolar and _vale(no.rerolar, v):
            antes = v
            v = _uma_face(no, rng)
            voltas = 0
            while no.sempre and _vale(no.rerolar, v) and voltas < LIMITE_REROLAGENS:
                v = _uma_face(no, rng)
                voltas += 1
        brutos.append((v, False, antes))
        atual, explosoes = v, 0
        while no.explode and _vale(no.explode, atual) and explosoes < LIMITE_EXPLOSOES:
            atual = _uma_face(no, rng)
            explosoes += 1
            brutos.append((atual, True, None))
    mantidos = set(range(len(brutos)))
    if no.manter:
        lado, k = no.manter
        ordem = sorted(range(len(brutos)), key=lambda i: brutos[i][0], reverse=lado == "h")
        mantidos = set(ordem[:k])
    dados = []
    total = 0
    for i, (v, explosao, antes) in enumerate(brutos):
        mantido = i in mantidos
        resultado = ""
        if mantido:
            if no.sucesso:
                if _vale(no.sucesso, v):
                    resultado, total = "sucesso", total + 1
                elif no.falha and _vale(no.falha, v):
                    resultado, total = "falha", total - 1
            else:
                total += v
        extremo = "max" if v == no.faces[-1] else "min" if v == no.faces[0] else ""
        dados.append(DadoRolado(v, mantido, explosao, antes, resultado, extremo))
    return GrupoRolado(no.notacao, tuple(dados), total)


def _executar(no: object, rng: random.Random, grupos: list[GrupoRolado]) -> tuple[int, str]:
    if isinstance(no, _Numero):
        return no.valor, str(no.valor)
    if isinstance(no, _Dado):
        g = _rolar_dado(no, rng)
        grupos.append(g)
        valores = ", ".join(str(d.valor) if d.mantido else f"~{d.valor}" for d in g.dados)
        return g.total, f"{g.notacao}[{valores}]"
    if isinstance(no, _Parenteses):
        v, t = _executar(no.a, rng, grupos)
        return v, f"({t})"
    if isinstance(no, _Negativo):
        v, t = _executar(no.a, rng, grupos)
        return -v, f"-{t}"
    if isinstance(no, _Binario):
        a, ta = _executar(no.a, rng, grupos)
        b, tb = _executar(no.b, rng, grupos)
        return _BINARIOS[no.op](a, b), f"{ta} {no.op} {tb}"
    if isinstance(no, _Divisao):
        a, ta = _executar(no.a, rng, grupos)
        b, tb = _executar(no.b, rng, grupos)
        nome = "teto" if no.teto else "piso"
        return _divisao(a, b, no.teto), f"{nome}({ta} / {tb})"
    if isinstance(no, _Funcao):
        partes = [_executar(a, rng, grupos) for a in no.args]
        textos = ", ".join(t for _, t in partes)
        return _FUNCOES_VARIOS[no.nome](v for v, _ in partes), f"{no.nome}({textos})"
    raise ErroRolagem("Expressão inválida.")


def _divisao(a: int, b: int, teto: bool) -> int:
    if b == 0:
        raise ErroRolagem("A conta divide por zero.")
    return -((-a) // b) if teto else a // b


def rolar_expressao(e: Expressao, rng: random.Random) -> Rolagem:
    grupos: list[GrupoRolado] = []
    total, detalhe = _executar(e.arvore, rng, grupos)
    return Rolagem(e.texto, total, detalhe, tuple(grupos))


def rolar(texto: str, rng: random.Random | None = None) -> list[Rolagem]:
    """Rola tudo o que a expressão pede: "1d20+5, 2d6+3" ou "6#4d6kh3"."""
    rng = rng or random.SystemRandom()
    saida = []
    for expressao, vezes in ler(texto):
        saida += [rolar_expressao(expressao, rng) for _ in range(vezes)]
    return saida


def montar(quantidade: int, faces: str | int, modificador: int = 0, modo: str = "normal") -> str:
    """Escreve a expressão do construtor: vantagem é rolar um dado a mais e ficar com os maiores."""
    dado = f"d{faces}"
    if modo == "vantagem":
        base = f"{quantidade + 1}{dado}kh{quantidade}"
    elif modo == "desvantagem":
        base = f"{quantidade + 1}{dado}kl{quantidade}"
    else:
        base = f"{quantidade}{dado}"
    if modificador:
        return f"{base}{modificador:+d}"
    return base


# --------------------------------------------------------------------------- distribuição
@dataclass(frozen=True)
class Distribuicao:
    probs: dict[int, float]
    exata: bool = True
    simulacoes: int = 0

    @property
    def media(self) -> float:
        return sum(v * p for v, p in self.probs.items())

    @property
    def desvio(self) -> float:
        m = self.media
        return math.sqrt(max(0.0, sum((v - m) ** 2 * p for v, p in self.probs.items())))

    @property
    def minimo(self) -> int:
        return min(self.probs)

    @property
    def maximo(self) -> int:
        return max(self.probs)

    @property
    def moda(self) -> int:
        return max(sorted(self.probs), key=lambda v: self.probs[v])

    def chance(self, comparacao: str, alvo: int) -> float:
        return sum(p for v, p in self.probs.items() if _COMPARAR[comparacao](v, alvo))

    def percentil(self, fracao: float) -> int:
        acumulado = 0.0
        for v in sorted(self.probs):
            acumulado += self.probs[v]
            if acumulado >= fracao - 1e-12:
                return v
        return self.maximo


class _Contas:
    """A distribuição exata, com um limite de contas para não travar o site."""

    def __init__(self) -> None:
        self.contas = 0

    def _gastar(self, n: int) -> None:
        self.contas += n
        if self.contas > _LIMITE_CONTAS:
            raise _SemExata

    def juntar(self, a: dict[int, float], b: dict[int, float], op) -> dict[int, float]:
        self._gastar(len(a) * len(b))
        saida: dict[int, float] = {}
        for va, pa in a.items():
            for vb, pb in b.items():
                v = op(va, vb)
                saida[v] = saida.get(v, 0.0) + pa * pb
        if len(saida) > _LIMITE_VALORES:
            raise _SemExata
        return {v: p for v, p in saida.items() if p >= _PODA}

    def somar_n(self, base: dict[int, float], n: int) -> dict[int, float]:
        saida = {0: 1.0}
        for _ in range(n):
            saida = self.juntar(saida, base, lambda x, y: x + y)
        return saida

    def _primeira_face(self, no: _Dado) -> dict[int, float]:
        """A primeira rolagem de cada dado, já com as regras de rolar de novo."""
        p = 1 / len(no.faces)
        uniforme = {f: p for f in no.faces}
        if not no.rerolar:
            return uniforme
        ficam = {f: q for f, q in uniforme.items() if not _vale(no.rerolar, f)}
        chance_ficar = sum(ficam.values())
        if no.sempre:
            # Geométrica, cortada em LIMITE_REROLAGENS na rolagem; a diferença é desprezível.
            return {f: q / chance_ficar for f, q in ficam.items()}
        saida = {f: q for f, q in ficam.items()}
        chance_rerolar = 1 - chance_ficar
        for f, q in uniforme.items():
            saida[f] = saida.get(f, 0.0) + chance_rerolar * q
        return saida

    def _total_explodindo(self, no: _Dado) -> dict[int, float]:
        """Soma do dado com as suas explosões, até o limite usado na rolagem."""
        p = 1 / len(no.faces)
        seguinte = {f: p for f in no.faces}  # sem explosões restantes
        for _ in range(LIMITE_EXPLOSOES):
            atual: dict[int, float] = {}
            self._gastar(len(no.faces) * len(seguinte))
            for f in no.faces:
                if _vale(no.explode, f):
                    for v, q in seguinte.items():
                        atual[f + v] = atual.get(f + v, 0.0) + p * q
                else:
                    atual[f] = atual.get(f, 0.0) + p
            seguinte = {v: q for v, q in atual.items() if q >= _PODA}
        primeira = self._primeira_face(no)
        saida: dict[int, float] = {}
        for f, p1 in primeira.items():
            if _vale(no.explode, f):
                for v, q in seguinte.items():
                    saida[f + v] = saida.get(f + v, 0.0) + p1 * q
            else:
                saida[f] = saida.get(f, 0.0) + p1
        return saida

    def _mantendo(self, no: _Dado, face: dict[int, float]) -> dict[int, float]:
        """Mantém k de n: percorre os resultados possíveis sem importar a ordem dos dados."""
        faces = sorted(face)
        lado, k = no.manter
        if math.comb(no.n + len(faces) - 1, no.n) > _LIMITE_COMBINACOES:
            raise _SemExata
        self._gastar(math.comb(no.n + len(faces) - 1, no.n) * no.n)
        fatorial_n = math.factorial(no.n)
        saida: dict[int, float] = {}
        por_valor = self._valor_do_dado(no)
        for combo in itertools.combinations_with_replacement(faces, no.n):
            formas = fatorial_n
            prob = 1.0
            for _, grupo in itertools.groupby(combo):
                repetidos = list(grupo)
                formas //= math.factorial(len(repetidos))
                prob *= face[repetidos[0]] ** len(repetidos)
            ficam = combo[-k:] if lado == "h" else combo[:k]
            total = sum(por_valor(v) for v in ficam)
            saida[total] = saida.get(total, 0.0) + formas * prob
        return saida

    @staticmethod
    def _valor_do_dado(no: _Dado):
        if not no.sucesso:
            return lambda v: v

        def valor(v: int) -> int:
            if _vale(no.sucesso, v):
                return 1
            return -1 if no.falha and _vale(no.falha, v) else 0

        return valor

    def dado(self, no: _Dado) -> dict[int, float]:
        if no.explode:
            # Com manter ou sucessos, cada explosão é um dado a mais: simula.
            if no.manter or no.sucesso:
                raise _SemExata
            return self.somar_n(self._total_explodindo(no), no.n)
        face = self._primeira_face(no)
        if no.manter:
            return self._mantendo(no, face)
        valor = self._valor_do_dado(no)
        por_dado: dict[int, float] = {}
        for f, p in face.items():
            por_dado[valor(f)] = por_dado.get(valor(f), 0.0) + p
        return self.somar_n(por_dado, no.n)

    def de(self, no: object) -> dict[int, float]:
        if isinstance(no, _Numero):
            return {no.valor: 1.0}
        if isinstance(no, _Dado):
            return self.dado(no)
        if isinstance(no, _Parenteses):
            return self.de(no.a)
        if isinstance(no, _Negativo):
            return {-v: p for v, p in self.de(no.a).items()}
        if isinstance(no, _Binario):
            return self.juntar(self.de(no.a), self.de(no.b), _BINARIOS[no.op])
        if isinstance(no, _Divisao):
            return self.juntar(self.de(no.a), self.de(no.b), lambda a, b: _divisao(a, b, no.teto))
        if isinstance(no, _Funcao):
            f = _FUNCOES_VARIOS[no.nome]
            saida = self.de(no.args[0])
            for a in no.args[1:]:
                saida = self.juntar(saida, self.de(a), lambda x, y: f(x, y))
            return saida
        raise ErroRolagem("Expressão inválida.")


def distribuicao(texto: str) -> Distribuicao:
    """A chance de cada total. Exata quando dá; senão, simulada, com semente fixa."""
    e = ler_uma(texto)
    try:
        probs = _Contas().de(e.arvore)
    except _SemExata:
        return _simular(e)
    total = sum(probs.values())
    return Distribuicao({v: p / total for v, p in sorted(probs.items())})


def _simular(e: Expressao) -> Distribuicao:
    vezes = min(SIMULACOES, max(1000, _ORCAMENTO_SIMULACAO // max(1, e.dados)))
    rng = random.Random(0)
    contagem: dict[int, int] = {}
    for _ in range(vezes):
        total, _detalhe = _executar(e.arvore, rng, [])
        contagem[total] = contagem.get(total, 0) + 1
    probs = {v: n / vezes for v, n in sorted(contagem.items())}
    return Distribuicao(probs, exata=False, simulacoes=vezes)
