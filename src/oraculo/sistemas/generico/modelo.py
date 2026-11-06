"""Especificação de um sistema de RPG lida de um livro ("SistemaLido").

É o contrato entre o leitor com LLM e o motor genérico: o LLM preenche, o pydantic valida e
`normalizar` conserta o que dá (ids, nomes de atributos nas fórmulas) e descarta o que não dá,
registrando cada descarte em `avisos`. Nada aqui é específico de um dado: serve para d20,
2d8, d100 (Call of Cthulhu), paradas de d10 (Vampiro) etc.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from oraculo.sistemas.generico.formulas import (
    ErroFormula,
    avaliar,
    nomes_desconhecidos,
    normalizar_id,
    zerar_nomes,
)

TipoDerivado = Literal["vida", "defesa", "recurso", "iniciativa", "movimento", "outro"]
TipoResolucao = Literal["soma_contra_alvo", "rolar_abaixo", "parada_de_sucessos", "outro"]
MetodoGeracao = Literal["rolagem", "pontos", "valores_fixos", "outro"]


def _texto(v: object) -> str:
    return "" if v is None else str(v).strip()


def _opcao(v: object, opcoes: tuple[str, ...], padrao: str) -> str:
    """Valor fora da lista (o LLM às vezes inventa um rótulo) vira o padrão, sem erro."""
    texto = _texto(v).lower()
    return texto if texto in opcoes else padrao


def _inteiro_ou_nada(v: object) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(round(float(str(v).replace(",", "."))))
    except ValueError:
        return None


class _Base(BaseModel):
    model_config = {"extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _sem_nulos(cls, dados: object) -> object:
        """O LLM manda null em campos que ele não achou: vale o padrão do campo."""
        if isinstance(dados, dict):
            return {k: v for k, v in dados.items() if v is not None}
        return dados


class Atributo(_Base):
    id: str = ""
    nome: str
    sigla: str = ""
    descricao: str = ""
    minimo: int | None = None
    maximo: int | None = None
    rolagem: str | None = None  # quando cada atributo tem a própria rolagem (ex.: TAM 2d6+6)

    @field_validator("nome", "sigla", "descricao", mode="before")
    @classmethod
    def _str(cls, v: object) -> str:
        return _texto(v)

    @field_validator("minimo", "maximo", mode="before")
    @classmethod
    def _int(cls, v: object) -> int | None:
        return _inteiro_ou_nada(v)


class RegraGeracao(_Base):
    """Como gerar um conjunto de atributos: rolagem, pontos ou valores fixos."""

    metodo: MetodoGeracao = "outro"
    rolagem: str | None = None  # rolagem única do conjunto (ex.: "4d6kh3")
    pontos: int | None = None
    valor_inicial: int | None = None
    valores_fixos: list[int] = Field(default_factory=list)
    explicacao: str = ""

    @field_validator("metodo", mode="before")
    @classmethod
    def _metodo(cls, v: object) -> str:
        return _opcao(v, ("rolagem", "pontos", "valores_fixos", "outro"), "outro")

    @field_validator("pontos", "valor_inicial", mode="before")
    @classmethod
    def _int(cls, v: object) -> int | None:
        return _inteiro_ou_nada(v)

    @field_validator("valores_fixos", mode="before")
    @classmethod
    def _lista_int(cls, v: object) -> list[int]:
        if not isinstance(v, list):
            return []
        return [x for x in (_inteiro_ou_nada(i) for i in v) if x is not None]


class GrupoGeracao(RegraGeracao):
    """Conjunto separado de atributos com a própria regra (ex.: 2 pontos para os sociais)."""

    nome: str = ""
    atributos: list[str] = Field(default_factory=list)


class GeracaoAtributos(RegraGeracao):
    """Regra geral + grupos com regra própria. Atributos fora dos grupos usam a regra geral."""

    grupos: list[GrupoGeracao] = Field(default_factory=list)


class Derivado(_Base):
    id: str = ""
    nome: str
    formula: str = ""
    tipo: TipoDerivado = "outro"
    explicacao: str = ""

    @field_validator("tipo", mode="before")
    @classmethod
    def _tipo(cls, v: object) -> str:
        return _opcao(v, ("vida", "defesa", "recurso", "iniciativa", "movimento", "outro"), "outro")

    @field_validator("formula", mode="before")
    @classmethod
    def _formula(cls, v: object) -> str:
        return _texto(v)


class Pericia(_Base):
    nome: str
    atributo: str | None = None
    descricao: str = ""


class Arquetipo(_Base):
    nome: str
    descricao: str = ""
    papel: str = ""  # combate, suporte, social, investigação... (palavras do próprio livro)
    atributos_chave: list[str] = Field(default_factory=list)
    pericias: list[str] = Field(default_factory=list)
    equipamento: list[str] = Field(default_factory=list)
    habilidades: list[str] = Field(default_factory=list)
    dano_tipico: str | None = None  # dano médio de um ataque típico (ex.: "1d8+2")
    # Fórmulas próprias do arquétipo para valores derivados (ex.: PV por classe no D&D).
    formulas: dict[str, str] = Field(default_factory=dict)

    @field_validator("formulas", mode="before")
    @classmethod
    def _formulas(cls, v: object) -> dict:
        if not isinstance(v, dict):
            return {}
        return {str(k): str(f).strip() for k, f in v.items() if f not in (None, "")}


class Ataque(_Base):
    nome: str
    dano: str | None = None
    descricao: str = ""


class Criatura(_Base):
    nome: str
    descricao: str = ""
    ameaca: str = ""  # nível, ND, categoria... como o livro escreve
    atributos: dict[str, int] = Field(default_factory=dict)
    vida: int | None = None
    defesa: int | None = None
    ataques: list[Ataque] = Field(default_factory=list)

    @field_validator("vida", "defesa", "pagina", mode="before")
    @classmethod
    def _int(cls, v: object) -> int | None:
        return _inteiro_ou_nada(v)

    habilidades: list[str] = Field(default_factory=list)
    pagina: int | None = None

    @field_validator("atributos", mode="before")
    @classmethod
    def _so_inteiros(cls, v: object) -> dict:
        if not isinstance(v, dict):
            return {}
        saida = {}
        for k, x in v.items():
            try:
                saida[str(k)] = int(float(str(x).split("/")[0]))
            except ValueError:
                continue
        return saida


class Mecanica(_Base):
    dado_base: str = ""
    tipo: TipoResolucao = "outro"
    resolucao: str = ""
    criticos: str = ""
    chance_acerto_estimada: float = 0.6
    dano_basico: str = ""  # dano de um ataque básico pela regra do livro (fórmula)
    dano_explicacao: str = ""
    # Quanto o dano de um acerto médio vale em relação ao dano base (graus de sucesso,
    # sucessos extras...). 1 quando o livro não multiplica o dano.
    multiplicador_dano_medio: float = 1.0

    @field_validator("multiplicador_dano_medio", mode="before")
    @classmethod
    def _multiplicador(cls, v: object) -> float:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return 1.0
        return min(10.0, max(0.1, x))

    @field_validator("dano_basico", mode="before")
    @classmethod
    def _dano(cls, v: object) -> str:
        return _texto(v)

    @field_validator("tipo", mode="before")
    @classmethod
    def _tipo(cls, v: object) -> str:
        opcoes = ("soma_contra_alvo", "rolar_abaixo", "parada_de_sucessos", "outro")
        return _opcao(v, opcoes, "outro")

    @field_validator("chance_acerto_estimada", mode="before")
    @classmethod
    def _chance(cls, v: object) -> float:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return 0.6
        if x > 1:  # veio em porcentagem
            x /= 100
        return min(0.95, max(0.05, x))


class Niveis(_Base):
    usa_niveis: bool = False
    nivel_inicial: int = 1
    nivel_maximo: int | None = None
    nome: str = "nível"
    variavel: str = ""  # como as fórmulas do livro chamam o nível (ex.: "nc" no Naruto SnS)

    @field_validator("nivel_inicial", mode="before")
    @classmethod
    def _inicial(cls, v: object) -> int:
        return max(1, _inteiro_ou_nada(v) or 1)

    @field_validator("nivel_maximo", mode="before")
    @classmethod
    def _maximo(cls, v: object) -> int | None:
        return _inteiro_ou_nada(v)


class SistemaLido(_Base):
    nome: str
    autores: str = ""
    genero: str = ""
    ambientacao: str = ""
    resumo: str = ""
    mecanica: Mecanica = Field(default_factory=Mecanica)
    niveis: Niveis = Field(default_factory=Niveis)
    atributos: list[Atributo] = Field(default_factory=list)
    geracao: GeracaoAtributos = Field(default_factory=GeracaoAtributos)
    derivados: list[Derivado] = Field(default_factory=list)
    pericias: list[Pericia] = Field(default_factory=list)
    arquetipos: list[Arquetipo] = Field(default_factory=list)
    nome_arquetipo: str = "arquétipo"  # classe, clã, profissão, clã vampírico...
    criaturas: list[Criatura] = Field(default_factory=list)
    regras_encontro: str = ""
    # Modificador de atributo, com "valor" (ex.: piso((valor-10)/2) nos sistemas d20).
    modificador: str = ""
    paginas_fonte: dict[str, list[int]] = Field(default_factory=dict)
    avisos: list[str] = Field(default_factory=list)

    # -------------------------------------------------------------- consultas
    def atributo(self, ref: str | None) -> Atributo | None:
        """Acha um atributo pelo id, sigla ou nome (sem diferenciar acento/caixa)."""
        if not ref:
            return None
        chave = normalizar_id(ref)
        for a in self.atributos:
            if chave in (a.id, normalizar_id(a.sigla), normalizar_id(a.nome)):
                return a
        return None

    def arquetipo(self, nome: str | None) -> Arquetipo | None:
        if not nome:
            return None
        chave = normalizar_id(nome)
        return next((a for a in self.arquetipos if normalizar_id(a.nome) == chave), None)

    def modificador_de(self, valor: float) -> float | None:
        if not self.modificador:
            return None
        try:
            return avaliar(self.modificador, {"valor": valor})
        except ErroFormula:
            return None

    def variaveis(self, valores: dict[str, float], nivel: int = 1) -> dict[str, float]:
        """Nomes que as fórmulas podem usar: id, sigla e nome de cada atributo (e o modificador
        como mod_<atributo>, <atributo>_mod ou modificador_de_<atributo>) e o nível."""
        v: dict[str, float] = {"nivel": nivel, "level": nivel, "nv": nivel}
        if self.niveis.variavel:
            v[normalizar_id(self.niveis.variavel)] = nivel
        for a in self.atributos:
            if a.id not in valores:
                continue
            mod = self.modificador_de(valores[a.id])
            for nome in {normalizar_id(x) for x in (a.id, a.sigla, a.nome) if x}:
                v[nome] = valores[a.id]
                if mod is not None:
                    for alias in (
                        f"mod_{nome}",
                        f"{nome}_mod",
                        f"modificador_de_{nome}",
                        f"modificador_{nome}",
                        f"mod{nome}",
                    ):
                        v[alias] = mod
        return v

    def formula_de(self, d: Derivado, arquetipo: Arquetipo | None = None) -> str:
        """A fórmula do arquétipo para o derivado, se houver; senão a geral."""
        if arquetipo:
            for chave, f in arquetipo.formulas.items():
                if normalizar_id(chave) in (d.id, normalizar_id(d.nome)):
                    return f
        return d.formula

    def calcular(
        self, valores: dict[str, float], nivel: int = 1, arquetipo: Arquetipo | None = None
    ) -> dict[str, float | None]:
        """Todos os derivados. Um derivado pode usar outros (Esquiva → Reação de Esquiva), em
        qualquer ordem: repete até nada mais mudar."""
        variaveis = self.variaveis(valores, nivel)
        saida: dict[str, float | None] = {d.id: None for d in self.derivados}
        pendentes = [d for d in self.derivados if self.formula_de(d, arquetipo)]
        while pendentes:
            feitos = []
            for d in pendentes:
                try:
                    valor = avaliar(self.formula_de(d, arquetipo), variaveis)
                except ErroFormula:
                    continue
                saida[d.id] = valor
                variaveis[normalizar_id(d.id)] = valor
                variaveis[normalizar_id(d.nome)] = valor
                feitos.append(d)
            if not feitos:
                break
            pendentes = [d for d in pendentes if d not in feitos]
        return saida

    def derivado_do_tipo(self, tipo: str) -> Derivado | None:
        return next((d for d in self.derivados if d.tipo == tipo), None)


# --------------------------------------------------------------------------- normalização
# O LLM às vezes erra o tipo de um valor derivado (Vitalidade como "recurso"). O nome decide
# quando ele é inequívoco; isso deixa as análises estáveis entre uma leitura e outra.
NOMES_POR_TIPO = {
    "vida": ("vida", "vitalidade", "pontos de vida", "pv", "hp", "hit points", "saude",
             "health", "ferimentos", "resistencia fisica", "pontos de vigor"),
    "defesa": ("defesa", "defense", "ca", "classe de armadura", "armor class", "esquiva",
               "reacao de esquiva", "aparar", "guarda"),
    "iniciativa": ("iniciativa", "initiative"),
    "movimento": ("deslocamento", "movimento", "movement", "speed", "velocidade"),
    "recurso": ("chakra", "mana", "energia", "pe", "pontos de energia", "sanidade", "sanity",
                "magia", "pontos de magia", "pm", "ki", "estamina", "stamina", "forca de vontade",
                "pontos de sorte", "sorte", "luck", "humanidade", "fome"),
}  # fmt: skip


def _tipo_pelo_nome(nome: str) -> str | None:
    chave = normalizar_id(nome).replace("_", " ")
    for tipo, nomes in NOMES_POR_TIPO.items():
        if chave in nomes or any(chave.startswith(n + " ") for n in nomes if len(n) > 3):
            return tipo
    return None


# Marcadores que o LLM às vezes escreve nas fórmulas ("10 + mod_des + outros"): valem 0.
MARCADORES = {
    "outros", "outros_bonus", "bonus", "bonus_diversos", "outros_modificadores", "misc",
    "diversos", "outros_valores", "modificadores", "outros_bonus_aplicaveis", "etc",
}  # fmt: skip


def normalizar(s: SistemaLido) -> SistemaLido:
    """Conserta ids e referências e descarta o que não for utilizável, com aviso."""
    avisos = list(s.avisos)
    if s.modificador:
        try:
            avaliar(s.modificador, {"valor": 10})
        except ErroFormula:
            avisos.append(f"Fórmula do modificador não entendida ({s.modificador}); ignorada.")
            s.modificador = ""

    # Atributos: ids únicos e faixas coerentes
    vistos: set[str] = set()
    atributos = []
    for a in s.atributos:
        a.id = normalizar_id(a.id or a.sigla or a.nome)
        if a.id in vistos:
            avisos.append(f"Atributo repetido ignorado: {a.nome}.")
            continue
        if a.minimo is not None and a.maximo is not None and a.minimo > a.maximo:
            a.minimo, a.maximo = a.maximo, a.minimo
        vistos.add(a.id)
        atributos.append(a)
    s.atributos = atributos
    teste = s.variaveis({a.id: 10 for a in s.atributos})

    formulas = [d.formula for d in s.derivados] + [s.mecanica.dano_basico]
    formulas += [f for arq in s.arquetipos for f in arq.formulas.values()]
    usa_mod = any(
        n.lower().startswith(("mod_", "modificador")) or n.lower().endswith("_mod")
        for f in formulas
        if f
        for n in nomes_desconhecidos(f, teste)
    )
    escala_d20 = "20" in s.mecanica.dado_base or any((a.maximo or 0) >= 18 for a in s.atributos)
    if usa_mod and not s.modificador and escala_d20:
        s.modificador = "piso((valor-10)/2)"
        avisos.append(
            "As fórmulas do livro usam modificador de atributo, mas a leitura não trouxe a "
            "regra: usei o padrão d20, piso((valor−10)/2). Confira no resumo."
        )
        teste = s.variaveis({a.id: 10 for a in s.atributos})

    def calculavel(formula: str | None) -> str | None:
        if not formula:
            return "sem fórmula"
        try:
            avaliar(formula, teste)
        except ErroFormula as e:
            return str(e)
        return None

    def sem_marcadores(formula: str, rotulo: str) -> str:
        """Zera marcadores como 'outros' (com aviso) se forem o único problema da fórmula."""
        if not formula or calculavel(formula) is None:
            return formula
        faltam = nomes_desconhecidos(formula, teste)
        if faltam and {normalizar_id(n) for n in faltam} <= MARCADORES:
            avisos.append(f"Em {rotulo}, {', '.join(faltam)} contou como 0.")
            return zerar_nomes(formula, faltam)
        return formula

    for d in s.derivados:
        d.formula = sem_marcadores(d.formula, d.nome)
    for arq in s.arquetipos:
        arq.formulas = {k: sem_marcadores(f, f"{k} ({arq.nome})") for k, f in arq.formulas.items()}

    for a in s.atributos:
        if a.rolagem and calculavel(a.rolagem):
            avisos.append(f"Rolagem de {a.nome} não entendida ({a.rolagem}); ignorada.")
            a.rolagem = None
    if s.geracao.rolagem and calculavel(s.geracao.rolagem):
        avisos.append(f"Rolagem de atributos não entendida ({s.geracao.rolagem}); ignorada.")
        s.geracao.rolagem = None
    grupos = []
    for g in s.geracao.grupos:
        ids_grupo = list(dict.fromkeys(a.id for a in map(s.atributo, g.atributos) if a))
        if not ids_grupo:
            avisos.append(f"Grupo de atributos {g.nome or '(sem nome)'} sem atributos válidos.")
            continue
        g.atributos = ids_grupo
        if g.rolagem and calculavel(g.rolagem):
            avisos.append(f"Rolagem do grupo {g.nome} não entendida ({g.rolagem}); ignorada.")
            g.rolagem = None
        grupos.append(g)
    s.geracao.grupos = grupos
    if s.mecanica.dano_basico and calculavel(s.mecanica.dano_basico):
        faltam = nomes_desconhecidos(s.mecanica.dano_basico, teste)
        sem_eles = zerar_nomes(s.mecanica.dano_basico, faltam) if faltam else ""
        if sem_eles and calculavel(sem_eles) is None:
            avisos.append(
                f"No dano básico ({s.mecanica.dano_basico}), {', '.join(faltam)} contou como 0 "
                "(ataque sem arma); ajuste no resumo se quiser outro valor."
            )
            s.mecanica.dano_basico = sem_eles
    if s.mecanica.dano_basico and calculavel(s.mecanica.dano_basico):
        avisos.append(f"Dano básico não calculável ({s.mecanica.dano_basico}); fica só como texto.")
        s.mecanica.dano_explicacao = (
            s.mecanica.dano_explicacao or f"Regra do livro: {s.mecanica.dano_basico}"
        )
        s.mecanica.dano_basico = ""

    for d in s.derivados:
        tipo = _tipo_pelo_nome(d.nome)
        if tipo:
            d.tipo = tipo
    # Derivados: ordenados para que cada um só use atributos e derivados anteriores. Os que
    # não fecham ficam como texto no resumo (fórmula vazia), com aviso.
    unicos, ids = [], set()
    for d in s.derivados:
        d.id = normalizar_id(d.id or d.nome)
        if d.id not in ids:
            ids.add(d.id)
            unicos.append(d)
    prontos, pendentes = [], list(unicos)
    while True:
        avancou = False
        for d in list(pendentes):
            if not d.formula:
                continue
            if calculavel(d.formula) is None:
                prontos.append(d)
                pendentes.remove(d)
                teste[normalizar_id(d.id)] = 10
                teste[normalizar_id(d.nome)] = 10
                avancou = True
        if not avancou:
            break
    for d in pendentes:
        if d.formula:
            avisos.append(
                f"Fórmula de {d.nome} não calculável ({d.formula}): {calculavel(d.formula)}."
            )
            d.formula = ""
    s.derivados = prontos + pendentes
    for d in s.derivados:
        teste[normalizar_id(d.id)] = 10
        teste[normalizar_id(d.nome)] = 10
    for arq in s.arquetipos:
        validas = {}
        for chave, f in arq.formulas.items():
            alvo = next(
                (d for d in s.derivados if normalizar_id(chave) in (d.id, normalizar_id(d.nome))),
                None,
            )
            if alvo is None:
                avisos.append(f"{arq.nome}: fórmula para {chave}, que não está nos derivados.")
            elif calculavel(f):
                avisos.append(f"{arq.nome}: fórmula de {alvo.nome} não calculável ({f}).")
            else:
                validas[alvo.id] = f
        arq.formulas = validas

    # Referências de arquétipos e perícias aos atributos
    for arq in s.arquetipos:
        chaves = []
        for ref in arq.atributos_chave:
            a = s.atributo(ref)
            if a and a.id not in chaves:
                chaves.append(a.id)
        arq.atributos_chave = chaves
        if arq.dano_tipico and calculavel(arq.dano_tipico):
            avisos.append(f"Dano típico de {arq.nome} não entendido ({arq.dano_tipico}).")
            arq.dano_tipico = None
    for p in s.pericias:
        a = s.atributo(p.atributo)
        p.atributo = a.id if a else None
    for c in s.criaturas:
        mapeados = {}
        for k, v in c.atributos.items():
            a = s.atributo(k)
            mapeados[a.id if a else normalizar_id(k)] = v
        c.atributos = mapeados
        for at in c.ataques:
            if at.dano and calculavel(at.dano):
                at.dano = None
    if not s.atributos:
        avisos.append("O livro não deixou claro quais são os atributos; a ficha fica limitada.")
    s.avisos = list(dict.fromkeys(avisos))
    return s
