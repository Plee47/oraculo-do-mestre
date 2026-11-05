"""Regras de D&D 5e (SRD 5.1): atributos, valores derivados e validação de fichas."""

from __future__ import annotations

from oraculo.nucleo.ficha import Ficha, Problema
from oraculo.nucleo.sistema import RegrasSistema, carregar_definicao

ATRIBUTOS = ("for", "des", "con", "int", "sab", "car")


def modificador(valor: int) -> int:
    return (valor - 10) // 2


def bonus_proficiencia(nivel: int) -> int:
    return 2 + (nivel - 1) // 4


class Regras(RegrasSistema):
    def __init__(self) -> None:
        self.definicao = carregar_definicao(__name__)

    # ------------------------------------------------------------------ derivados

    def derivados(self, ficha: Ficha) -> dict[str, int]:
        attrs = {a: ficha.atributos.get(a, 10) for a in ATRIBUTOS}
        mods = {a: modificador(v) for a, v in attrs.items()}
        prof = bonus_proficiencia(ficha.nivel)
        classe = self.definicao.classe(ficha.classe)

        d: dict[str, int] = {f"mod_{a}": m for a, m in mods.items()}
        d["proficiencia"] = prof
        d["iniciativa"] = mods["des"]
        d["percepcao_passiva"] = 10 + mods["sab"]
        d["ca_sem_armadura"] = 10 + mods["des"]

        if classe:
            if classe.id == "barbaro":  # Defesa sem Armadura
                d["ca_sem_armadura"] += mods["con"]
            elif classe.id == "monge":
                d["ca_sem_armadura"] += mods["sab"]

            if classe.dado_vida:
                dv = classe.dado_vida
                por_nivel = dv // 2 + 1  # média fixa do SRD
                d["pv_maximo"] = max(1, dv + mods["con"]) + sum(
                    max(1, por_nivel + mods["con"]) for _ in range(ficha.nivel - 1)
                )
            for a in ATRIBUTOS:
                d[f"resistencia_{a}"] = mods[a] + (prof if a in classe.resistencias else 0)
            if classe.conjuracao:
                d["cd_magia"] = 8 + prof + mods[classe.conjuracao]
                d["ataque_magico"] = prof + mods[classe.conjuracao]
        return d

    # ------------------------------------------------------------------ validação

    def validar(self, ficha: Ficha) -> list[Problema]:
        defn = self.definicao
        problemas: list[Problema] = []

        def erro(campo: str, msg: str) -> None:
            problemas.append(Problema(gravidade="erro", campo=campo, mensagem=msg))

        def aviso(campo: str, msg: str) -> None:
            problemas.append(Problema(gravidade="aviso", campo=campo, mensagem=msg))

        if ficha.sistema != defn.id:
            erro("sistema", f"ficha de outro sistema ({ficha.sistema!r})")
        if ficha.nivel > defn.nivel_maximo:
            erro("nivel", f"nível máximo é {defn.nivel_maximo}")

        faltando = [a for a in ATRIBUTOS if a not in ficha.atributos]
        if faltando:
            erro("atributos", f"faltam atributos: {', '.join(faltando).upper()}")
        desconhecidos = set(ficha.atributos) - set(ATRIBUTOS)
        if desconhecidos:
            erro("atributos", f"atributos desconhecidos: {', '.join(sorted(desconhecidos))}")
        for a in defn.atributos:
            v = ficha.atributos.get(a.id)
            if v is not None and not a.minimo <= v <= a.maximo:
                erro(f"atributos.{a.id}", f"{a.abrev} deve ficar entre {a.minimo} e {a.maximo}")

        if ficha.tipo == "pj":
            classe = defn.classe(ficha.classe)
            if classe is None:
                erro("classe", "classe inválida ou não informada")
            self._validar_metodo(ficha, erro)
            if classe and not faltando:
                melhor = max(ficha.atributos[a] for a in classe.atributos_principais)
                if melhor < 13:
                    nomes = "/".join(a.upper() for a in classe.atributos_principais)
                    aviso(
                        "atributos",
                        f"{classe.nome} depende de {nomes}, mas o valor está baixo ({melhor}). "
                        "Os ataques ou magias principais vão falhar com frequência.",
                    )
                if ficha.atributos["con"] < 10:
                    aviso("atributos.con", "CON abaixo de 10 reduz os PV a cada nível.")
        return problemas

    def _validar_metodo(self, ficha: Ficha, erro) -> None:
        extras = self.definicao.extras
        valores = [ficha.atributos.get(a) for a in ATRIBUTOS]
        if None in valores:
            return
        if ficha.metodo_atributos == "compra_pontos":
            tabela = {int(k): v for k, v in extras["compra_pontos"]["custo"].items()}
            fora = [v for v in valores if v not in tabela]
            if fora:
                erro("atributos", "na compra de pontos os valores iniciais vão de 8 a 15")
                return
            gasto = sum(tabela[v] for v in valores)
            if gasto > extras["compra_pontos"]["orcamento"]:
                erro(
                    "atributos",
                    f"gastou {gasto} pontos; o limite é {extras['compra_pontos']['orcamento']}",
                )
        elif ficha.metodo_atributos == "padrao":
            if sorted(valores) != sorted(extras["conjunto_padrao"]):
                erro("atributos", "o conjunto padrão é 15, 14, 13, 12, 10, 8")


def custo_compra_pontos(atributos: dict[str, int]) -> int | None:
    """Custo total na compra de pontos (None se algum valor estiver fora de 8–15)."""
    tabela = Regras().definicao.extras["compra_pontos"]["custo"]
    tabela = {int(k): v for k, v in tabela.items()}
    if any(v not in tabela for v in atributos.values()):
        return None
    return sum(tabela[v] for v in atributos.values())
