"""Análise de grupo e de encontro para D&D 5e: dicas explicáveis baseadas nas regras.

Nada aqui é "caixa-preta": cada achado vem de uma regra do sistema aplicada aos números das
fichas e dos monstros, e diz qual regra foi usada.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean

from oraculo.nucleo.analise import Achado, ordenar
from oraculo.nucleo.ficha import Ficha
from oraculo.nucleo.sistema import obter_regras
from oraculo.sistemas.dnd5e import modificador
from oraculo.sistemas.dnd5e.catalogo import Catalogo, Monstro
from oraculo.sistemas.dnd5e.gerador import calcular_ca
from oraculo.sistemas.dnd5e.srd import media_dado

_ABREV = {"for": "FOR", "des": "DES", "con": "CON", "int": "INT", "sab": "SAB", "car": "CAR"}
FISICOS = {"bludgeoning", "piercing", "slashing"}
TIPOS_PT = {
    "acid": "ácido", "bludgeoning": "contundente", "cold": "frio", "fire": "fogo",
    "force": "energia", "lightning": "elétrico", "necrotic": "necrótico",
    "piercing": "perfurante", "poison": "veneno", "psychic": "psíquico",
    "radiant": "radiante", "slashing": "cortante", "thunder": "trovejante",
}  # fmt: skip
PERICIAS_CHAVE = {
    "perception": "Percepção (emboscadas e armadilhas)",
    "insight": "Intuição (mentiras de NPCs)",
    "stealth": "Furtividade",
    "persuasion": "Persuasão",
    "arcana": "Arcanismo (magias e itens)",
    "athletics": "Atletismo",
}
EFEITOS_RESISTENCIA = {
    "des": "sopros de dragão, Bola de Fogo, armadilhas",
    "con": "venenos, doenças e manter a concentração",
    "sab": "Medo, Enfeitiçar Pessoa, Imobilizar Pessoa",
}
# Limiares de XP por personagem (fácil, médio, difícil, mortal) — regra de encontros 5e.
LIMIARES_XP = {
    1: (25, 50, 75, 100), 2: (50, 100, 150, 200), 3: (75, 150, 225, 400),
    4: (125, 250, 375, 500), 5: (250, 500, 750, 1100), 6: (300, 600, 900, 1400),
    7: (350, 750, 1100, 1700), 8: (450, 900, 1400, 2100), 9: (550, 1100, 1600, 2400),
    10: (600, 1200, 1900, 2800), 11: (800, 1600, 2400, 3600), 12: (1000, 2000, 3000, 4500),
    13: (1100, 2200, 3400, 5100), 14: (1250, 2500, 3800, 5700), 15: (1400, 2800, 4300, 6400),
    16: (1600, 3200, 4800, 7200), 17: (2000, 3900, 5900, 8800), 18: (2100, 4200, 6300, 9500),
    19: (2400, 4900, 7300, 10900), 20: (2800, 5700, 8500, 12700),
}  # fmt: skip
_ATAQUES_EXTRAS = {"barbaro": 5, "monge": 5, "paladino": 5, "patrulheiro": 5}


def prob_acerto(bonus: int, ca: float) -> float:
    """d20 + bônus >= CA; 1 natural sempre erra, 20 natural sempre acerta."""
    return min(0.95, max(0.05, (21 - (ca - bonus)) / 20))


def prob_falha(cd: int, bonus: int) -> float:
    return min(1.0, max(0.0, (cd - bonus - 1) / 20))


# --------------------------------------------------------------------------- perfil do PJ


@dataclass
class PerfilPJ:
    nome: str
    classe: str
    papel: str
    nivel: int
    pv: int
    ca: int
    resistencias: dict[str, int]
    proficiente_em: list[str]
    bonus_ataque: int
    dano_arma: float  # dano médio de um acerto com a arma principal
    ataques: int
    furtivo: float  # dano médio extra do ataque furtivo
    truque_bonus: int | None = None
    truque_dano: float = 0.0
    tipos_dano: set[str] = field(default_factory=set)
    tipos_arma: set[str] = field(default_factory=set)
    dano_magico: bool = False  # tem alguma fonte de dano mágico
    arma_magica: bool = False  # os ataques com arma contam como mágicos
    area: bool = False
    cura: bool = False
    distancia: bool = False
    controle: bool = False
    pericias: set[str] = field(default_factory=set)

    def dpr(self, ca_alvo: float) -> float:
        """Dano esperado por rodada contra uma CA (o melhor entre arma e truque)."""
        p = prob_acerto(self.bonus_ataque, ca_alvo)
        arma = self.ataques * p * self.dano_arma + (1 - (1 - p) ** self.ataques) * self.furtivo
        truque = 0.0
        if self.truque_bonus is not None:
            truque = prob_acerto(self.truque_bonus, ca_alvo) * self.truque_dano
        return max(arma, truque)


def perfil(ficha: Ficha, cat: Catalogo) -> PerfilPJ:
    regras = obter_regras("dnd5e")
    classe = regras.definicao.classe(ficha.classe)
    srd = cat.classe(classe.srd)
    d = regras.derivados(ficha)
    armas = {a.id: a for a in cat.armas}
    armaduras = {a.id: a for a in cat.armaduras}
    magias = {m.id: m for m in cat.magias}
    attrs = ficha.atributos
    prof = d["proficiencia"]

    armadura = next((armaduras[i] for i in ficha.equipamento
                     if i in armaduras and armaduras[i].categoria != "escudo"), None)  # fmt: skip
    escudo = next((armaduras[i] for i in ficha.equipamento
                   if i in armaduras and armaduras[i].categoria == "escudo"), None)  # fmt: skip
    minhas_armas = [armas[i] for i in ficha.equipamento if i in armas]
    principal = next((a for a in minhas_armas if a.alcance == "corpo_a_corpo"), None)
    principal = principal or (minhas_armas[0] if minhas_armas else None)

    if principal and (principal.alcance == "distancia" or "finesse" in principal.propriedades):
        mod = max(modificador(attrs["for"]), modificador(attrs["des"]))
        if principal.alcance == "distancia":
            mod = modificador(attrs["des"])
    else:
        mod = modificador(attrs["for"])

    n = ficha.nivel
    if classe.id == "guerreiro":
        ataques = 1 + (n >= 5) + (n >= 11) + (n >= 20)
    else:
        ataques = 1 + (n >= _ATAQUES_EXTRAS.get(classe.id, 99))
    if classe.id == "monge":
        ataques += 1  # artes marciais: ataque desarmado como ação bônus

    p = PerfilPJ(
        nome=ficha.nome,
        classe=classe.nome,
        papel=classe.papel or "",
        nivel=n,
        pv=d["pv_maximo"],
        ca=calcular_ca(attrs, classe.id, armadura, escudo),
        resistencias={a: d[f"resistencia_{a}"] for a in _ABREV},
        proficiente_em=list(classe.resistencias),
        bonus_ataque=prof + mod,
        dano_arma=(media_dado(principal.dano) + mod) if principal else 0.0,
        ataques=ataques,
        furtivo=3.5 * math.ceil(n / 2) if classe.id == "ladino" else 0.0,
        pericias=set(ficha.pericias),
    )
    p.tipos_arma = {a.tipo_dano for a in minhas_armas}
    p.tipos_dano = set(p.tipos_arma)
    p.distancia = any(a.alcance == "distancia" for a in minhas_armas)
    p.arma_magica = classe.id == "monge" and n >= 6  # Golpes de Ki
    p.dano_magico = p.arma_magica
    if classe.id == "paladino":
        p.cura = True  # Cura pelas Mãos
        if n >= 2:  # Destruição Divina: dano radiante extra
            p.tipos_dano.add("radiant")
            p.dano_magico = True

    mod_conj = modificador(attrs[srd.conjuracao]) if srd.conjuracao else 0
    escala = 1 + (n >= 5) + (n >= 11) + (n >= 17)
    for mid in ficha.poderes:
        m = magias.get(mid)
        if not m:
            continue
        p.cura |= m.cura
        p.controle |= m.funcao == "controle"
        if m.dano:
            p.dano_magico = True
            if m.tipo_dano:
                p.tipos_dano.add(m.tipo_dano)
            p.area |= m.area
            p.distancia |= m.ataque == "ranged" or m.resistencia is not None
            if m.circulo == 0 and m.ataque:
                dano = media_dado(m.dano) * escala
                if dano > p.truque_dano:
                    p.truque_dano, p.truque_bonus = dano, prof + mod_conj
    return p


# --------------------------------------------------------------------------- grupo


def analisar_grupo(fichas: list[Ficha], cat: Catalogo) -> list[Achado]:
    if not fichas:
        return []
    pjs = [perfil(f, cat) for f in fichas]
    achados: list[Achado] = []
    n_monstros = max(1, len(cat.monstros))

    # Papéis
    curandeiros = [p.nome for p in pjs if p.cura]
    if not curandeiros:
        achados.append(Achado(
            severidade="alerta", categoria="Papéis", titulo="Ninguém do grupo cura",
            detalhe="Nenhuma ficha tem magia de cura ou Cura pelas Mãos. Um aliado caído só "
                    "volta com poções ou se estabilizar sozinho.",
            regra="Personagem com 0 PV fica inconsciente e faz testes contra a morte.",
            sugestao="Inclua um clérigo, druida, bardo ou paladino, ou distribua poções de cura.",
        ))  # fmt: skip
    else:
        achados.append(Achado(
            severidade="ok", categoria="Papéis", titulo="Há cura no grupo",
            detalhe=f"Podem curar: {', '.join(curandeiros)}.",
            regra="Magias de cura e Cura pelas Mãos recuperam PV e levantam aliados caídos.",
        ))  # fmt: skip
    linha_de_frente = [p for p in pjs if p.ca >= 16 and p.pv >= 8 * p.nivel]
    if not linha_de_frente:
        achados.append(Achado(
            severidade="atencao", categoria="Papéis", titulo="Linha de frente frágil",
            detalhe="Nenhum personagem combina CA 16+ com PV altos. Os inimigos corpo a corpo "
                    "vão alcançar os conjuradores rapidamente.",
            regra="CA define a chance de ser atingido; PV, quantos golpes se aguenta.",
            sugestao="Um guerreiro, paladino ou bárbaro segura melhor a frente.",
        ))  # fmt: skip

    # Testes de resistência
    for a, efeitos in EFEITOS_RESISTENCIA.items():
        media = mean(p.resistencias[a] for p in pjs)
        prof = [p.nome for p in pjs if a in p.proficiente_em]
        pior = min(pjs, key=lambda p: p.resistencias[a])
        if media < 2 or not prof:
            severidade = "alerta" if a == "sab" and not prof else "atencao"
            achados.append(Achado(
                severidade=severidade, categoria="Resistências",
                titulo=f"Resistência de {_ABREV[a]} fraca (média {media:+.1f})",
                detalhe=f"Efeitos que pedem {_ABREV[a]}: {efeitos}. "
                        f"Proficientes: {', '.join(prof) or 'ninguém'}. "
                        f"Mais vulnerável: {pior.nome} ({pior.resistencias[a]:+d}).",
                regra=f"Teste de resistência = d20 + modificador de {_ABREV[a]} "
                      "(+ proficiência se a classe tiver).",
                sugestao="Contra esses efeitos: posicionamento, Proteção contra o Bem e o Mal, "
                         "ou um paladino de nível 6 (Aura de Proteção).",
            ))  # fmt: skip

    # Tipos de dano
    resistem_fisico = [m for m in cat.monstros if m.fisico_nao_magico]
    if not any(p.dano_magico for p in pjs):
        fortes = [m for m in cat.monstros if m.cr >= 5]
        pct_fortes = len([m for m in fortes if m.fisico_nao_magico]) / max(1, len(fortes))
        achados.append(Achado(
            severidade="alerta", categoria="Dano",
            titulo="Todo o dano do grupo é físico e não mágico",
            detalhe=f"{len(resistem_fisico)} dos {n_monstros} monstros do SRD resistem ou são "
                    f"imunes a esse dano, e entre os de CR 5+ são {pct_fortes:.0%} "
                    "(gárgulas, lobisomens, elementais, demônios...).",
            regra="Resistência corta o dano pela metade; imunidade zera.",
            sugestao="Armas mágicas ou um conjurador com truques de dano resolvem.",
        ))  # fmt: skip
    for p in pjs:
        if p.tipos_dano and len(p.tipos_dano) == 1:
            tipo = next(iter(p.tipos_dano))
            imunes = [m for m in cat.monstros if tipo in m.imunidades_dano]
            if len(imunes) / n_monstros >= 0.15:
                achados.append(Achado(
                    severidade="atencao", categoria="Dano",
                    titulo=f"{p.nome} só causa dano de {TIPOS_PT.get(tipo, tipo)}",
                    detalhe=f"{len(imunes)} monstros do SRD são imunes a esse tipo.",
                    regra="Imunidade a um tipo de dano zera todo o dano daquele tipo.",
                    sugestao="Dê a esse personagem uma segunda opção de dano.",
                ))  # fmt: skip

    if not any(p.area for p in pjs):
        achados.append(Achado(
            severidade="atencao", categoria="Dano", titulo="Nenhum dano em área",
            detalhe="Hordas (goblins, zumbis, lobos) exigem um ataque por inimigo. "
                    "Encontros com muitos monstros vão durar mais e custar mais PV.",
            regra="Magias de área atingem todas as criaturas na região de uma vez.",
            sugestao="Um mago ou feiticeiro com Mãos Flamejantes ou Bola de Fogo.",
        ))  # fmt: skip
    if not any(p.distancia for p in pjs):
        voadores = [m for m in cat.monstros if m.voa]
        achados.append(Achado(
            severidade="alerta", categoria="Dano", titulo="Ninguém ataca à distância",
            detalhe=f"{len(voadores)} monstros do SRD voam. Um inimigo voando fora de alcance "
                    "pode atacar o grupo sem ser atingido.",
            regra="Ataques corpo a corpo só alcançam criaturas a 1,5 m (ou 3 m com alcance).",
            sugestao="Arcos, bestas ou truques como Raio de Fogo.",
        ))  # fmt: skip

    # Perícias
    cobertas = set().union(*(p.pericias for p in pjs))
    faltando = [desc for pid, desc in PERICIAS_CHAVE.items() if pid not in cobertas]
    if faltando:
        achados.append(Achado(
            severidade="info", categoria="Perícias", titulo="Perícias sem ninguém treinado",
            detalhe="; ".join(faltando) + ".",
            regra="Sem proficiência, o teste usa só o modificador do atributo.",
            sugestao="Antecedentes e raças podem cobrir essas perícias.",
        ))  # fmt: skip
    return ordenar(achados)


# --------------------------------------------------------------------------- encontro


@dataclass
class ResumoEncontro:
    xp_total: int
    xp_ajustado: float
    dificuldade_oficial: str
    dpr_grupo: float
    dpr_monstros: float
    rodadas_para_vencer: float
    rodadas_para_perder: float


def _multiplicador(n_monstros: int, n_pjs: int) -> float:
    faixas = (0.5, 1, 1.5, 2, 2.5, 3, 4, 5)
    i = 1 if n_monstros <= 1 else 2 if n_monstros == 2 else 3 if n_monstros <= 6 else (
        4 if n_monstros <= 10 else 5 if n_monstros <= 14 else 6)  # fmt: skip
    i += 1 if n_pjs < 3 else -1 if n_pjs >= 6 else 0
    return faixas[i]


def dificuldade_oficial(niveis: list[int], xps: list[int]) -> tuple[float, str]:
    xp_aj = sum(xps) * _multiplicador(len(xps), len(niveis))
    limiares = [sum(LIMIARES_XP[n][i] for n in niveis) for i in range(4)]
    rotulo = "Trivial"
    for nome, limiar in zip(("Fácil", "Médio", "Difícil", "Mortal"), limiares, strict=True):
        if xp_aj >= limiar:
            rotulo = nome
    return xp_aj, rotulo


def _fator_defesa(m: Monstro, pj: PerfilPJ) -> float:
    """Quanto do dano do PJ passa pelas defesas do monstro (1 = tudo, 0.5 = resistência)."""
    tipos = pj.tipos_dano or {"bludgeoning"}
    melhor = 0.0
    for t in tipos:
        fator = 1.0
        if t in m.imunidades_dano:
            fator = 0.0
        elif t in m.resistencias_dano:
            fator = 0.5
        elif t in m.vulnerabilidades_dano:
            fator = 2.0
        if t in FISICOS and t in pj.tipos_arma and not pj.arma_magica and m.fisico_nao_magico:
            fator = 0.0 if m.fisico_nao_magico == "imune" else min(fator, 0.5)
        melhor = max(melhor, fator)
    return melhor


def _dano_turno(m: Monstro, ca_alvo: float) -> float:
    total = 0.0
    for nome in m.rotina:
        a = m.ataque(nome)
        if a.bonus_ataque is not None:
            total += prob_acerto(a.bonus_ataque, ca_alvo) * a.dano_medio
    return total


def _pico_turno(m: Monstro) -> tuple[float, str]:
    """Maior dano que o monstro causa num único turno (se tudo acertar)."""
    rotina = sum(m.ataque(n).dano_medio for n in m.rotina)
    especiais = [(a.dano_medio, a.nome) for a in m.ataques if a.limitado]
    melhor_especial = max(especiais, default=(0.0, ""))
    if melhor_especial[0] > rotina:
        return melhor_especial
    return rotina, "ataques normais"


def analisar_encontro(
    fichas: list[Ficha], monstros: list[tuple[Monstro, int]], cat: Catalogo
) -> tuple[ResumoEncontro, list[Achado]]:
    pjs = [perfil(f, cat) for f in fichas]
    lista = [m for m, q in monstros for _ in range(q)]
    if not pjs or not lista:
        raise ValueError("informe ao menos um personagem e um monstro")
    achados: list[Achado] = []
    ca_grupo = mean(p.ca for p in pjs)

    xp_aj, oficial = dificuldade_oficial([p.nivel for p in pjs], [m.xp for m in lista])
    dpr_grupo = sum(mean(p.dpr(m.ca) * _fator_defesa(m, p) for m in lista) for p in pjs)
    dpr_monstros = sum(_dano_turno(m, ca_grupo) for m in lista)
    vencer = sum(m.pv for m in lista) / max(dpr_grupo, 0.1)
    perder = sum(p.pv for p in pjs) / max(dpr_monstros, 0.1)
    resumo = ResumoEncontro(
        xp_total=sum(m.xp for m in lista),
        xp_ajustado=xp_aj,
        dificuldade_oficial=oficial,
        dpr_grupo=dpr_grupo,
        dpr_monstros=dpr_monstros,
        rodadas_para_vencer=vencer,
        rodadas_para_perder=perder,
    )

    # Balanço geral
    if perder < vencer:
        achados.append(Achado(
            severidade="alerta", categoria="Balanço", titulo="O grupo tende a cair antes",
            detalhe=f"Estimativa: o grupo precisa de {vencer:.1f} rodadas para vencer, mas os "
                    f"monstros derrubam o grupo em {perder:.1f}.",
            regra="Rodadas = PV totais do lado oposto ÷ dano médio por rodada "
                  "(chance de acerto × dano médio, com resistências).",
            sugestao="Reduza monstros, dê terreno vantajoso ao grupo ou uma rota de fuga.",
        ))  # fmt: skip
    elif vencer <= 1.5:
        achados.append(Achado(
            severidade="info", categoria="Balanço", titulo="Luta muito curta",
            detalhe=f"O grupo deve vencer em cerca de {vencer:.1f} rodada(s).",
            regra="Rodadas = PV dos monstros ÷ dano médio do grupo por rodada.",
            sugestao="Bom para aquecimento; para tensão, aumente os PV ou adicione reforços.",
        ))  # fmt: skip

    # Economia de ações
    tipos = {m.id: m for m in lista}
    if len(lista) == 1 and len(pjs) >= 3 and not lista[0].acoes_lendarias:
        achados.append(Achado(
            severidade="atencao", categoria="Economia de ações",
            titulo=f"{lista[0].nome} sozinho age 1 vez para cada {len(pjs)} do grupo",
            detalhe="Monstros solo sem ações lendárias costumam ser cercados e derrotados "
                    "antes de usar suas melhores habilidades.",
            regra="Cada criatura tem uma ação por turno; ações lendárias dão turnos extras.",
            sugestao="Adicione lacaios ou divida os PV do chefe em duas fases.",
        ))  # fmt: skip
    if len(lista) >= 2 * len(pjs) and not any(p.area for p in pjs):
        achados.append(Achado(
            severidade="alerta", categoria="Economia de ações",
            titulo=f"{len(lista)} inimigos e nenhum dano em área",
            detalhe="Cada monstro precisa ser derrubado individualmente; o volume de ataques "
                    "inimigos por rodada será alto.",
            regra="Sem área, o grupo derruba no máximo um inimigo por ataque.",
            sugestao="Use menos monstros mais fortes, ou dê ao grupo um gargalo para lutar.",
        ))  # fmt: skip

    # Defesas dos monstros contra o dano do grupo
    for m in tipos.values():
        bloqueados = [p.nome for p in pjs if _fator_defesa(m, p) == 0]
        reduzidos = [p.nome for p in pjs if 0 < _fator_defesa(m, p) <= 0.5]
        dobrados = [p.nome for p in pjs if _fator_defesa(m, p) >= 2]
        if bloqueados:
            achados.append(Achado(
                severidade="alerta", categoria="Defesas", titulo=f"{m.nome} anula o dano de "
                f"{', '.join(bloqueados)}",
                detalhe=_descrever_defesas(m),
                regra="Imunidade zera o dano daquele tipo.",
                sugestao="Dê armas mágicas, prateadas ou outro tipo de dano a esses personagens.",
            ))  # fmt: skip
        if reduzidos:
            achados.append(Achado(
                severidade="atencao", categoria="Defesas",
                titulo=f"{m.nome} reduz à metade o dano de {', '.join(reduzidos)}",
                detalhe=_descrever_defesas(m),
                regra="Resistência divide o dano daquele tipo por 2.",
            ))  # fmt: skip
        if dobrados:
            achados.append(Achado(
                severidade="ok", categoria="Defesas",
                titulo=f"{', '.join(dobrados)} causa dano dobrado em {m.nome}",
                detalhe=_descrever_defesas(m),
                regra="Vulnerabilidade dobra o dano daquele tipo.",
            ))  # fmt: skip

    # Testes de resistência que exploram fraquezas do grupo
    for m in tipos.values():
        for a in m.ataques:
            if a.cd is None or not a.resistencia:
                continue
            falhas = {p.nome: prob_falha(a.cd, p.resistencias[a.resistencia]) for p in pjs}
            media_falha = mean(falhas.values())
            if media_falha >= 0.6:
                controle = a.dano_medio == 0
                pior = max(falhas, key=falhas.get)
                achados.append(Achado(
                    severidade="alerta" if controle else "atencao", categoria="Resistências",
                    titulo=f"{a.nome} ({m.nome}): o grupo falha {media_falha:.0%} das vezes",
                    detalhe=f"Teste de {_ABREV[a.resistencia]} CD {a.cd}"
                            f"{', em área' if a.area else ''}. {pior} falha {falhas[pior]:.0%}."
                            + (" Efeito de controle: tira personagens da luta." if controle
                               else f" Dano médio {a.dano_medio:.0f}."),
                    regra="Falha se d20 + bônus de resistência < CD.",
                    sugestao="Espalhe o grupo (contra área) ou prepare Proteção contra o Bem e "
                             "o Mal / Restauração Menor.",
                ))  # fmt: skip

    # Risco de derrubar alguém num único turno
    for m in tipos.values():
        pico, fonte = _pico_turno(m)
        caem = [p.nome for p in pjs if pico >= p.pv]
        if caem:
            achados.append(Achado(
                severidade="alerta", categoria="Risco",
                titulo=f"{m.nome} pode derrubar {', '.join(caem)} num único turno",
                detalhe=f"Dano máximo esperado num turno: {pico:.0f} ({fonte}).",
                regra="Com 0 PV o personagem cai; dano restante ≥ PV máximo mata na hora.",
                sugestao="Mantenha os personagens frágeis longe ou reduza o dano dessa ação.",
            ))  # fmt: skip

    # Voo
    voadores = [m.nome for m in tipos.values() if m.voa]
    if voadores and not any(p.distancia for p in pjs):
        achados.append(Achado(
            severidade="alerta", categoria="Mobilidade",
            titulo=f"{', '.join(voadores)} voa(m) e ninguém ataca à distância",
            detalhe="Um voador pode atacar e se afastar para fora do alcance corpo a corpo.",
            regra="Ataques corpo a corpo só alcançam criaturas adjacentes.",
            sugestao="Arcos, bestas, truques de dano ou lutar em ambiente fechado.",
        ))  # fmt: skip

    # Chance de acerto
    acertos = [prob_acerto(a.bonus_ataque, ca_grupo) for m in lista for n in m.rotina
               if (a := m.ataque(n)).bonus_ataque is not None]  # fmt: skip
    if acertos and mean(acertos) >= 0.75:
        achados.append(Achado(
            severidade="atencao", categoria="Acerto",
            titulo=f"Os monstros acertam o grupo {mean(acertos):.0%} das vezes",
            detalhe=f"CA média do grupo: {ca_grupo:.1f}.",
            regra="Acerta se d20 + bônus de ataque ≥ CA.",
            sugestao="Escudos, Armadura Arcana ou cobertura reduzem a chance de acerto.",
        ))  # fmt: skip
    acerto_grupo = mean(prob_acerto(p.bonus_ataque, m.ca) for p in pjs for m in lista)
    if acerto_grupo <= 0.4:
        achados.append(Achado(
            severidade="atencao", categoria="Acerto",
            titulo=f"O grupo acerta só {acerto_grupo:.0%} dos ataques",
            detalhe="A CA dos monstros é alta para o bônus de ataque atual do grupo.",
            regra="Acerta se d20 + bônus de ataque ≥ CA.",
            sugestao="Magias com teste de resistência ignoram a CA; vantagem (flanquear, "
                     "Fogo das Fadas) ajuda muito.",
        ))  # fmt: skip

    lendarios = [m.nome for m in tipos.values() if m.resistencia_lendaria]
    if lendarios and any(p.controle for p in pjs):
        achados.append(Achado(
            severidade="info", categoria="Controle",
            titulo=f"{', '.join(lendarios)} tem Resistência Lendária",
            detalhe="As primeiras magias de controle vão ser anuladas.",
            regra="Resistência Lendária transforma uma falha em sucesso (geralmente 3x/dia).",
            sugestao="Gaste a resistência com magias baratas antes da magia decisiva.",
        ))  # fmt: skip
    return resumo, ordenar(achados)


def _descrever_defesas(m: Monstro) -> str:
    partes = []
    if m.imunidades_dano:
        partes.append("imune a " + ", ".join(TIPOS_PT.get(t, t) for t in m.imunidades_dano))
    if m.resistencias_dano:
        partes.append("resiste a " + ", ".join(TIPOS_PT.get(t, t) for t in m.resistencias_dano))
    if m.fisico_nao_magico:
        partes.append(f"{m.fisico_nao_magico} a dano físico de armas não mágicas")
    if m.vulnerabilidades_dano:
        partes.append(
            "vulnerável a " + ", ".join(TIPOS_PT.get(t, t) for t in m.vulnerabilidades_dano)
        )
    return f"{m.nome}: " + "; ".join(partes) + "." if partes else m.nome
