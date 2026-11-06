"""Transforma um sistema lido na ficha do jogador, em PDF (ver oraculo.fichas_pdf).

A ficha segue o que a leitura entendeu do livro: atributos, valores, perícias, escolhas de criação
e as partes que o próprio livro manda anotar (`SistemaLido.ficha`).
"""

from __future__ import annotations

import re

from oraculo.fichas_pdf import (
    BlocoImpresso,
    FichaImpressa,
    Tema,
    ValorImpresso,
    atributo_em_branco,
    tema_para,
)
from oraculo.nucleo.ficha import Ficha
from oraculo.sistemas.generico.gerador import calcular_derivados
from oraculo.sistemas.generico.modelo import BlocoFicha, SistemaLido, normalizar_id


def tema_do_sistema(s: SistemaLido) -> Tema:
    return tema_para(s.genero, s.nome, s.ambientacao)


def ficha_impressa(s: SistemaLido, ficha: Ficha) -> FichaImpressa:
    atributos = []
    for a in s.atributos:
        if a.id in ficha.atributos:
            valor = ficha.atributos[a.id]
            mod = s.modificador_de(valor)
            atributos.append((a.sigla or a.nome, valor, None if mod is None else int(mod)))
    # Um valor sem fórmula (depende de uma escolha do jogador) fica com o espaço para preencher.
    valores = [
        ValorImpresso(d.nome, "" if v is None else str(v), anotar=d.tipo in ("vida", "recurso"))
        for d, v in calcular_derivados(s, ficha.atributos, ficha.nivel, ficha.classe)
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
    blocos = _blocos_do_livro(s)
    if s.pericias:
        blocos.insert(0, _bloco_pericias(s, ficha.pericias))
    elif ficha.pericias:
        secoes.append(("Perícias", [", ".join(ficha.pericias)]))
    # O que a ficha gerada ainda não traz fica como espaço para o jogador preencher.
    ja_preenchido = {
        "Habilidades e poderes": bool(habilidades),
        "Equipamento": bool(ficha.equipamento),
        "Aparência e história": bool(ficha.narrativa),
    }
    blocos += [b for b in _blocos_padrao(s) if not ja_preenchido.get(b.titulo)]
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
        blocos=blocos,
        narrativa=dict(ficha.narrativa),
        credito=_credito(s),
    )


def ficha_em_branco(s: SistemaLido) -> FichaImpressa:
    """A ficha deste sistema para preencher, com as contas e as opções lidas do livro."""
    escolhas = [e for e in s.etapas if e.tipo == "escolha"]
    campos = ["Nome", "Jogador", *(e.nome for e in escolhas)]
    if not escolhas and s.arquetipos:
        campos.append(s.nome_arquetipo.capitalize())
    if s.niveis.usa_niveis:
        campos.append(s.niveis.nome.capitalize())
    contas = []
    if s.modificador:
        contas.append(f"Modificador de atributo: {formula_legivel(s, s.modificador)}")
    for d in s.derivados:
        if d.formula or d.explicacao:
            conta = formula_legivel(s, d.formula) if d.formula else d.explicacao
            contas.append(f"{d.nome}: {conta}")
    opcoes = []
    for e in escolhas:
        nomes = [f"{o.nome} (p. {o.pagina})" if o.pagina else o.nome for o in e.opcoes]
        if nomes:
            opcoes.append(f"{e.nome}: {', '.join(nomes)}")
    if not escolhas and s.arquetipos:
        opcoes.append(f"{s.nome_arquetipo.capitalize()}: {', '.join(a.nome for a in s.arquetipos)}")
    com_modificador = s.modificador_de(10) is not None
    blocos = _blocos_do_livro(s)
    if s.pericias:
        blocos.insert(0, _bloco_pericias(s, []))
    else:
        blocos.insert(0, BlocoImpresso("Perícias", linhas=3))
    return FichaImpressa(
        nome="",
        sistema=s.nome,
        subtitulo="Ficha em branco",
        atributos=[atributo_em_branco(a.sigla or a.nome, com_modificador) for a in s.atributos],
        valores=[ValorImpresso(d.nome, anotar=d.tipo in ("vida", "recurso")) for d in s.derivados],
        campos=campos,
        blocos=[
            *blocos,
            *_blocos_padrao(s),
        ],
        secoes=[
            ("Como calcular", contas),
            ("Opções do livro", opcoes),
            ("Como jogar", _como_jogar(s)),
        ],
        credito=_credito(s),
    )


def formula_legivel(s: SistemaLido, formula: str) -> str:
    """Troca os ids das fórmulas pelos nomes do livro: "mod_des" vira "modificador de Destreza"."""
    # O LLM às vezes chama o atributo pelo nome inteiro (mod_destreza), e não pelo id (mod_des).
    nomes = {chave: a.nome for a in s.atributos for chave in (a.id, normalizar_id(a.nome))}
    nomes |= {d.id: d.nome for d in s.derivados if d.id}
    nomes |= {"nivel": s.niveis.nome, "pv_max": "Pontos de Vida máximos"}
    if s.niveis.variavel:
        nomes[s.niveis.variavel] = s.niveis.nome

    def trocar(achado: re.Match) -> str:
        palavra = achado.group(0)
        if palavra.startswith("mod_") and palavra[4:] in nomes:
            return f"modificador de {nomes[palavra[4:]]}"
        return nomes.get(palavra, palavra)

    texto = re.sub(r"[^\W\d]\w*", trocar, formula)
    texto = re.sub(r"\s*\+\s*0\b(?!\.)", "", texto)
    texto = re.sub(r"\s*\*\s*", " x ", texto)
    for funcao, sentido in (("piso", "baixo"), ("teto", "cima")):
        texto = re.sub(
            rf"\b{funcao}\(((?:[^()]|\([^()]*\))*)\)", rf"\1, arredondado para {sentido}", texto
        )
    return texto


def _bloco_pericias(s: SistemaLido, treinadas: list[str]) -> BlocoImpresso:
    marcadas = {normalizar_id(p) for p in treinadas}
    itens = [ValorImpresso(p.nome, marcado=normalizar_id(p.nome) in marcadas) for p in s.pericias]
    conhecidas = {normalizar_id(p.nome) for p in s.pericias}
    # Perícias que a opção escolhida concede e que não estavam na lista lida também vão marcadas.
    itens += [
        ValorImpresso(p, marcado=True) for p in treinadas if normalizar_id(p) not in conhecidas
    ]
    return BlocoImpresso("Perícias", "marcas", itens)


def _blocos_do_livro(s: SistemaLido) -> list[BlocoImpresso]:
    return [_impresso(b) for b in s.ficha]


def _impresso(b: BlocoFicha) -> BlocoImpresso:
    if b.tipo == "texto":
        return BlocoImpresso(
            b.titulo, itens=[ValorImpresso(i) for i in b.itens], linhas=2 if b.itens else 4
        )
    anotar = b.tipo == "contadores"
    return BlocoImpresso(b.titulo, "valores", [ValorImpresso(i, anotar=anotar) for i in b.itens])


def _blocos_padrao(s: SistemaLido) -> list[BlocoImpresso]:
    """O que toda ficha precisa e o livro não trouxe com outro título."""
    do_livro = {normalizar_id(b.titulo) for b in s.ficha}
    padrao = (("Habilidades e poderes", 6), ("Equipamento", 4), ("Aparência e história", 4))
    return [BlocoImpresso(t, linhas=n) for t, n in padrao if normalizar_id(t) not in do_livro]


def _como_jogar(s: SistemaLido) -> list[str]:
    return [x for x in (s.mecanica.resolucao, s.mecanica.criticos, s.mecanica.dano_explicacao) if x]


def _credito(s: SistemaLido) -> str:
    autoria = f" ({s.autores})" if s.autores else ""
    return f"Regras de {s.nome}{autoria}"
