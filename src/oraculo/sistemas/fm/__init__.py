"""Regras de Feiticeiros & Maldições (v2.5): valores derivados e validação de fichas.

Só as mecânicas, resumidas a partir do livro de regras (ver `sistema.yaml` para crédito e
licença). Convenções da ficha genérica neste sistema:

* `classe` é a especialização; `origem` é a origem (inato, herdado...);
* `pericias` lista as perícias treinadas e, opcionalmente, os testes de resistência escolhidos
  (ex.: "fortitude"); sem escolha, vale o teste com o melhor atributo.
"""

from __future__ import annotations

from oraculo.nucleo.ficha import Ficha, Problema
from oraculo.nucleo.sistema import Classe, RegrasSistema, carregar_definicao

ATRIBUTOS = ("for", "des", "con", "int", "sab", "pre")
RESISTENCIAS = ("astucia", "fortitude", "integridade", "reflexos", "vontade")
ATRIBUTOS_TECNICA = ("int", "sab", "pre")  # atributos mentais usados no jujutsu


def modificador(valor: int) -> int:
    return (valor - 10) // 2


def bonus_treinamento(nivel: int) -> int:
    """+2 no nível 1, +1 nos níveis 5, 9, 13 e 17."""
    return 2 + (nivel - 1) // 4


def melhor_atributo(atributos: dict[str, int], opcoes: list[str] | tuple[str, ...]) -> str:
    """O atributo de maior valor entre as opções (empate: o primeiro da lista)."""
    return max(opcoes, key=lambda a: (atributos.get(a, 10), -list(opcoes).index(a)))


def resistencias_treinadas(
    ficha: Ficha, classe: Classe, defn_res: dict
) -> tuple[set[str], set[str]]:
    """(treinadas, mestre) nos testes de resistência, contando o nível 9."""
    opcoes = classe.resistencias
    if classe.resistencias_escolha is None:
        treinadas = list(opcoes)
    else:
        escolhidas = [r for r in opcoes if r in ficha.pericias]
        if not escolhidas:
            escolhidas = [
                melhor_atributo(
                    {r: ficha.atributos.get(defn_res[r]["atributo"], 10) for r in opcoes}, opcoes
                )
            ]
        treinadas = escolhidas[: classe.resistencias_escolha]
    mestre: set[str] = set()
    if ficha.nivel >= 9:  # Teste de Resistência Mestre
        if classe.resistencias_escolha is None:
            mestre = set(treinadas)
        else:
            mestre = {treinadas[0]}
            treinadas += [r for r in opcoes if r not in treinadas][:1]
    return set(treinadas), mestre


class Regras(RegrasSistema):
    def __init__(self) -> None:
        self.definicao = carregar_definicao(__name__)

    @property
    def extras(self) -> dict:
        return self.definicao.extras

    def atributo_chave(self, ficha: Ficha) -> str | None:
        classe = self.definicao.classe(ficha.classe)
        if classe is None:
            return None
        return melhor_atributo(ficha.atributos, classe.atributos_principais)

    def atributo_tecnica(self, ficha: Ficha) -> str | None:
        """Atributo do jujutsu: o atributo-chave para quem usa técnica, senão o melhor mental."""
        classe = self.definicao.classe(ficha.classe)
        if classe is None or classe.id == "restringido":
            return None
        if classe.energia_soma_atributo:
            return self.atributo_chave(ficha)
        return melhor_atributo(ficha.atributos, ATRIBUTOS_TECNICA)

    # ------------------------------------------------------------------ derivados

    def derivados(self, ficha: Ficha) -> dict[str, int]:
        attrs = {a: ficha.atributos.get(a, 10) for a in ATRIBUTOS}
        mods = {a: modificador(v) for a, v in attrs.items()}
        treino = bonus_treinamento(ficha.nivel)
        meio = ficha.nivel // 2
        classe = self.definicao.classe(ficha.classe)
        origem = self.extras["origens"].get(ficha.origem or "", {})

        d: dict[str, int] = {f"mod_{a}": m for a, m in mods.items()}
        d["treinamento"] = treino
        d["defesa"] = 10 + mods["des"] + meio
        d["iniciativa"] = mods["des"]
        d["deslocamento"] = self.extras["deslocamento_base"] + origem.get("deslocamento_extra", 0)
        for pid, p in self.extras["pericias"].items():
            d[f"pericia_{pid}"] = (
                mods[p["atributo"]] + meio + (treino if pid in ficha.pericias else 0)
            )
        d["atencao"] = 10 + d["pericia_percepcao"]
        d["ataque_corpo_a_corpo"] = mods["for"] + meio + treino
        d["ataque_distancia"] = mods["des"] + meio + treino

        if classe is None:
            for r in RESISTENCIAS:
                d[f"resistencia_{r}"] = mods[self.extras["resistencias"][r]["atributo"]] + meio
            return d

        dv = classe.dado_vida or 8
        por_nivel = dv // 2 + 1  # valor fixo do livro (ex.: d10 → 6)
        d["pv_maximo"] = (
            (classe.pv_primeiro_nivel or dv)
            + mods["con"]
            + (ficha.nivel - 1) * (por_nivel + mods["con"])
        )
        d["integridade_alma"] = d["pv_maximo"]
        d["dado_vida"] = dv

        chave = self.atributo_chave(ficha)
        d["cd_especializacao"] = 10 + meio + mods[chave] + treino
        tecnica = self.atributo_tecnica(ficha)
        energia = (classe.energia_por_nivel or 0) * ficha.nivel
        if tecnica:
            if classe.energia_soma_atributo:
                energia += mods[tecnica]
            d["pe"] = energia
            d["ataque_amaldicoado"] = mods[tecnica] + meio + treino
            d["cd_tecnica"] = 10 + meio + mods[tecnica] + treino
        else:
            d["estamina"] = energia

        treinadas, mestre = resistencias_treinadas(ficha, classe, self.extras["resistencias"])
        for r in RESISTENCIAS:
            bonus = treino if r in treinadas else 0
            if r in mestre:
                bonus += treino // 2
            d[f"resistencia_{r}"] = mods[self.extras["resistencias"][r]["atributo"]] + meio + bonus
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
        limite = self.extras["limite_atributo_comum"]
        for a in defn.atributos:
            v = ficha.atributos.get(a.id)
            if v is None:
                continue
            if not a.minimo <= v <= a.maximo:
                erro(f"atributos.{a.id}", f"{a.abrev} deve ficar entre {a.minimo} e {a.maximo}")
            elif v > limite:
                aviso(
                    f"atributos.{a.id}",
                    f"{a.abrev} {v} passa do limite comum ({limite}); só vale com uma habilidade, "
                    "talento ou característica que permita.",
                )

        if ficha.tipo != "pj":
            return problemas

        classe = defn.classe(ficha.classe)
        if classe is None:
            erro("classe", "especialização inválida ou não informada")
        origens = self.extras["origens"]
        if ficha.origem is not None and ficha.origem not in origens:
            erro("origem", f"origem desconhecida: {ficha.origem!r}")
        restrita = origens.get("restringido", {}).get("exige_especializacao")
        if classe and restrita:
            if (ficha.origem == "restringido") != (classe.id == restrita):
                erro(
                    "classe",
                    "a especialização Restringido exige a origem Restringido, e vice-versa "
                    "(restringidos também não fazem multiclasse).",
                )
        if ficha.origem == "sem_tecnica" and classe and classe.id == "especialista_tecnica":
            aviso(
                "origem",
                "Sem Técnica não tem técnica inata: um Especialista em Técnica perde boa parte "
                "das habilidades até obter uma técnica de outra forma.",
            )

        self._validar_metodo(ficha, erro)
        if classe and not faltando:
            chave = self.atributo_chave(ficha)
            if ficha.atributos[chave] < 13:
                nomes = "/".join(a.upper() for a in classe.atributos_principais)
                aviso(
                    "atributos",
                    f"{classe.nome} usa {nomes} na CD de especialização, mas o melhor deles está "
                    f"baixo ({ficha.atributos[chave]}). As habilidades vão falhar com frequência.",
                )
            if ficha.atributos["con"] < 10:
                aviso("atributos.con", "CON abaixo de 10 reduz os PV a cada nível.")
        return problemas

    def _validar_metodo(self, ficha: Ficha, erro) -> None:
        valores = [ficha.atributos.get(a) for a in ATRIBUTOS]
        if None in valores:
            return
        if ficha.metodo_atributos == "compra_pontos":
            custo = custo_compra_pontos(ficha.atributos)
            orcamento = self.extras["compra_pontos"]["orcamento"]
            if custo is None:
                erro("atributos", "na compra de pontos os valores iniciais vão de 8 a 15")
            elif custo > orcamento:
                erro("atributos", f"gastou {custo} pontos; o limite é {orcamento}")
        elif ficha.metodo_atributos == "padrao":
            if sorted(valores) != sorted(self.extras["conjunto_padrao"]):
                erro("atributos", "o conjunto de valores fixos é 15, 14, 13, 12, 10, 8")


def custo_compra_pontos(atributos: dict[str, int]) -> int | None:
    """Custo na compra de pontos (todos começam em 10; 8 e 9 devolvem pontos)."""
    tabela = {int(k): v for k, v in Regras().extras["compra_pontos"]["custo"].items()}
    if any(v not in tabela for v in atributos.values()):
        return None
    return sum(tabela[v] for v in atributos.values())
