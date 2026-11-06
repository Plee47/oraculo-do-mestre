"""Fichas para qualquer sistema lido de um livro, com cada escolha explicada.

Segue o método de criação que o próprio livro descreve (rolagem por atributo como no Call of
Cthulhu, rolagem única distribuída, compra de pontos ou valores fixos como no Vampiro) e
calcula os valores derivados com as fórmulas do livro. Determinístico dado um `seed`.
"""

from __future__ import annotations

import random

from oraculo.nucleo.ficha import Ficha, Problema
from oraculo.sistemas.generico.formulas import avaliar, normalizar_id, tem_dado
from oraculo.sistemas.generico.modelo import (
    Atributo,
    Derivado,
    Opcao,
    RegraGeracao,
    SistemaLido,
)

SISTEMA_LIDO = "lido"
NOMES = (
    "Alex", "Bia", "Caio", "Dani", "Eli", "Fran", "Gabi", "Iuri", "Jade", "Kai", "Lia", "Malu",
    "Nico", "Otto", "Pam", "Rafa", "Sam", "Téo", "Vivi", "Zoe",
)  # fmt: skip


def regra_de(s: SistemaLido, atributo_id: str) -> RegraGeracao:
    """A regra de geração que vale para o atributo: a do grupo dele ou a geral."""
    return next((g for g in s.geracao.grupos if atributo_id in g.atributos), s.geracao)


def limites(s: SistemaLido, a: Atributo) -> tuple[int | None, int | None]:
    minimo = a.minimo if a.minimo is not None else regra_de(s, a.id).valor_inicial
    return minimo, a.maximo


def _prender(valor: float, minimo: int | None, maximo: int | None) -> int:
    v = round(valor)
    if minimo is not None:
        v = max(v, minimo)
    if maximo is not None:
        v = min(v, maximo)
    return v


def prioridade(s: SistemaLido, arquetipo_chaves: list[str], rng: random.Random) -> list[str]:
    """Atributos-chave do arquétipo primeiro; o resto embaralhado pelo seed."""
    resto = [a.id for a in s.atributos if a.id not in arquetipo_chaves]
    rng.shuffle(resto)
    return [*arquetipo_chaves, *resto]


def _com_regra(
    s: SistemaLido, r: RegraGeracao, ordem: list[str], rng: random.Random
) -> tuple[dict[str, int], str]:
    """Gera os atributos de `ordem` (do mais ao menos importante) com uma regra do livro."""
    por_id = {a.id: a for a in s.atributos}
    valores: dict[str, int] = {}
    metodo = r.metodo
    if metodo == "outro":  # livro com vários métodos: o mais previsível que ele der
        if r.valores_fixos:
            metodo = "valores_fixos"
        elif r.pontos:
            metodo = "pontos"
        elif r.rolagem:
            metodo = "rolagem"

    if metodo == "rolagem" and r.rolagem:
        rolados = sorted((avaliar(r.rolagem, {}, rng=rng) for _ in ordem), reverse=True)
        for aid, v in zip(ordem, rolados, strict=True):
            valores[aid] = _prender(v, *limites(s, por_id[aid]))
        return valores, (
            f"{len(ordem)} rolagens de {r.rolagem}, os maiores resultados nos atributos mais "
            "importantes do arquétipo"
        )

    if metodo == "valores_fixos" and r.valores_fixos:
        fixos = sorted(r.valores_fixos, reverse=True)
        sobra = min(fixos)
        for i, aid in enumerate(ordem):
            valores[aid] = _prender(fixos[i] if i < len(fixos) else sobra, *limites(s, por_id[aid]))
        texto = f"valores fixos do livro ({', '.join(map(str, fixos))})"
        if len(fixos) < len(ordem):
            texto += f"; atributos além da lista ficaram com {sobra}"
        return valores, texto + ", os maiores nos atributos mais importantes do arquétipo"

    if metodo == "pontos" and r.pontos:
        for aid in ordem:
            mn, _ = limites(s, por_id[aid])
            valores[aid] = mn if mn is not None else 0
        pesos = {aid: (3 if i < 2 else 2 if i < 4 else 1) for i, aid in enumerate(ordem)}
        gasto = dict.fromkeys(ordem, 0)
        restantes = r.pontos

        def abaixo_do_maximo(aid: str) -> bool:
            maximo = limites(s, por_id[aid])[1]
            return maximo is None or valores[aid] < maximo

        while restantes > 0:
            livres = [a for a in ordem if abaixo_do_maximo(a)]
            if not livres:
                break
            escolhido = max(livres, key=lambda a: (pesos[a] / (1 + gasto[a]), -ordem.index(a)))
            valores[escolhido] += 1
            gasto[escolhido] += 1
            restantes -= 1
        inicio = r.valor_inicial if r.valor_inicial is not None else "o mínimo"
        texto = (
            f"{r.pontos} pontos distribuídos a partir de {inicio}, mais pontos nos atributos do "
            "arquétipo"
        )
        if restantes:
            texto += f"; sobraram {restantes} pontos porque todos chegaram ao máximo"
        return valores, texto

    sem_faixa = all(limites(s, por_id[a]) == (None, None) for a in ordem)
    if s.modificador and sem_faixa and s.modificador_de(10) == 0:
        tipicos = (15, 14, 13, 12, 10, 8)
        for i, aid in enumerate(ordem):
            valores[aid] = tipicos[i] if i < len(tipicos) else 10
        return valores, (
            "o livro não traz um método de geração nos trechos lidos; usei valores típicos da "
            "escala do modificador dele (10 vale +0), os maiores nos atributos do arquétipo"
        )

    # Método que o Oráculo não automatiza: valores proporcionais à faixa do atributo.
    fracoes = [0.75, 0.7, 0.6, 0.55]
    for i, aid in enumerate(ordem):
        mn, mx = limites(s, por_id[aid])
        base, topo = (mn if mn is not None else 1), (mx if mx is not None else (mn or 1) + 10)
        f = fracoes[i] if i < len(fracoes) else 0.45
        valores[aid] = _prender(base + (topo - base) * f, mn, mx)
    return valores, (
        "o livro usa um método que o Oráculo não automatiza; valores sugeridos dentro da faixa "
        "de cada atributo, mais altos nos atributos do arquétipo"
    )


def gerar_atributos(
    s: SistemaLido, ordem: list[str], rng: random.Random
) -> tuple[dict[str, int], str]:
    """Valores dos atributos pelo(s) método(s) do livro e a explicação do que foi feito.

    Ordem de precedência: rolagem própria do atributo (ex.: Call of Cthulhu) → grupo com regra
    própria (ex.: atributos sociais com pontos separados) → regra geral.
    """
    valores: dict[str, int] = {}
    textos: list[str] = []
    restantes = list(ordem)

    proprios = [a for a in s.atributos if a.rolagem and a.id in restantes]
    if proprios:
        for a in proprios:
            valores[a.id] = _prender(avaliar(a.rolagem, {}, rng=rng), *limites(s, a))
        textos.append(
            "rolados com a rolagem própria de cada um ("
            + ", ".join(f"{a.sigla or a.nome} {a.rolagem}" for a in proprios[:4])
            + ("…" if len(proprios) > 4 else "")
            + ")"
        )
        restantes = [x for x in restantes if x not in {a.id for a in proprios}]

    for g in s.geracao.grupos:
        sub = [x for x in restantes if x in g.atributos]
        if sub:
            v, texto = _com_regra(s, g, sub, rng)
            valores.update(v)
            textos.append(f"{g.nome or 'grupo'}: {texto}")
            restantes = [x for x in restantes if x not in sub]

    if restantes:
        v, texto = _com_regra(s, s.geracao, restantes, rng)
        valores.update(v)
        textos.append(texto)
    regras = [*s.geracao.grupos, s.geracao]
    if any(r.metodo == "pontos" and r.pontos for r in regras):
        textos.append("cada ponto custa 1 (se o livro usa tabela de custo, confira)")
    return valores, "; ".join(textos)


def calcular_derivados(
    s: SistemaLido, atributos: dict[str, int], nivel: int = 1, arquetipo: str | None = None
) -> list[tuple[Derivado, int | None]]:
    """Cada valor derivado pela fórmula do livro (a do arquétipo, se houver; dados pela média)."""
    valores = s.calcular(atributos, nivel, s.arquetipo(arquetipo))
    return [(d, None if valores[d.id] is None else round(valores[d.id])) for d in s.derivados]


def _escolher_pericias(
    s: SistemaLido, pericias_arquetipo: list[str], atributos: dict[str, int], rng: random.Random
) -> list[str]:
    nomes = {normalizar_id(p.nome): p.nome for p in s.pericias}
    escolhidas = [nomes.get(normalizar_id(p), p) for p in pericias_arquetipo]
    if len(escolhidas) < 4 and s.pericias:
        candidatas = sorted(
            (p for p in s.pericias if p.nome not in escolhidas),
            key=lambda p: (-atributos.get(p.atributo or "", 0), rng.random()),
        )
        escolhidas += [p.nome for p in candidatas[: 4 - len(escolhidas)]]
    return list(dict.fromkeys(escolhidas))


def escolher_opcoes(
    s: SistemaLido,
    escolhas: dict[str, str] | None,
    nivel: int,
    rng: random.Random,
    expl: list[str],
    sorteadas: dict[str, str] | None = None,
) -> dict[str, Opcao]:
    """Percorre as etapas do livro: usa o que o jogador pediu e sorteia o resto.

    `sorteadas` repete um sorteio anterior: a ficha não muda quando a leitura a fundo revela
    novas opções.
    """
    feitas: dict[str, Opcao] = {}
    for e in s.etapas_de_escolha(nivel):
        pai = feitas[e.depende_de].nome if e.depende_de in feitas else None
        opcoes = e.opcoes_de(pai)
        if not opcoes:
            continue
        pedida = next(
            (
                o
                for o in opcoes
                if normalizar_id(o.nome) == normalizar_id((escolhas or {}).get(e.id, ""))
            ),
            None,
        )
        repetida = next(
            (o for o in opcoes
             if normalizar_id(o.nome) == normalizar_id((sorteadas or {}).get(e.id, ""))),
            None,
        )  # fmt: skip
        o = pedida or repetida or rng.choice(opcoes)
        feitas[e.id] = o
        pagina = f" (p. {o.pagina})" if o.pagina else ""
        como = "escolha" if pedida else "sorteada entre as opções do livro"
        expl.append(f"{e.nome}: {o.nome}{pagina}, {como}.")
    return feitas


def gerar_ficha(
    s: SistemaLido,
    *,
    arquetipo: str | None = None,
    nivel: int | None = None,
    nome: str | None = None,
    seed: int | None = None,
    escolhas: dict[str, str] | None = None,
    sorteadas: dict[str, str] | None = None,
) -> Ficha:
    rng = random.Random(seed)
    expl: list[str] = []

    nivel_final = 1
    if s.niveis.usa_niveis:
        nivel_final = max(1, nivel or s.niveis.nivel_inicial)
        if s.niveis.nivel_maximo:
            nivel_final = min(nivel_final, s.niveis.nivel_maximo)

    principal = s.etapa_principal()
    pedidas = dict(escolhas or {})
    if arquetipo and principal:
        if principal.opcao(arquetipo) is None:
            raise ValueError(f"{s.nome_arquetipo} desconhecido: {arquetipo!r}")
        pedidas[principal.id] = arquetipo
    feitas = escolher_opcoes(s, pedidas, nivel_final, rng, expl, sorteadas) if s.etapas else {}

    arq = feitas.get(principal.id) if principal else None
    if arq is None:
        arq = s.arquetipo(arquetipo)
        if arquetipo and arq is None:
            raise ValueError(f"{s.nome_arquetipo} desconhecido: {arquetipo!r}")
        if arq is None and s.arquetipos:
            arq = rng.choice(s.arquetipos)
            expl.append(f"{arq.nome}: sorteado entre as opções de {s.nome_arquetipo} do livro.")

    # Atributos importantes: os da escolha principal primeiro, depois os das outras escolhas.
    outras = [o for o in feitas.values() if o is not arq]
    chaves = list(dict.fromkeys(
        [*(arq.atributos_chave if arq else []), *(c for o in outras for c in o.atributos_chave)]
    ))  # fmt: skip

    ordem = prioridade(s, chaves, rng)
    atributos, como = gerar_atributos(s, ordem, rng) if ordem else ({}, "")
    if como:
        expl.append(f"Atributos: {como}.")
    if chaves:
        rotulo = arq.nome if arq else "as escolhas"
        nomes = ", ".join(s.atributo(c).nome for c in chaves)
        expl.append(f"Atributos mais importantes para {rotulo}: {nomes}.")

    # Bônus de atributo que as escolhas concedem
    for o in feitas.values():
        aplicados = []
        for aid, bonus in o.bonus_atributos.items():
            if aid in atributos:
                a = next(x for x in s.atributos if x.id == aid)
                maximo = limites(s, a)[1]
                novo = atributos[aid] + bonus
                atributos[aid] = min(novo, maximo) if maximo is not None else novo
                aplicados.append(f"{bonus:+d} {a.sigla or a.nome}")
        if aplicados:
            expl.append(f"Bônus de {o.nome}: {', '.join(aplicados)}.")

    calculados = [
        (d, v)
        for d, v in calcular_derivados(s, atributos, nivel_final, arq.nome if arq else None)
        if v is not None
    ]
    if calculados:
        expl.append(
            "Valores derivados pelas fórmulas do livro: "
            + "; ".join(f"{d.nome} = `{s.formula_de(d, arq)}` → {v}" for d, v in calculados[:4])
            + (
                "; dados contam pela média."
                if any(tem_dado(s.formula_de(d, arq)) for d, _ in calculados)
                else "."
            )  # fmt: skip
        )

    fontes = [*([arq] if arq else []), *outras]
    pericias_livro = list(dict.fromkeys(p for o in fontes for p in o.pericias))
    pericias = _escolher_pericias(s, pericias_livro, atributos, rng)
    if pericias:
        origem = (
            f"as de {', '.join(o.nome for o in fontes if o.pericias)}"
            if pericias_livro
            else "as ligadas aos melhores atributos"
        )
        expl.append(f"Perícias: {origem}.")

    poderes = []
    for o in fontes:
        poderes += list(o.habilidades) + list(getattr(o, "poderes", []))
    return Ficha(
        nome=nome or rng.choice(NOMES),
        sistema=SISTEMA_LIDO,
        tipo="pj",
        nivel=nivel_final,
        classe=arq.nome if arq else None,
        escolhas={e: o.nome for e, o in feitas.items()},
        atributos=atributos,
        metodo_atributos="livre",
        pericias=pericias,
        equipamento=list(dict.fromkeys(x for o in fontes for x in o.equipamento)),
        poderes=list(dict.fromkeys(poderes)),
        explicacoes=expl,
        tags=[arq.papel] if arq and arq.papel else [],
    )


def validar(s: SistemaLido, ficha: Ficha) -> list[Problema]:
    problemas: list[Problema] = []
    for a in s.atributos:
        v = ficha.atributos.get(a.id)
        if v is None:
            problemas.append(
                Problema(
                    gravidade="erro",
                    campo=f"atributos.{a.id}",
                    mensagem=f"falta o atributo {a.nome}",
                )
            )
            continue
        mn, mx = limites(s, a)
        if (mn is not None and v < mn) or (mx is not None and v > mx):
            faixa = f"{mn if mn is not None else '…'} a {mx if mx is not None else '…'}"
            problemas.append(
                Problema(
                    gravidade="erro",
                    campo=f"atributos.{a.id}",
                    mensagem=f"{a.nome} {v} fora da faixa do livro ({faixa})",
                )
            )
    if ficha.classe and s.arquetipos and s.arquetipo(ficha.classe) is None:
        problemas.append(
            Problema(
                gravidade="aviso",
                campo="classe",
                mensagem=f"{ficha.classe} não está entre os do livro",
            )
        )
    vida = s.derivado_do_tipo("vida")
    if vida:
        valor = dict(
            (d.id, v) for d, v in calcular_derivados(s, ficha.atributos, ficha.nivel, ficha.classe)
        )
        if valor.get(vida.id) is not None and valor[vida.id] <= 0:
            problemas.append(
                Problema(
                    gravidade="aviso",
                    campo="atributos",
                    mensagem=f"{vida.nome} ficou em {valor[vida.id]}",
                )
            )
    return problemas


def dicas_da_ficha(s: SistemaLido, ficha: Ficha) -> dict[str, str]:
    """O que o livro diz sobre as habilidades, poderes e perícias, pelo id normalizado do nome."""
    dicas: dict[str, str] = {}
    for e in s.etapas:
        o = e.opcao(ficha.escolhas.get(e.id))
        if not o:
            continue
        for h in (*o.habilidades_detalhe, *o.poderes_detalhe):
            if not h.resumo:
                continue
            texto = h.resumo
            if h.nivel is not None:
                texto += f" A partir de {s.niveis.nome} {h.nivel}."
            if h.pagina is not None:
                texto += f" Página {h.pagina}."
            dicas.setdefault(normalizar_id(h.nome), texto)
    for pericia in s.pericias:
        if pericia.descricao:
            dicas.setdefault(normalizar_id(pericia.nome), pericia.descricao)
    return dicas
