"""Extração de magias e monstros de páginas de livro com LLM (D&D 5e).

Fluxo: texto do PDF -> limpeza -> janelas de 2 páginas -> prompt -> JSON -> modelos do catálogo.
A janela inclui a página seguinte só como continuação: o LLM extrai apenas o que COMEÇA na
página A, o que evita duplicatas e entradas cortadas no fim da página.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from oraculo.sistemas.dnd5e.catalogo import Magia, Monstro
from oraculo.sistemas.dnd5e.srd import TIPOS_DANO

TIPOS_DANO_VALIDOS = set(TIPOS_DANO)

# --------------------------------------------------------------------------- limpeza


def limpar_texto_pdf(texto: str) -> str:
    """Remove ruído típico de PDF: tabs, espaços duplicados, hífens e caracteres invisíveis."""
    texto = texto.replace("\xad", "").replace("​", "").replace("’", "'")
    # O PDF do SRD escreve "4th-level" com vários hífens seguidos (-, U+2010, U+2011...).
    texto = re.sub(r"[\-‐‑‒–]+", "-", texto)
    texto = texto.replace("\t", " ")
    texto = re.sub(r"[  ]{2,}", " ", texto)
    return "\n".join(linha.strip() for linha in texto.splitlines() if linha.strip())


_RE_INDICIO = re.compile(
    r"armor\s+class|hit\s+points|classe\s+de\s+armadura|pontos\s+de\s+vida|"
    r"\d(?:st|nd|rd|th)-?\s*level\s+\w+|\bcantrip\b|\bcírculo\b|\btruque\b|casting\s+time",
    re.IGNORECASE,
)


def parece_ter_entradas(texto: str) -> bool:
    """Pré-filtro barato: só páginas com indício de magia ou bloco de estatísticas vão ao LLM."""
    return bool(_RE_INDICIO.search(limpar_texto_pdf(texto)))


@dataclass(frozen=True)
class Janela:
    pagina: int  # número da página A (1 = primeira)
    texto: str


def janelas(paginas: list[str], continuacao: int = 1500) -> list[Janela]:
    """Página A inteira + o começo da página B (para completar entradas cortadas)."""
    limpas = [limpar_texto_pdf(p) for p in paginas]
    resultado = []
    for i, atual in enumerate(limpas):
        if len(atual) < 200:
            continue
        seguinte = limpas[i + 1][:continuacao] if i + 1 < len(limpas) else ""
        texto = f"=== PÁGINA A ===\n{atual}\n=== PÁGINA B (continuação) ===\n{seguinte}"
        resultado.append(Janela(pagina=i + 1, texto=texto))
    return resultado


# --------------------------------------------------------------------------- prompt

INSTRUCOES = """Você extrai dados de livros de RPG (D&D 5ª edição) para JSON.

Extraia TODAS as magias e TODOS os blocos de estatísticas de monstros/NPCs cujo TÍTULO aparece
na PÁGINA A. A PÁGINA B serve só para completar uma entrada que começou na página A. Ignore
entradas que começaram antes da página A e qualquer coisa que não seja magia ou monstro.

Uma entrada só existe se tiver um bloco próprio: o título numa linha, seguido da linha de
nível/escola (magias, ex. "3rd-level evocation") ou de tamanho/tipo (monstros, ex. "Large
dragon, chaotic evil"). Nomes apenas CITADOS no meio do texto (ex. "como a magia heal") NÃO são
entradas. Condições (charmed, frightened, poisoned...) NÃO são tipos de dano.

Responda SOMENTE com um objeto JSON, sem comentários, neste formato:
{"magias": [{"nome": str, "circulo": int (0 = truque), "escola": str (em inglês, minúsculas),
  "concentracao": bool, "ritual": bool, "dano": str|null (dado no círculo base, ex. "8d6"),
  "tipo_dano": str|null (em inglês, minúsculas, ex. "fire"),
  "resistencia": "str"|"dex"|"con"|"int"|"wis"|"cha"|null (atributo do teste de resistência),
  "area": bool (afeta uma área: cone, esfera, linha, cubo, cilindro, raio),
  "cura": bool (recupera pontos de vida)}],
 "monstros": [{"nome": str, "tamanho": str (em inglês, ex. "Large"), "tipo": str (em inglês,
  minúsculas, ex. "dragon"), "cr": number (1/4 = 0.25), "ca": int, "pv": int (valor médio),
  "atributos": {"str": int, "dex": int, "con": int, "int": int, "wis": int, "cha": int},
  "imunidades_dano": [str], "resistencias_dano": [str], "vulnerabilidades_dano": [str],
  "voa": bool (tem deslocamento de voo), "acoes_lendarias": int (quantas ações lendárias
  diferentes estão listadas; 0 se nenhuma)}]}

Nas listas de dano use só tipos simples em inglês (acid, bludgeoning, cold, fire, force,
lightning, necrotic, piercing, poison, psychic, radiant, slashing, thunder). Se um campo não
existir no texto, use null (ou lista vazia).
Se não houver nada, responda {"magias": [], "monstros": []}."""


def mensagens(janela: Janela) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": INSTRUCOES},
        {"role": "user", "content": janela.texto},
    ]


def prompt_unico(janela: Janela) -> str:
    """Instruções + texto num único prompt (formato do `ai_query` do Databricks)."""
    return f"{INSTRUCOES}\n\n{janela.texto}"


# --------------------------------------------------------------------------- resposta

_RE_BLOCO_JSON = re.compile(r"\{.*\}", re.DOTALL)
_ATRIB = {"str": "for", "dex": "des", "con": "con", "int": "int", "wis": "sab", "cha": "car"}


def interpretar_resposta(texto: str) -> dict:
    """Aceita JSON puro, dentro de ```json ... ``` ou com texto em volta."""
    if not texto:
        return {"magias": [], "monstros": []}
    sem_cercas = re.sub(r"```(?:json)?", "", texto)
    m = _RE_BLOCO_JSON.search(sem_cercas)
    if not m:
        raise ValueError("resposta sem JSON")
    dados = json.loads(m.group(0))
    return {"magias": dados.get("magias") or [], "monstros": dados.get("monstros") or []}


def _id(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-")


def _lista(valor) -> list[str]:
    """Normaliza uma lista de tipos de dano e descarta o que não for tipo de dano válido
    (o LLM às vezes mistura condições, como "charmed", nas imunidades a dano)."""
    if not valor:
        return []
    if isinstance(valor, str):
        valor = [valor]
    return sorted({str(v).strip().lower() for v in valor} & TIPOS_DANO_VALIDOS)


def _cr(valor) -> float:
    if isinstance(valor, str) and "/" in valor:
        a, b = valor.split("/", 1)
        return float(a) / float(b)
    return float(valor or 0)


def magia_de_llm(d: dict) -> Magia:
    resistencia = (d.get("resistencia") or "").lower()[:3]
    return Magia(
        id=_id(d["nome"]),
        nome=str(d["nome"]).strip(),
        circulo=int(d.get("circulo") or 0),
        escola=str(d.get("escola") or "").lower(),
        classes=[],  # as listas de classes ficam em outra seção do livro
        concentracao=bool(d.get("concentracao")),
        ritual=bool(d.get("ritual")),
        resistencia=_ATRIB.get(resistencia),
        tipo_dano=(d.get("tipo_dano") or None) and str(d["tipo_dano"]).lower(),
        dano=(d.get("dano") or None) and str(d["dano"]).replace(" ", ""),
        cura=bool(d.get("cura")),
        area=bool(d.get("area")),
    )


def monstro_de_llm(d: dict) -> Monstro:
    attrs = d.get("atributos") or {}
    atributos = {_ATRIB[k]: int(attrs.get(k) or 10) for k in _ATRIB}
    return Monstro(
        id=_id(d["nome"]),
        nome=str(d["nome"]).strip(),
        tipo=str(d.get("tipo") or "").lower(),
        tamanho=str(d.get("tamanho") or "").capitalize(),
        cr=_cr(d.get("cr")),
        xp=0,
        ca=int(d.get("ca") or 10),
        pv=int(d.get("pv") or 1),
        atributos=atributos,
        resistencias_bonus={a: (v - 10) // 2 for a, v in atributos.items()},
        imunidades_dano=_lista(d.get("imunidades_dano")),
        resistencias_dano=_lista(d.get("resistencias_dano")),
        vulnerabilidades_dano=_lista(d.get("vulnerabilidades_dano")),
        voa=bool(d.get("voa")),
        acoes_lendarias=int(d.get("acoes_lendarias") or 0),
    )


@dataclass
class Extracao:
    magias: list[Magia]
    monstros: list[Monstro]
    erros: list[str]


def converter(respostas: list[tuple[int, str]]) -> Extracao:
    """`respostas` = [(página, texto do LLM)]. Deduplica por id (fica a primeira ocorrência)."""
    magias: dict[str, Magia] = {}
    monstros: dict[str, Monstro] = {}
    erros = []
    for pagina, texto in respostas:
        try:
            dados = interpretar_resposta(texto)
        except (ValueError, json.JSONDecodeError) as e:
            erros.append(f"página {pagina}: {e}")
            continue
        for d in dados["magias"]:
            try:
                m = magia_de_llm(d)
                magias.setdefault(m.id, m)
            except (KeyError, TypeError, ValueError) as e:
                erros.append(f"página {pagina}, magia: {e!r}")
        for d in dados["monstros"]:
            try:
                m = monstro_de_llm(d)
                monstros.setdefault(m.id, m)
            except (KeyError, TypeError, ValueError) as e:
                erros.append(f"página {pagina}, monstro: {e!r}")
    return Extracao(list(magias.values()), list(monstros.values()), erros)
