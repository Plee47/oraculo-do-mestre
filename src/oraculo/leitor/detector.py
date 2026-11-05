"""Detector "é livro de RPG?": features explicáveis por página + nota do documento.

O modelo final é uma regressão logística sobre features que um mestre reconheceria (dados,
blocos de estatísticas, vocabulário de regras, marcas de narrativa). Ele é exportado como JSON
(coeficientes + médias/desvios), então roda no site em Python puro, sem pickle e sem sklearn.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------- features

_RE_DADO = re.compile(r"\b\d{0,3}\s?[dD](?:4|6|8|10|12|20|100)\b")
_RE_MODIFICADOR = re.compile(r"(?<![\w.])[+\-−–]\s?\d{1,2}\b")
_RE_ATRIBUTO = re.compile(r"\b(?:STR|DEX|CON|INT|WIS|CHA|FOR|DES|AGI|PER|SAB|CAR)\b")
_RE_PALAVRA = re.compile(r"[A-Za-zÀ-ÿ]+")

# Termos ESPECÍFICOS de RPG. Palavras genéricas como "player", "check", "level", "range",
# "target", "roll" e "advantage" ficaram de fora: aparecem em livros de xadrez e esportes, e
# uma única delas bastava para um trecho curto de xadrez ser classificado como RPG.
TERMOS_REGRAS = (
    # inglês
    "armor class", "hit points", "hit point", "hit dice", "saving throw", "spell", "spellcasting",
    "damage", "attack roll", "bonus action", "proficiency", "ability check", "dungeon master",
    "game master", "player character", "initiative", "modifier", "short rest", "long rest",
    "cantrip", "spell slot",
    # português
    "pontos de vida", "classe de armadura", "teste de resistência", "magia", "magias", "dano",
    "bônus", "personagem jogador", "mestre do jogo", "atributo", "atributos", "rolagem",
    "rolar o dado", "classe de dificuldade", "ação bônus", "modificador", "penalidade",
    "ficha do personagem",
)  # fmt: skip
TERMOS_ESTATISTICA = (
    "armor class", "hit points", "challenge", "speed", "senses", "languages", "saving throws",
    "classe de armadura", "pontos de vida", "deslocamento", "nível de desafio", "dificuldade",
)  # fmt: skip
TERMOS_SEGUNDA_PESSOA = ("you", "your", "você", "vocês", "seu personagem", "your character")

# Só features de EVIDÊNCIA POSITIVA de RPG. Uma versão anterior usava também "marcas de
# narrativa" e "densidade de números": o modelo aprendeu o atalho "não é romance => é RPG" e
# classificava um livro de xadrez como RPG (ver README, Fase 3).
FEATURES = (
    "dados_por_mil",
    "modificadores_por_mil",
    "atributos_por_mil",
    "termos_regras_por_mil",
    "termos_estatistica_por_mil",
    "segunda_pessoa_por_mil",
)
MINIMO_CARACTERES = 300  # páginas menores (capa, índice vazio) não entram na nota


def _contar(texto: str, termos: tuple[str, ...]) -> int:
    return sum(len(re.findall(rf"\b{re.escape(t)}\b", texto)) for t in termos)


def extrair_features(texto: str) -> dict[str, float]:
    """Ocorrências por mil palavras, comprimidas com log(1 + x) (contagens são assimétricas)."""
    minusculo = texto.lower()
    mil = 1000 / max(len(_RE_PALAVRA.findall(minusculo)), 1)
    brutas = {
        "dados_por_mil": len(_RE_DADO.findall(texto)),
        "modificadores_por_mil": len(_RE_MODIFICADOR.findall(texto)),
        "atributos_por_mil": len(_RE_ATRIBUTO.findall(texto)),
        "termos_regras_por_mil": _contar(minusculo, TERMOS_REGRAS),
        "termos_estatistica_por_mil": _contar(minusculo, TERMOS_ESTATISTICA),
        "segunda_pessoa_por_mil": _contar(minusculo, TERMOS_SEGUNDA_PESSOA),
    }
    return {f: math.log1p(n * mil) for f, n in brutas.items()}


NOMES_FEATURES = {
    "dados_por_mil": "notação de dados (1d20, 2d6…)",
    "modificadores_por_mil": "modificadores (+2, −1…)",
    "atributos_por_mil": "siglas de atributos (FOR, DEX…)",
    "termos_regras_por_mil": "vocabulário de regras",
    "termos_estatistica_por_mil": "blocos de estatísticas",
    "segunda_pessoa_por_mil": "fala com o leitor (você, your…)",
}

# --------------------------------------------------------------------------- sistema provável

ASSINATURAS_SISTEMA = {
    "dnd5e": (
        "armor class", "saving throw", "proficiency bonus", "spell slot", "bonus action",
        "challenge", "short rest", "long rest", "classe de armadura", "teste de resistência",
        "bônus de proficiência", "espaço de magia", "ação bônus", "nível de desafio",
    ),
    "fm": (
        "energia amaldiçoada", "técnica amaldiçoada", "expansão de domínio", "maldição",
        "feiticeiro jujutsu", "técnica inata",
    ),
    "tagmar": ("tagmar", "karma", "estágio", "tabela de resolução"),
}  # fmt: skip


def sistema_provavel(texto: str) -> tuple[str | None, dict[str, int]]:
    minusculo = texto.lower()
    contagens = {s: _contar(minusculo, termos) for s, termos in ASSINATURAS_SISTEMA.items()}
    melhor = max(contagens, key=contagens.get)
    return (melhor if contagens[melhor] >= 5 else None), contagens


# --------------------------------------------------------------------------- modelo


@dataclass
class ModeloDetector:
    """Regressão logística exportável: p = sigmoid(intercepto + Σ coef·(x − média)/desvio)."""

    coeficientes: dict[str, float]
    intercepto: float
    medias: dict[str, float]
    desvios: dict[str, float]
    limiar_documento: float = 0.5

    def contribuicoes(self, feats: dict[str, float]) -> dict[str, float]:
        return {
            f: self.coeficientes[f] * (feats[f] - self.medias[f]) / (self.desvios[f] or 1.0)
            for f in self.coeficientes
        }

    def prob_pagina(self, texto: str) -> float:
        z = self.intercepto + sum(self.contribuicoes(extrair_features(texto)).values())
        return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> ModeloDetector:
        return cls(**d)

    def salvar(self, caminho: str | Path) -> None:
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        texto = json.dumps(self.to_dict(), indent=1, ensure_ascii=False) + "\n"
        Path(caminho).write_text(texto, encoding="utf-8", newline="\n")

    @classmethod
    def carregar(cls, caminho: str | Path) -> ModeloDetector:
        return cls.from_dict(json.loads(Path(caminho).read_text(encoding="utf-8")))


@dataclass
class Veredito:
    e_rpg: bool
    nota: float  # média das probabilidades das páginas com texto
    paginas_analisadas: int
    fracao_paginas_rpg: float
    sistema: str | None
    motivos: list[str]


def avaliar_documento(modelo: ModeloDetector, paginas: list[str]) -> Veredito:
    uteis = [p for p in paginas if len(p.strip()) >= MINIMO_CARACTERES]
    if not uteis:
        return Veredito(False, 0.0, 0, 0.0, None, ["Não há texto extraível (PDF escaneado?)."])
    probs = [modelo.prob_pagina(p) for p in uteis]
    nota = sum(probs) / len(probs)

    # Motivos: as features que mais empurraram a nota, na média do documento.
    soma: dict[str, float] = dict.fromkeys(modelo.coeficientes, 0.0)
    for p in uteis:
        for f, c in modelo.contribuicoes(extrair_features(p)).items():
            soma[f] += c / len(uteis)
    ordenadas = sorted(soma.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
    motivos = [
        f"{'mais' if c > 0 else 'menos'} parecido com RPG por causa de: {NOMES_FEATURES[f]}"
        for f, c in ordenadas
    ]
    sistema, _ = sistema_provavel("\n".join(uteis))
    return Veredito(
        e_rpg=nota >= modelo.limiar_documento,
        nota=nota,
        paginas_analisadas=len(uteis),
        fracao_paginas_rpg=sum(p >= 0.5 for p in probs) / len(probs),
        sistema=sistema,
        motivos=motivos,
    )
