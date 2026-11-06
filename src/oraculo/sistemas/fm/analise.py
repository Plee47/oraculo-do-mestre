"""Análise de grupo em Feiticeiros & Maldições: papéis, resistências, alcance e origens.

Cada achado cita a regra do sistema que o gerou. O livro base não traz bestiário, então ainda
não há análise de encontro para este sistema.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean

from oraculo.nucleo.analise import Achado, ordenar
from oraculo.nucleo.ficha import Ficha
from oraculo.sistemas.fm import RESISTENCIAS, Regras, resistencias_treinadas


@dataclass(frozen=True)
class PerfilFM:
    nome: str
    especializacao: str
    papel: str
    origem: str
    nivel: int
    pv: int
    defesa: int
    energia: int
    tipo_energia: str  # "pe" ou "estamina"
    resistencias: dict[str, int]
    treinado_em: frozenset[str]
    distancia: bool
    cura: bool


def perfil(ficha: Ficha, regras: Regras | None = None) -> PerfilFM:
    regras = regras or Regras()
    classe = regras.definicao.classe(ficha.classe)
    if classe is None:
        raise ValueError(f"{ficha.nome}: especialização inválida ({ficha.classe!r})")
    d = regras.derivados(ficha)
    treinadas, _ = resistencias_treinadas(ficha, classe, regras.extras["resistencias"])
    tipo = "estamina" if "estamina" in d else "pe"
    return PerfilFM(
        nome=ficha.nome,
        especializacao=classe.nome,
        papel=classe.papel or "combatente",
        origem=ficha.origem or "",
        nivel=ficha.nivel,
        pv=d["pv_maximo"],
        defesa=d["defesa"],
        energia=d[tipo],
        tipo_energia=tipo,
        resistencias={r: d[f"resistencia_{r}"] for r in RESISTENCIAS},
        treinado_em=frozenset(treinadas),
        distancia=classe.id in regras.extras["armas_distancia"],
        cura=classe.papel == "suporte",
    )


def analisar_grupo(fichas: list[Ficha]) -> list[Achado]:
    if not fichas:
        return []
    regras = Regras()
    ex = regras.extras
    pjs = [perfil(f, regras) for f in fichas]
    achados: list[Achado] = []

    # Papéis
    suportes = [p.nome for p in pjs if p.cura]
    if not suportes:
        achados.append(Achado(
            severidade="alerta", categoria="Papéis", titulo="Ninguém cura com energia reversa",
            detalhe="O grupo não tem Suporte. Fora de descansos, os PV perdidos só voltam com "
                    "itens de cura ou feitiços curativos.",
            regra="O Suporte é o especialista em energia reversa, a principal fonte de cura.",
            sugestao="Inclua um Suporte, monte um feitiço curativo na técnica de alguém ou "
                     "leve itens de Medicina.",
        ))  # fmt: skip
    else:
        achados.append(Achado(
            severidade="ok", categoria="Papéis", titulo="Há cura no grupo",
            detalhe=f"Suporte: {', '.join(suportes)}.",
            regra="O Suporte cura com energia reversa e amplia as capacidades dos aliados.",
        ))  # fmt: skip
    frente = [p for p in pjs if p.papel == "combatente"]
    if not frente:
        achados.append(Achado(
            severidade="atencao", categoria="Papéis", titulo="Sem linha de frente",
            detalhe="Ninguém é Lutador, Especialista em Combate ou Restringido. Maldições "
                    "corpo a corpo chegam direto em quem tem PV e Defesa menores.",
            regra="Especializações de combate têm mais PV por nível (d10 ou d12, contra d8).",
            sugestao="Um Lutador ou Especialista em Combate segura a frente.",
        ))  # fmt: skip
    if not any(p.tipo_energia == "pe" and p.papel != "combatente" for p in pjs):
        achados.append(Achado(
            severidade="info", categoria="Papéis", titulo="Pouca energia amaldiçoada no grupo",
            detalhe="Só combatentes no grupo: a energia é gasta em habilidades de combate, "
                    "sobra pouco para feitiços de área, controle ou cura.",
            regra="Especialista em Técnica ganha 6 PE por nível; Controlador e Suporte, 5; "
                  "Lutador e Especialista em Combate, 4; Restringido não tem PE.",
            sugestao="Um Especialista em Técnica traz dano e efeitos com a técnica.",
        ))  # fmt: skip

    # Testes de resistência
    for r in ("vontade", "astucia", "fortitude", "reflexos"):
        info = ex["resistencias"][r]
        treinados = [p.nome for p in pjs if r in p.treinado_em]
        media = mean(p.resistencias[r] for p in pjs)
        if not treinados:
            pior = min(pjs, key=lambda p: p.resistencias[r])
            achados.append(Achado(
                severidade="alerta" if r == "vontade" else "atencao", categoria="Resistências",
                titulo=f"Ninguém treinado em {info['nome']} (média {media:+.1f})",
                detalhe=f"{info['nome']} protege contra {info['contra']}. "
                        f"Mais vulnerável: {pior.nome} ({pior.resistencias[r]:+d}).",
                regra=f"Teste de {info['nome']} = d20 + mod. de {info['atributo'].upper()} + "
                      "metade do nível + bônus de treinamento (se treinado).",
                sugestao="As especializações de técnica treinam Astúcia ou Vontade; as de "
                         "combate, Fortitude ou Reflexos. No nível 9 todos ganham um segundo.",
            ))  # fmt: skip
    alma = min(pjs, key=lambda p: p.resistencias["integridade"])
    achados.append(Achado(
        severidade="info", categoria="Resistências", titulo="Integridade da alma",
        detalhe="Nenhuma especialização treina Integridade. Menor valor no grupo: "
                f"{alma.nome} ({alma.resistencias['integridade']:+d}).",
        regra="Integridade = d20 + mod. de CON + metade do nível; resiste a efeitos raros que "
              "atacam a alma. A Integridade da Alma máxima é igual aos PV máximos.",
    ))  # fmt: skip

    # Alcance
    if not any(p.distancia for p in pjs):
        achados.append(Achado(
            severidade="atencao", categoria="Alcance",
            titulo="Ninguém treinado em armas à distância",
            detalhe="Contra uma maldição que voa ou fica fora de alcance, o grupo depende só de "
                    "feitiços com alcance.",
            regra="Sem treinamento na arma, o ataque não soma o bônus de treinamento.",
            sugestao="Especialista em Combate, Especialista em Técnica e Controlador treinam "
                     "armas à distância.",
        ))  # fmt: skip

    # Fragilidade
    if len(pjs) > 1:
        fragil = min(pjs, key=lambda p: (p.pv, p.defesa))
        media_pv = mean(p.pv for p in pjs)
        if fragil.pv < 0.7 * media_pv:
            achados.append(Achado(
                severidade="atencao", categoria="Papéis", titulo=f"{fragil.nome} é o alvo fácil",
                detalhe=f"{fragil.pv} PV e Defesa {fragil.defesa}, contra {media_pv:.0f} PV de "
                        "média no grupo.",
                regra="Defesa = 10 + mod. de DES + metade do nível; PV vêm da especialização "
                      "+ CON a cada nível.",
                sugestao="Posicione atrás da linha de frente ou aumente CON nos próximos pontos "
                         "de atributo.",
            ))  # fmt: skip

    # Origens raras repetidas
    raras = Counter(p.origem for p in pjs if ex["origens"].get(p.origem, {}).get("rara"))
    for origem, n in raras.items():
        if n > 1:
            achados.append(Achado(
                severidade="info", categoria="Origens",
                titulo=f"{n} personagens com a origem rara {ex['origens'][origem]['nome']}",
                detalhe="O livro sugere evitar várias origens raras iguais no mesmo grupo, "
                        "por coerência com o mundo de jogo.",
                regra="Derivado, Restringido, Feto Amaldiçoado Híbrido e Corpo Amaldiçoado "
                      "Mutante são origens raras.",
                sugestao="Não é regra: combine com o mestre se faz sentido na campanha.",
            ))  # fmt: skip
    return ordenar(achados)
