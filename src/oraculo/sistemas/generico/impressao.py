"""Transforma uma ficha de um sistema lido na ficha impressa (ver oraculo.fichas_pdf)."""

from __future__ import annotations

from oraculo.fichas_pdf import FichaImpressa, Tema, ValorImpresso, atributo_em_branco, tema_para
from oraculo.nucleo.ficha import Ficha
from oraculo.sistemas.generico.gerador import calcular_derivados
from oraculo.sistemas.generico.modelo import SistemaLido


def tema_do_sistema(s: SistemaLido) -> Tema:
    return tema_para(s.genero, s.nome, s.ambientacao)


def ficha_impressa(s: SistemaLido, ficha: Ficha) -> FichaImpressa:
    atributos = []
    for a in s.atributos:
        if a.id in ficha.atributos:
            valor = ficha.atributos[a.id]
            mod = s.modificador_de(valor)
            atributos.append((a.sigla or a.nome, valor, None if mod is None else int(mod)))
    valores = [
        ValorImpresso(d.nome, str(v), anotar=d.tipo in ("vida", "recurso"))
        for d, v in calcular_derivados(s, ficha.atributos, ficha.nivel, ficha.classe)
        if v is not None
    ]
    partes = [ficha.escolhas.get(e.id) for e in s.etapas if e.id in ficha.escolhas]
    if not partes and ficha.classe:
        partes = [ficha.classe]
    if s.niveis.usa_niveis:
        partes.append(f"{s.niveis.nome} {ficha.nivel}")

    habilidades = []
    for e in s.etapas:
        o = e.opcao(ficha.escolhas.get(e.id))
        if not o:
            continue
        for h in o.habilidades_detalhe:
            if h.nivel is None or h.nivel <= ficha.nivel:
                pagina = f" (p. {h.pagina})" if h.pagina else ""
                resumo = f": {h.resumo}" if h.resumo else ""
                habilidades.append(f"{h.nome}{resumo}{pagina}")
    if not habilidades:
        habilidades = list(ficha.poderes)

    secoes = [("Habilidades e poderes", habilidades)]
    if ficha.pericias:
        secoes.append(("Perícias", [", ".join(ficha.pericias)]))
    if ficha.equipamento:
        secoes.append(("Equipamento", [", ".join(ficha.equipamento)]))
    secoes.append(("Como jogar", _como_jogar(s)))
    return FichaImpressa(
        nome=ficha.nome,
        sistema=s.nome,
        subtitulo=" · ".join(p for p in partes if p),
        atributos=atributos,
        valores=valores,
        secoes=secoes,
        narrativa=dict(ficha.narrativa),
        credito=_credito(s),
    )


def ficha_em_branco(s: SistemaLido) -> FichaImpressa:
    """A ficha deste sistema para preencher à mão, com as contas e as opções lidas do livro."""
    escolhas = [e for e in s.etapas if e.tipo == "escolha"]
    campos = ["Nome", "Jogador", *(e.nome for e in escolhas)]
    if not escolhas and s.arquetipos:
        campos.append(s.nome_arquetipo.capitalize())
    if s.niveis.usa_niveis:
        campos.append(s.niveis.nome.capitalize())
    contas = [
        f"{d.nome}: {d.explicacao or d.formula}" for d in s.derivados if d.explicacao or d.formula
    ]
    if s.modificador:
        contas.insert(0, f"Modificador de atributo: {s.modificador}")
    opcoes = []
    for e in escolhas:
        nomes = [f"{o.nome} (p. {o.pagina})" if o.pagina else o.nome for o in e.opcoes]
        if nomes:
            opcoes.append(f"{e.nome}: {', '.join(nomes)}")
    if not escolhas and s.arquetipos:
        opcoes.append(f"{s.nome_arquetipo.capitalize()}: {', '.join(a.nome for a in s.arquetipos)}")
    com_modificador = s.modificador_de(10) is not None
    return FichaImpressa(
        nome="",
        sistema=s.nome,
        subtitulo="Ficha em branco",
        atributos=[atributo_em_branco(a.sigla or a.nome, com_modificador) for a in s.atributos],
        valores=[ValorImpresso(d.nome, anotar=d.tipo in ("vida", "recurso")) for d in s.derivados],
        campos=campos,
        pautadas=[
            ("Habilidades e poderes", 6),
            ("Perícias", 3),
            ("Equipamento", 4),
            ("Aparência e história", 4),
        ],
        secoes=[
            ("Como calcular", contas),
            ("Opções do livro", opcoes),
            ("Como jogar", _como_jogar(s)),
        ],
        credito=_credito(s),
    )


def _como_jogar(s: SistemaLido) -> list[str]:
    return [x for x in (s.mecanica.resolucao, s.mecanica.criticos, s.mecanica.dano_explicacao) if x]


def _credito(s: SistemaLido) -> str:
    autoria = f" ({s.autores})" if s.autores else ""
    return f"Regras de {s.nome}{autoria}"
