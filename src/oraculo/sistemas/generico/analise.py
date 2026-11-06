"""Análises de grupo e de encontro para qualquer sistema lido de um livro.

Só usa o que o livro deu: faixas dos atributos, fórmulas de vida e defesa, dano típico dos
arquétipos e a ficha das criaturas. Quando falta um dado, a análise diz o que falta em vez de
inventar número. As contas de encontro são estimativas por valor médio e o texto diz isso.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import mean

from oraculo.nucleo.analise import Achado, ordenar
from oraculo.nucleo.ficha import Ficha
from oraculo.sistemas.generico.formulas import ErroFormula, avaliar
from oraculo.sistemas.generico.gerador import calcular_derivados, gerar_ficha, limites
from oraculo.sistemas.generico.modelo import Ataque, Criatura, SistemaLido


@dataclass(frozen=True)
class PerfilLido:
    nome: str
    arquetipo: str
    vida: int | None
    defesa: int | None
    dano: float | None  # dano médio por turno (dano típico do arquétipo)
    atributos: dict[str, int]


def perfil(s: SistemaLido, ficha: Ficha) -> PerfilLido:
    valores = {
        d.tipo: v
        for d, v in reversed(calcular_derivados(s, ficha.atributos, ficha.nivel, ficha.classe))
    }
    arq = s.arquetipo(ficha.classe)
    formula_dano = (arq.dano_tipico if arq and arq.dano_tipico else "") or s.mecanica.dano_basico
    dano = None
    if formula_dano:
        try:
            # um modificador negativo não cura o alvo: dano mínimo é 0
            dano = max(0.0, avaliar(formula_dano, s.variaveis(ficha.atributos, ficha.nivel)))
        except ErroFormula:
            dano = None
    return PerfilLido(
        nome=ficha.nome,
        arquetipo=ficha.classe or "—",
        vida=valores.get("vida"),
        defesa=valores.get("defesa"),
        dano=dano,
        atributos=dict(ficha.atributos),
    )


def _fracao_na_faixa(s: SistemaLido, aid: str, valor: float) -> float | None:
    a = next((x for x in s.atributos if x.id == aid), None)
    if a is None:
        return None
    mn, mx = limites(s, a)
    if mn is None or mx is None or mx == mn:
        return None
    return (valor - mn) / (mx - mn)


def analisar_grupo(s: SistemaLido, fichas: list[Ficha]) -> list[Achado]:
    if not fichas:
        return []
    pjs = [perfil(s, f) for f in fichas]
    achados: list[Achado] = []
    resolucao = s.mecanica.resolucao or "a mecânica do livro"

    # Atributo mais fraco do grupo (relativo à faixa do próprio livro)
    fracos = []
    for a in s.atributos:
        valores = [p.atributos[a.id] for p in pjs if a.id in p.atributos]
        if not valores:
            continue
        fr = _fracao_na_faixa(s, a.id, mean(valores))
        if fr is not None:
            fracos.append((fr, a, mean(valores), max(valores)))
    if fracos:
        fr, a, media_grupo, melhor = min(fracos, key=lambda x: x[0])
        if fr < 0.4:
            achados.append(Achado(
                severidade="atencao", categoria="Atributos",
                titulo=f"O grupo é fraco em {a.nome} (média {media_grupo:.0f})",
                detalhe=f"{a.descricao or 'Testes desse atributo'} — o melhor do grupo tem "
                        f"{melhor}. Situações que pedem {a.nome} vão falhar com frequência.",
                regra=f"Resolução do sistema: {resolucao}",
                sugestao=f"Inclua um personagem com {a.nome} alto ou evite depender dele.",
            ))  # fmt: skip

    # Perícias sem ninguém
    if s.pericias:
        cobertas = {p.lower() for f in fichas for p in f.pericias}
        faltando = [p.nome for p in s.pericias if p.nome.lower() not in cobertas]
        if faltando:
            mostrar = ", ".join(faltando[:8]) + ("…" if len(faltando) > 8 else "")
            achados.append(Achado(
                severidade="info", categoria="Perícias",
                titulo=f"{len(faltando)} perícias sem ninguém treinado",
                detalhe=f"{mostrar}.",
                regra="Perícias do livro que nenhuma ficha do grupo tem.",
            ))  # fmt: skip

    # Papéis do livro que faltam
    papeis_livro = {a.papel.lower() for a in s.arquetipos if a.papel}
    papeis_grupo = {
        s.arquetipo(f.classe).papel.lower()
        for f in fichas
        if s.arquetipo(f.classe) and s.arquetipo(f.classe).papel
    }
    faltam = sorted(papeis_livro - papeis_grupo)
    if faltam and len(papeis_livro) > 1:
        achados.append(Achado(
            severidade="info", categoria="Papéis",
            titulo=f"Papéis do livro sem ninguém: {', '.join(faltam)}",
            detalhe="Os arquétipos do livro cobrem funções que este grupo não tem.",
            regra=f"Papéis atribuídos a cada {s.nome_arquetipo} na leitura do livro.",
        ))  # fmt: skip

    # Fragilidade
    vidas = [p for p in pjs if p.vida is not None]
    vida_def = s.derivado_do_tipo("vida")
    if len(vidas) > 1 and vida_def:
        fragil = min(vidas, key=lambda p: p.vida)
        media_vida = mean(p.vida for p in vidas)
        if fragil.vida < 0.7 * media_vida:
            achados.append(Achado(
                severidade="atencao", categoria="Papéis", titulo=f"{fragil.nome} é o alvo fácil",
                detalhe=f"{vida_def.nome} {fragil.vida}, contra {media_vida:.0f} de média.",
                regra=f"{vida_def.nome} = {vida_def.formula}",
            ))  # fmt: skip
    elif not vida_def:
        achados.append(Achado(
            severidade="info", categoria="Leitura",
            titulo="O livro não deu uma fórmula de vida calculável",
            detalhe="Sem ela, não dá para comparar a resistência dos personagens.",
            regra="Valores derivados lidos do livro (veja o resumo do sistema).",
        ))  # fmt: skip
    return ordenar(achados)


# --------------------------------------------------------------------------- encontro


@dataclass(frozen=True)
class ResumoEncontro:
    vida_grupo: float | None
    vida_criaturas: float | None
    dano_grupo: float | None
    dano_criaturas: float | None
    rodadas_para_vencer: float | None
    rodadas_para_perder: float | None
    veredito: str


def criatura_de_ficha(s: SistemaLido, ficha: Ficha) -> Criatura:
    """Um PdM montado com as regras de personagem do livro, como inimigo de encontro.

    Muitos livros não têm bestiário: os inimigos são construídos como os personagens. O dano
    vira número (média) já no nível do PdM, para não depender de variáveis depois.
    """
    p = perfil(s, ficha)
    ataques = []
    if p.dano is not None:
        ataques.append(Ataque(nome="Ataque típico", dano=f"{p.dano:.1f}"))
    return Criatura(
        nome=ficha.nome,
        descricao=f"PdM gerado pelas regras do livro ({ficha.classe or 'sem arquétipo'})",
        ameaca=f"{s.niveis.nome} {ficha.nivel}" if s.niveis.usa_niveis else "",
        atributos=dict(ficha.atributos),
        vida=p.vida,
        defesa=p.defesa,
        ataques=ataques,
    )


def dano_por_turno(s: SistemaLido, c: Criatura) -> float | None:
    """O ataque de maior dano médio da criatura (uma ação por turno)."""
    variaveis = {**dict.fromkeys((x.lower() for x in c.atributos), 0), **c.atributos}
    variaveis.update(s.variaveis(c.atributos))
    medias = []
    for at in c.ataques:
        if at.dano:
            try:
                medias.append(max(0.0, avaliar(at.dano, variaveis)))
            except ErroFormula:
                continue
    return max(medias) if medias else None


def _estimar(
    s: SistemaLido, pjs: list[PerfilLido], criaturas: list[tuple[Criatura, int]]
) -> ResumoEncontro:
    """A conta do encontro, por valor médio. Campos sem dado do livro ficam None."""
    acerto = s.mecanica.chance_acerto_estimada
    # Dano esperado por turno = dano médio × multiplicador médio (graus de sucesso) × acerto.
    fator = acerto * s.mecanica.multiplicador_dano_medio
    tem = lambda xs: bool(xs) and all(x is not None for x in xs)  # noqa: E731
    vida_grupo = sum(p.vida for p in pjs) if tem([p.vida for p in pjs]) else None
    dano_grupo = sum(p.dano for p in pjs) * fator if tem([p.dano for p in pjs]) else None
    vida_cri = (sum(c.vida * n for c, n in criaturas)
                if tem([c.vida for c, _ in criaturas]) else None)  # fmt: skip
    danos = [(c, n, dano_por_turno(s, c)) for c, n in criaturas]
    dano_cri = (sum(d * n for _, n, d in danos) * fator
                if tem([d for _, _, d in danos]) else None)  # fmt: skip

    vencer = vida_cri / dano_grupo if vida_cri is not None and dano_grupo else None
    perder = vida_grupo / dano_cri if vida_grupo is not None and dano_cri else None
    if vencer and perder:
        razao = perder / vencer
        veredito = ("fácil" if razao >= 3 else "equilibrado" if razao >= 1.5
                    else "difícil" if razao >= 0.8 else "mortal")  # fmt: skip
    else:
        veredito = "sem dados suficientes"
    return ResumoEncontro(vida_grupo, vida_cri, dano_grupo, dano_cri, vencer, perder, veredito)


def analisar_encontro(
    s: SistemaLido, fichas: list[Ficha], criaturas: list[tuple[Criatura, int]]
) -> tuple[ResumoEncontro, list[Achado]]:
    pjs = [perfil(s, f) for f in fichas]
    acerto = s.mecanica.chance_acerto_estimada
    achados: list[Achado] = []
    resumo = _estimar(s, pjs, criaturas)
    vida_grupo, vida_cri = resumo.vida_grupo, resumo.vida_criaturas
    dano_grupo, dano_cri = resumo.dano_grupo, resumo.dano_criaturas
    vencer, perder, veredito = (
        resumo.rodadas_para_vencer, resumo.rodadas_para_perder, resumo.veredito,
    )  # fmt: skip
    danos = [(c, n, dano_por_turno(s, c)) for c, n in criaturas]

    multiplicador = s.mecanica.multiplicador_dano_medio
    regra_acerto = (
        f"Estimativa por valor médio: dano médio × chance de acerto estimada ({acerto:.0%})"
        + (f" × multiplicador médio de dano ({multiplicador:.1f})" if multiplicador != 1 else "")
        + f", pela mecânica do livro ({s.mecanica.resolucao or s.mecanica.dado_base or '—'})."
    )
    if veredito in ("difícil", "mortal"):
        achados.append(Achado(
            severidade="alerta" if veredito == "mortal" else "atencao", categoria="Balanço",
            titulo=f"Encontro {veredito}",
            detalhe=f"O grupo derruba as criaturas em ~{vencer:.1f} rodadas, mas cai em "
                    f"~{perder:.1f}.",
            regra=regra_acerto,
            sugestao="Reduza a quantidade de criaturas ou dê ao grupo terreno e preparação.",
        ))  # fmt: skip
    elif veredito in ("fácil", "equilibrado"):
        achados.append(Achado(
            severidade="ok", categoria="Balanço", titulo=f"Encontro {veredito}",
            detalhe=f"~{vencer:.1f} rodadas para vencer contra ~{perder:.1f} até o grupo cair.",
            regra=regra_acerto,
        ))  # fmt: skip

    # Um golpe que derruba o mais frágil
    vivos = [p for p in pjs if p.vida is not None]
    if vivos:
        fragil = min(vivos, key=lambda p: p.vida)
        for c, _, d in danos:
            if d is not None and d * multiplicador >= fragil.vida:
                achados.append(Achado(
                    severidade="alerta", categoria="Risco",
                    titulo=f"{c.nome} derruba {fragil.nome} com um golpe",
                    detalhe=f"Dano médio do melhor ataque: {d * multiplicador:.0f}; "
                            f"vida de {fragil.nome}: {fragil.vida}.",
                    regra="Comparação do dano médio do ataque com a vida calculada da ficha.",
                ))  # fmt: skip
                break

    faltas = []
    if vida_grupo is None:
        faltas.append("a vida das fichas")
    if dano_grupo is None:
        faltas.append("o dano de um ataque dos personagens")
    if vida_cri is None:
        faltas.append("a vida das criaturas")
    if dano_cri is None:
        faltas.append("o dano dos ataques das criaturas")
    if faltas:
        achados.append(Achado(
            severidade="info", categoria="Leitura", titulo="Estimativa incompleta",
            detalhe=f"O livro não deixou claro {', '.join(faltas)}, então essa parte da conta "
                    "ficou de fora.",
            regra="O Oráculo não inventa números que o livro não deu.",
        ))  # fmt: skip

    especiais = [(c.nome, h) for c, _ in criaturas for h in c.habilidades[:2]]
    if especiais:
        achados.append(Achado(
            severidade="info", categoria="Habilidades",
            titulo="Habilidades especiais que a conta não cobre",
            detalhe="; ".join(f"{n}: {h}" for n, h in especiais[:6]) + ".",
            regra="Efeitos especiais mudam o encontro mais que o dano médio.",
        ))  # fmt: skip
    if s.regras_encontro:
        achados.append(Achado(
            severidade="info", categoria="Livro", titulo="O que o livro diz sobre encontros",
            detalhe=s.regras_encontro, regra="Orientação do próprio livro.",
        ))  # fmt: skip

    return resumo, ordenar(achados)


# --------------------------------------------------------------------------- sugestão
# Rodadas até o grupo cair ÷ rodadas para vencer que se busca em cada dificuldade.
ALVOS_DIFICULDADE = {"fácil": 3.5, "equilibrado": 2.0, "difícil": 1.1}
MAX_CANDIDATAS = 12


@dataclass(frozen=True)
class SugestaoEncontro:
    criaturas: list[tuple[Criatura, int]]
    resumo: ResumoEncontro
    origem: str  # "livro" ou "regras"


def _candidatas(s: SistemaLido, fichas: list[Ficha], seed: int) -> tuple[list[Criatura], str]:
    """Criaturas do livro com vida e dano; sem elas, PdMs montados pelas regras do livro."""
    do_livro = [c for c in s.criaturas if c.vida and dano_por_turno(s, c)]
    if do_livro:
        return do_livro, "livro"
    nivel = fichas[0].nivel if fichas else None
    nomes = [a.nome for a in s.arquetipos] or [None]
    gerados = []
    for i, nome in enumerate((nomes * 6)[:6]):
        ficha = gerar_ficha(
            s, arquetipo=nome, nivel=nivel, seed=seed + 100 + i, nome=f"PdM {i + 1}"
        )
        c = criatura_de_ficha(s, ficha)
        if c.vida and dano_por_turno(s, c):
            gerados.append(c)
    return gerados, "regras"


def sugerir_encontro(
    s: SistemaLido, fichas: list[Ficha], dificuldade: str = "equilibrado", seed: int = 1
) -> SugestaoEncontro | None:
    """O grupo de inimigos cuja estimativa fica mais perto da dificuldade pedida.

    Usa a mesma conta da análise de encontro. Nas dificuldades fácil e equilibrada, evita
    criaturas que derrubam o personagem mais frágil com um golpe. None se o livro não deu os
    números necessários (vida e dano dos personagens e dos inimigos).
    """
    if dificuldade not in ALVOS_DIFICULDADE:
        raise ValueError(f"dificuldade desconhecida: {dificuldade!r}")
    pjs = [perfil(s, f) for f in fichas]
    if not pjs or any(p.vida is None or p.dano is None for p in pjs):
        return None
    if not sum(p.dano for p in pjs):  # ninguém do grupo causa dano: não há como estimar
        return None
    candidatas, origem = _candidatas(s, fichas, seed)
    if not candidatas:
        return None
    rng = random.Random(seed)
    rng.shuffle(candidatas)
    candidatas = candidatas[:MAX_CANDIDATAS]
    multiplicador = s.mecanica.multiplicador_dano_medio
    menor_vida = min(p.vida for p in pjs)
    if dificuldade != "difícil":
        seguras = [c for c in candidatas if dano_por_turno(s, c) * multiplicador < menor_vida]
        candidatas = seguras or candidatas

    grupos: list[list[tuple[Criatura, int]]] = []
    for a in candidatas:
        grupos += [[(a, n)] for n in range(1, 11)]
    for i, a in enumerate(candidatas):
        for b in candidatas[i + 1 :]:
            grupos += [[(a, x), (b, y)] for x in range(1, 5) for y in range(1, 5)]

    alvo = ALVOS_DIFICULDADE[dificuldade]

    def custo(grupo: list[tuple[Criatura, int]]) -> float:
        resumo = _estimar(s, pjs, grupo)
        if not resumo.rodadas_para_vencer or not resumo.rodadas_para_perder:
            return math.inf
        razao = resumo.rodadas_para_perder / resumo.rodadas_para_vencer
        if razao <= 0:
            return math.inf
        return abs(math.log(razao / alvo)) + 0.01 * sum(n for _, n in grupo)

    melhor = min(grupos, key=custo)
    if custo(melhor) == math.inf:
        return None
    return SugestaoEncontro(melhor, _estimar(s, pjs, melhor), origem)
