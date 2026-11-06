"""Índice de busca de um livro: acha as páginas de cada assunto antes de chamar o LLM.

* **BM25** (busca lexical clássica) em Python puro: grátis e instantâneo.
* **Embeddings** (opcional): vetores das páginas pelo modelo de embeddings do Databricks,
  para achar páginas pelo sentido mesmo sem as palavras exatas. São calculados uma vez por
  livro e guardados no cache.
* **Busca híbrida:** soma das duas notas normalizadas.

Qual estratégia o site usa é decidido pela avaliação contra o gabarito do SRD
(`oraculo.leitor.avaliacao_generica`, notebook 23).
"""

from __future__ import annotations

import base64
import math
import re
import struct
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

_RE_TOKEN = re.compile(r"[a-z0-9]+")
PARADAS = frozenset(
    """a o os as de da do das dos e em no na nos nas um uma uns umas que se por para com como
    ao aos à às é ser são seu sua seus suas ou mais mas the of and to in a an is for on with
    as by be or it this that are at from you your""".split()
)  # fmt: skip


def tokens(texto: str) -> list[str]:
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return [t for t in _RE_TOKEN.findall(sem_acento) if t not in PARADAS and len(t) > 1]


def _normalizar(notas: list[float]) -> list[float]:
    maior, menor = max(notas, default=0.0), min(notas, default=0.0)
    if maior == menor:
        return [0.0 for _ in notas]
    return [(n - menor) / (maior - menor) for n in notas]


def _cosseno(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


def vetores_para_texto(vetores: list[list[float]]) -> str:
    """Serializa em float16 + base64 (metade do tamanho, precisão de sobra para busca)."""
    if not vetores:
        return ""
    dim = len(vetores[0])
    plano = [x for v in vetores for x in v]
    corpo = struct.pack(f"<{len(plano)}e", *plano)
    return f"{dim}:" + base64.b64encode(corpo).decode()


def texto_para_vetores(texto: str) -> list[list[float]]:
    if not texto:
        return []
    dim_txt, corpo = texto.split(":", 1)
    dim = int(dim_txt)
    bruto = base64.b64decode(corpo)
    plano = struct.unpack(f"<{len(bruto) // 2}e", bruto)
    return [list(plano[i : i + dim]) for i in range(0, len(plano), dim)]


@dataclass
class IndiceLivro:
    paginas: list[str]
    vetores: list[list[float]] = field(default_factory=list)
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        self._termos = [Counter(tokens(p)) for p in self.paginas]
        self._tamanhos = [sum(c.values()) for c in self._termos]
        self._media = sum(self._tamanhos) / max(len(self._tamanhos), 1) or 1.0
        df: Counter = Counter()
        for c in self._termos:
            df.update(c.keys())
        n = len(self.paginas)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @property
    def tem_vetores(self) -> bool:
        return len(self.vetores) == len(self.paginas) and bool(self.vetores)

    def bm25(self, consulta: str) -> list[float]:
        termos = tokens(consulta)
        notas = []
        for c, tamanho in zip(self._termos, self._tamanhos, strict=True):
            nota = 0.0
            for t in termos:
                f = c.get(t, 0)
                if f:
                    norma = f + self.k1 * (1 - self.b + self.b * tamanho / self._media)
                    nota += self._idf.get(t, 0.0) * f * (self.k1 + 1) / norma
            notas.append(nota)
        return notas

    def buscar(
        self,
        consulta: str,
        k: int = 10,
        vetor_consulta: list[float] | None = None,
        peso_semantico: float = 0.5,
        minimo_caracteres: int = 200,
    ) -> list[int]:
        """Índices (base 0) das k páginas mais relevantes, da melhor para a pior."""
        notas = _normalizar(self.bm25(consulta))
        if vetor_consulta is not None and self.tem_vetores:
            sem = _normalizar([_cosseno(vetor_consulta, v) for v in self.vetores])
            notas = [
                (1 - peso_semantico) * a + peso_semantico * s
                for a, s in zip(notas, sem, strict=True)
            ]
        candidatas = [i for i, p in enumerate(self.paginas) if len(p.strip()) >= minimo_caracteres]
        ordem = sorted(candidatas, key=lambda i: notas[i], reverse=True)
        return [i for i in ordem[:k] if notas[i] > 0]

    def com_vizinhas(self, indices: list[int], orcamento: int) -> list[int]:
        """As páginas achadas e a seguinte de cada uma (seções continuam), dentro do orçamento
        de caracteres, na ordem do livro."""
        escolhidas: list[int] = []
        total = 0
        for i in indices:
            for j in (i, i + 1):
                if j >= len(self.paginas) or j in escolhidas:
                    continue
                if total + len(self.paginas[j]) > orcamento:
                    continue
                escolhidas.append(j)
                total += len(self.paginas[j])
        return sorted(escolhidas)
