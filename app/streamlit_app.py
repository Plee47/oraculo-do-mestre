"""Oráculo do Mestre — vitrine pública (Streamlit Community Cloud)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Usa sempre o código do repositório (src/), nunca um pacote `oraculo` instalado antes.
# O Streamlit Cloud reaproveita o ambiente entre deploys; sem isto, o site rodaria uma
# versão antiga do pacote depois de cada atualização.
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "app"))

import streamlit as st
from recarga import recarregar_se_mudou

# O processo do Streamlit não reinicia a cada push: se src/ ou dados/ mudaram, descarta os
# módulos antigos da memória e os caches (ver app/recarga.py).
if recarregar_se_mudou([RAIZ / "src", RAIZ / "dados"]):
    st.cache_resource.clear()
    st.cache_data.clear()

from oraculo.leitor.detector import MINIMO_CARACTERES, ModeloDetector, avaliar_documento
from oraculo.leitor.extracao import parece_ter_entradas
from oraculo.leitor.porteiro import decidir
from oraculo.nucleo import Ficha, obter_regras
from oraculo.nucleo.analise import Achado
from oraculo.sistemas.dnd5e import ATRIBUTOS, custo_compra_pontos, modificador
from oraculo.sistemas.dnd5e.analise import TIPOS_PT, analisar_encontro, analisar_grupo, perfil
from oraculo.sistemas.dnd5e.catalogo import Catalogo
from oraculo.sistemas.dnd5e.gerador import PAPEIS, calcular_ca, gerar_ficha
from oraculo.sistemas.fm import analise as fm_analise
from oraculo.sistemas.fm import custo_compra_pontos as fm_custo
from oraculo.sistemas.fm import gerador as fm_gerador

st.set_page_config(page_title="Oráculo do Mestre", page_icon="🔮", layout="wide")

CATALOGO_DND5E = Path(__file__).parents[1] / "dados" / "publicos" / "dnd5e" / "catalogo.json"
MODELO_DETECTOR = Path(__file__).parents[1] / "dados" / "publicos" / "modelos" / "detector_rpg.json"
AVALIACAO_LEITOR = (
    Path(__file__).parents[1] / "dados" / "publicos" / "avaliacoes" / "leitor_srd51.json"
)
PAGINAS = (
    "Início",
    "Gerador de fichas (D&D 5e)",
    "Análise de grupo e encontro (D&D 5e)",
    "Leitor de livros de RPG",
    "Ficha rápida (D&D 5e)",
    "Feiticeiros & Maldições",
    "Roteiro",
    "Conteúdo e licenças",
)


@st.cache_resource
def catalogo_dnd5e() -> Catalogo:
    return Catalogo.carregar(CATALOGO_DND5E)


@st.cache_resource
def modelo_detector() -> ModeloDetector:
    return ModeloDetector.carregar(MODELO_DETECTOR)


pagina = st.sidebar.radio("Navegação", PAGINAS)
st.sidebar.caption("Projeto de portfólio · Python + Databricks + GitHub")


# --------------------------------------------------------------------------- início
def pagina_inicio() -> None:
    st.title("🔮 Oráculo do Mestre")
    st.subheader("Lê livros de RPG, monta fichas e aponta o que está desequilibrado na sua mesa.")
    st.markdown(
        """
- **Leitor de livros:** reconhece se o PDF é um livro de RPG, de qual sistema, e extrai
  classes, magias e criaturas para tabelas estruturadas.
- **Gerador de fichas:** cria personagens válidos pelas regras, explicando cada escolha.
- **Análise:** encontra fraquezas do grupo e desequilíbrios nos encontros, sempre explicando
  *qual regra* gerou a dica.

Sistemas: **D&D 5ª edição** (SRD) e **Feiticeiros & Maldições** (em breve).
"""
    )
    st.info(
        "Experimente o **Gerador de fichas** e a **Análise de grupo e encontro** no menu ao lado.",
        icon="🎲",
    )


# --------------------------------------------------------------------------- gerador
def pagina_gerador() -> None:
    cat = catalogo_dnd5e()
    regras = obter_regras("dnd5e")
    defn = regras.definicao
    nomes_racas = defn.extras["racas"]
    st.title("Gerador de fichas · D&D 5e")
    st.caption(
        "Fichas válidas pelas regras do SRD 5.1, com cada escolha explicada. "
        f"Catálogo processado no Databricks: {cat.resumo()['magias']} magias, "
        f"{cat.resumo()['armas']} armas, {cat.resumo()['classes']} classes."
    )

    c1, c2, c3, c4 = st.columns(4)
    nivel = c1.slider("Nível", 1, 20, 3)
    papel = c2.selectbox("Papel no grupo", ["qualquer", *PAPEIS])
    opcoes_classe = {"Automática": None} | {
        c.nome: c.id for c in defn.classes if papel == "qualquer" or c.papel == papel
    }
    classe = opcoes_classe[c3.selectbox("Classe", list(opcoes_classe))]
    opcoes_raca = {"Automática": None} | {nomes_racas.get(r.id, r.nome): r.id for r in cat.racas}
    raca = opcoes_raca[c4.selectbox("Raça", list(opcoes_raca))]

    if "semente" not in st.session_state:
        st.session_state.semente = 1
    if st.button("🎲 Gerar outra"):
        st.session_state.semente += 1

    ficha = gerar_ficha(
        cat,
        nivel,
        classe=classe,
        papel=None if papel == "qualquer" else papel,
        raca=raca,
        seed=st.session_state.semente,
    )
    mostrar_ficha(ficha, cat)


def mostrar_ficha(ficha: Ficha, cat: Catalogo) -> None:
    regras = obter_regras("dnd5e")
    defn = regras.definicao
    classe = defn.classe(ficha.classe)
    d = regras.derivados(ficha)
    armas = {a.id: a for a in cat.armas}
    armaduras = {a.id: a for a in cat.armaduras}
    armadura = next((armaduras[i] for i in ficha.equipamento if i in armaduras
                     and armaduras[i].categoria != "escudo"), None)  # fmt: skip
    escudo = next((armaduras[i] for i in ficha.equipamento if i in armaduras
                   and armaduras[i].categoria == "escudo"), None)  # fmt: skip
    raca = defn.extras["racas"].get(ficha.origem, ficha.origem)

    st.subheader(f"{ficha.nome} · {raca} {classe.nome} de nível {ficha.nivel}")
    st.caption(f"Papel: {classe.papel} — {defn.extras['papeis'][classe.papel]}")

    m = st.columns(5)
    m[0].metric("PV máximo", d["pv_maximo"])
    m[1].metric("CA", calcular_ca(ficha.atributos, ficha.classe, armadura, escudo))
    m[2].metric("Iniciativa", f"{d['iniciativa']:+d}")
    m[3].metric("Proficiência", f"+{d['proficiencia']}")
    m[4].metric("CD de magia", d.get("cd_magia", "—"))

    cols = st.columns(6)
    for col, attr in zip(cols, defn.atributos, strict=True):
        valor = ficha.atributos[attr.id]
        col.markdown(f"**{attr.abrev}**  \n### {valor}  \n{modificador(valor):+d}")

    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Perícias**")
        st.write(", ".join(cat.pericia(p).nome for p in ficha.pericias))
        st.markdown("**Equipamento**")
        for item_id in ficha.equipamento:
            if item_id in armas:
                a = armas[item_id]
                st.write(f"⚔️ {a.nome} — {a.dano} {a.tipo_dano}")
            else:
                a = armaduras[item_id]
                st.write(f"🛡️ {a.nome} — CA {'+' if a.categoria == 'escudo' else ''}{a.ca_base}")
    with e2:
        if ficha.poderes:
            magias = {m.id: m for m in cat.magias}
            st.markdown("**Magias**")
            por_circulo: dict[int, list[str]] = {}
            for mid in ficha.poderes:
                por_circulo.setdefault(magias[mid].circulo, []).append(magias[mid].nome)
            for circulo, nomes in sorted(por_circulo.items()):
                rotulo = "Truques" if circulo == 0 else f"{circulo}º círculo"
                st.write(f"**{rotulo}:** {', '.join(nomes)}")

    with st.expander("🔮 Por que essas escolhas?", expanded=True):
        for e in ficha.explicacoes:
            st.write(f"- {e}")

    problemas = regras.validar(ficha)
    for p in problemas:
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)

    st.download_button(
        "Baixar ficha (JSON)",
        ficha.model_dump_json(indent=2),
        file_name=f"{ficha.nome.lower()}.json",
        mime="application/json",
    )


# --------------------------------------------------------------------------- análise
_ESTILO = {"alerta": st.error, "atencao": st.warning, "info": st.info, "ok": st.success}
_ICONE = {"alerta": "🔴", "atencao": "🟠", "info": "🔵", "ok": "🟢"}


def mostrar_achados(achados: list[Achado]) -> None:
    if not achados:
        st.success("Nenhum problema encontrado.", icon="🟢")
    for a in achados:
        linhas = [f"**{a.titulo}**", a.detalhe, f"*Regra:* {a.regra}"]
        if a.sugestao:
            linhas.append(f"*Sugestão:* {a.sugestao}")
        texto = "  \n".join(linhas)  # dois espaços + \n = quebra de linha no Markdown
        _ESTILO[a.severidade](texto, icon=_ICONE[a.severidade])


def _cr(cr: float) -> str:
    return {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}.get(cr, f"{cr:g}")


def pagina_analise() -> None:
    cat = catalogo_dnd5e()
    defn = obter_regras("dnd5e").definicao
    st.title("Análise de grupo e encontro · D&D 5e")
    st.caption(
        "Cada dica cita a regra que a gerou. Os números dos monstros vêm do catálogo do SRD "
        f"processado no Databricks ({len(cat.monstros)} monstros)."
    )

    st.subheader("1 · Grupo")
    c1, c2 = st.columns([1, 3])
    nivel = c1.slider("Nível do grupo", 1, 20, 5)
    n_pjs = c1.number_input("Personagens", 1, 6, 4)
    nomes = [c.nome for c in defn.classes]
    ids = {c.nome: c.id for c in defn.classes}
    padrao = ("Guerreiro", "Clérigo", "Ladino", "Mago", "Paladino", "Bardo")
    cols = c2.columns(int(n_pjs))
    classes = [
        col.selectbox(f"PJ {i + 1}", nomes, index=nomes.index(padrao[i]), key=f"pj_{i}")
        for i, col in enumerate(cols)
    ]
    fichas = [gerar_ficha(cat, nivel, classe=ids[c], seed=i + 1) for i, c in enumerate(classes)]
    perfis = [perfil(f, cat) for f in fichas]
    st.dataframe(
        [
            {
                "Nome": p.nome,
                "Classe": p.classe,
                "PV": p.pv,
                "CA": p.ca,
                "Dano/rodada (vs CA 15)": round(p.dpr(15), 1),
                "Tipos de dano": ", ".join(sorted(TIPOS_PT.get(t, t) for t in p.tipos_dano)),
                "Cura": "sim" if p.cura else "",
                "Área": "sim" if p.area else "",
            }
            for p in perfis
        ],
        hide_index=True,
        use_container_width=True,
    )
    with st.expander("Fraquezas e forças do grupo", expanded=True):
        mostrar_achados(analisar_grupo(fichas, cat))

    st.subheader("2 · Encontro")
    ordenados = sorted(cat.monstros, key=lambda m: (m.cr, m.nome))
    rotulos = {f"{m.nome} (CR {_cr(m.cr)})": m for m in ordenados}
    escolhidos = st.multiselect("Monstros", list(rotulos), default=["Owlbear (CR 3)"])
    if not escolhidos:
        st.info("Escolha ao menos um monstro.")
        return
    qcols = st.columns(len(escolhidos))
    monstros = [
        (rotulos[r], int(col.number_input(f"Qtd. {rotulos[r].nome}", 1, 20, 1, key=f"q_{r}")))
        for r, col in zip(escolhidos, qcols, strict=True)
    ]
    resumo, achados = analisar_encontro(fichas, monstros, cat)
    m = st.columns(4)
    m[0].metric("Dificuldade oficial (XP)", resumo.dificuldade_oficial)
    m[1].metric("XP ajustado", f"{resumo.xp_ajustado:,.0f}")
    m[2].metric("Rodadas para vencer", f"{resumo.rodadas_para_vencer:.1f}")
    m[3].metric("Rodadas até o grupo cair", f"{resumo.rodadas_para_perder:.1f}")
    st.caption(
        "Estimativas por média de dano esperado (chance de acerto × dano, com resistências). "
        "Não consideram táticas, terreno nem magias de controle."
    )
    mostrar_achados(achados)


# --------------------------------------------------------------------------- detector
NOMES_SISTEMAS = {"dnd5e": "D&D 5e", "fm": "Feiticeiros & Maldições", "tagmar": "Tagmar"}
LIMITE_PAGINAS = 200


def pagina_detector() -> None:
    modelo = modelo_detector()
    st.title("Leitor de livros de RPG")
    st.markdown(
        "Antes de qualquer LLM ler um livro, o **porteiro** confere se é mesmo um livro de RPG "
        "de um sistema suportado. Assim um romance ou um manual não viram fichas, e a cota de "
        "LLM não é gasta à toa."
    )
    st.caption(
        "Envie um PDF ou cole um trecho. O arquivo é lido só na memória deste servidor, não é "
        "salvo e não é enviado a nenhum LLM: a extração roda no Databricks, sobre os livros que "
        "você coloca no seu próprio workspace."
    )
    mostrar_avaliacao_leitor()
    aba_pdf, aba_texto = st.tabs(["📄 Enviar PDF", "📝 Colar texto"])
    paginas: list[str] = []
    with aba_pdf:
        arquivo = st.file_uploader("PDF", type=["pdf"], label_visibility="collapsed")
        if arquivo is not None:
            from pypdf import PdfReader

            leitor = PdfReader(arquivo)
            total = len(leitor.pages)
            with st.spinner("Lendo o PDF…"):
                paginas = [(p.extract_text() or "") for p in leitor.pages[:LIMITE_PAGINAS]]
            if total > LIMITE_PAGINAS:
                st.caption(f"Analisando as primeiras {LIMITE_PAGINAS} de {total} páginas.")
    with aba_texto:
        texto = st.text_area(
            "Texto",
            height=180,
            label_visibility="collapsed",
            placeholder=f"Cole pelo menos {MINIMO_CARACTERES} caracteres de um livro…",
        )
        if not paginas and texto.strip():
            paginas = [texto]

    if not paginas:
        with st.expander("Como funciona", expanded=True):
            st.markdown(
                """
O detector dá uma nota a cada página com base em **6 sinais que um mestre reconheceria**:
notação de dados (`1d20`), modificadores (`+2`), siglas de atributos, vocabulário de regras,
blocos de estatísticas e texto que fala com o leitor. A nota do livro é a média das páginas.

Foi treinado no Databricks com 12 obras de licença aberta e avaliado com *leave-one-book-out*,
em que cada livro é julgado por um modelo que nunca viu nenhuma página dele: **12 de 12 livros
certos**, incluindo romances de fantasia e um livro de regras de xadrez.
"""
            )
        return

    v = avaliar_documento(modelo, paginas)
    if v.paginas_analisadas == 0:
        st.warning(
            f"Texto insuficiente: cole ao menos {MINIMO_CARACTERES} caracteres, ou envie um PDF "
            "com texto selecionável (PDFs escaneados não têm texto)."
        )
        return
    if v.e_rpg:
        st.success(f"**Parece um livro de RPG** (nota {v.nota:.0%})", icon="🎲")
    else:
        st.info(f"**Não parece um livro de RPG** (nota {v.nota:.0%})", icon="📚")
    m = st.columns(3)
    m[0].metric("Páginas analisadas", v.paginas_analisadas)
    m[1].metric("Páginas com cara de RPG", f"{v.fracao_paginas_rpg:.0%}")
    m[2].metric("Sistema provável", NOMES_SISTEMAS.get(v.sistema, "—") if v.sistema else "—")
    st.markdown("**Por quê:**")
    for motivo in v.motivos:
        st.write(f"- {motivo.capitalize()}")

    decisao = decidir(modelo, paginas)
    st.markdown("**Porteiro do leitor:**")
    if decisao.aceito:
        st.success(
            f"Seguiria para a extração com LLM: {decisao.motivo}. "
            f"{sum(parece_ter_entradas(p) for p in paginas)} página(s) passariam no pré-filtro.",
            icon="✅",
        )
    else:
        st.warning(f"Barrado antes do LLM: {decisao.motivo}.", icon="⛔")

    uteis = [p for p in paginas if len(p.strip()) >= MINIMO_CARACTERES]
    if len(uteis) > 1:
        st.caption("Nota de cada página")
        st.bar_chart([modelo.prob_pagina(p) for p in uteis], height=180)


def mostrar_avaliacao_leitor() -> None:
    if not AVALIACAO_LEITOR.exists():
        return
    dados = json.loads(AVALIACAO_LEITOR.read_text(encoding="utf-8"))
    st.subheader("Qual LLM lê melhor um livro de RPG?")
    st.caption(
        f"{dados['livro']}: {dados['paginas_avaliadas']} páginas sorteadas, com "
        f"{dados['magias_esperadas']} magias e {dados['monstros_esperados']} monstros. Cada campo "
        "extraído foi comparado com o catálogo oficial do SRD (gabarito). Rodado no Databricks "
        "com ai_query; métricas no MLflow."
    )
    linhas = []
    for m in dados["modelos"]:
        linhas.append(
            {
                "Modelo": m["modelo"].removeprefix("databricks-"),
                "Nota geral": round(m["nota_geral"], 3),
                "Magias: F1": round(m.get("magias_f1", 0), 3),
                "Magias: campos certos": f"{m.get('magias_campos_media', 0):.0%}",
                "Monstros: F1": round(m.get("monstros_f1", 0), 3),
                "Monstros: campos certos": f"{m.get('monstros_campos_media', 0):.0%}",
                "Tempo (s)": round(m["segundos"]),
            }
        )
    st.dataframe(linhas, hide_index=True, use_container_width=True)
    st.caption(
        f"Escolhido para o leitor: **{dados['modelo_escolhido'].removeprefix('databricks-')}**"
    )


# --------------------------------------------------------------------------- ficha
def pagina_ficha() -> None:
    regras = obter_regras("dnd5e")
    defn = regras.definicao
    st.title("Ficha rápida · D&D 5e")

    c1, c2, c3 = st.columns([2, 2, 1])
    nome = c1.text_input("Nome", "Aventureira")
    classes = {c.nome: c.id for c in defn.classes}
    classe_nome = c2.selectbox("Classe", list(classes), index=list(classes).index("Guerreiro"))
    nivel = c3.number_input("Nível", 1, defn.nivel_maximo, 1)

    metodos = {"Compra de pontos": "compra_pontos", "Conjunto padrão": "padrao", "Livre": "livre"}
    metodo = st.radio("Como gerar atributos", list(metodos), horizontal=True)

    padrao = dict(zip(ATRIBUTOS, (15, 14, 13, 12, 10, 8), strict=True))
    cols = st.columns(6)
    atributos = {}
    for col, attr in zip(cols, defn.atributos, strict=True):
        atributos[attr.id] = col.number_input(
            attr.abrev, attr.minimo, attr.maximo, padrao[attr.id], key=f"attr_{attr.id}"
        )

    if metodos[metodo] == "compra_pontos":
        custo = custo_compra_pontos(atributos)
        orcamento = defn.extras["compra_pontos"]["orcamento"]
        if custo is None:
            st.caption("Na compra de pontos cada atributo começa entre 8 e 15.")
        else:
            st.progress(min(custo / orcamento, 1.0), text=f"Pontos gastos: {custo} / {orcamento}")

    ficha = Ficha(
        nome=nome or "Sem nome",
        sistema="dnd5e",
        nivel=int(nivel),
        classe=classes[classe_nome],
        atributos=atributos,
        metodo_atributos=metodos[metodo],
    )
    d = regras.derivados(ficha)

    st.divider()
    m = st.columns(5)
    m[0].metric("PV máximo", d.get("pv_maximo", "—"))
    m[1].metric("CA sem armadura", d["ca_sem_armadura"])
    m[2].metric("Iniciativa", f"{d['iniciativa']:+d}")
    m[3].metric("Proficiência", f"+{d['proficiencia']}")
    m[4].metric("CD de magia", d.get("cd_magia", "—"))

    st.markdown("**Modificadores e resistências**")
    linhas = st.columns(6)
    for col, attr in zip(linhas, defn.atributos, strict=True):
        col.markdown(
            f"**{attr.abrev}** {d[f'mod_{attr.id}']:+d}  \n"
            f"resist. {d.get(f'resistencia_{attr.id}', d[f'mod_{attr.id}']):+d}"
        )

    st.divider()
    problemas = regras.validar(ficha)
    if not problemas:
        st.success("Ficha válida pelas regras do SRD 5.1.", icon="✅")
    for p in problemas:
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)


# --------------------------------------------------------------------------- F&M
_ROTULOS_FM = {
    "defesa": "Defesa", "pv_maximo": "PV máximo", "pe": "PE", "estamina": "Estamina",
    "cd_especializacao": "CD de especialização", "atencao": "Atenção",
}  # fmt: skip


def _fm_resumo(ficha: Ficha) -> None:
    regras = obter_regras("fm")
    defn = regras.definicao
    d = regras.derivados(ficha)
    energia = "pe" if "pe" in d else "estamina"
    chaves = ("pv_maximo", "defesa", energia, "cd_especializacao", "atencao")
    for col, chave in zip(st.columns(5), chaves, strict=True):
        col.metric(_ROTULOS_FM[chave], d.get(chave, "—"))
    for col, attr in zip(st.columns(6), defn.atributos, strict=True):
        valor = ficha.atributos.get(attr.id, 10)
        col.markdown(f"**{attr.abrev}**  \n### {valor}  \n{d[f'mod_{attr.id}']:+d}")
    res = defn.extras["resistencias"]
    st.markdown(
        "**Testes de resistência:** "
        + " · ".join(f"{r['nome']} {d[f'resistencia_{rid}']:+d}" for rid, r in res.items())
    )
    extra = f"Iniciativa {d['iniciativa']:+d} · Deslocamento {d['deslocamento']} m"
    if "cd_tecnica" in d:
        extra = (
            f"Ataque amaldiçoado {d['ataque_amaldicoado']:+d} · CD de técnica {d['cd_tecnica']}"
            f" · {extra}"
        )
    st.caption(extra)


def _fm_gerador(regras) -> None:
    defn = regras.definicao
    origens = defn.extras["origens"]
    pericias = defn.extras["pericias"]
    c1, c2, c3, c4 = st.columns(4)
    nivel = c1.slider("Nível", 1, 20, 3, key="fm_nivel")
    papel = c2.selectbox("Papel", ["qualquer", *fm_gerador.PAPEIS], key="fm_papel")
    opcoes = {"Automática": None} | {
        c.nome: c.id for c in defn.classes if papel == "qualquer" or c.papel == papel
    }
    classe = opcoes[c3.selectbox("Especialização", list(opcoes), key="fm_classe")]
    opcoes_origem = {"Automática": None} | {o["nome"]: oid for oid, o in origens.items()}
    origem = opcoes_origem[c4.selectbox("Origem", list(opcoes_origem), key="fm_origem")]
    if "fm_semente" not in st.session_state:
        st.session_state.fm_semente = 1
    if st.button("🎲 Gerar outra", key="fm_gerar"):
        st.session_state.fm_semente += 1
    try:
        ficha = fm_gerador.gerar_ficha(
            nivel,
            classe=classe,
            origem=origem,
            papel=None if papel == "qualquer" else papel,
            seed=st.session_state.fm_semente,
        )
    except ValueError as e:
        st.warning(str(e))
        return
    cls = defn.classe(ficha.classe)
    st.subheader(f"{ficha.nome} · {origens[ficha.origem]['nome']} · {cls.nome} de nível {nivel}")
    st.caption(f"Papel: {cls.papel} — {defn.extras['papeis'][cls.papel]}")
    _fm_resumo(ficha)
    e1, e2 = st.columns(2)
    treinadas = ", ".join(pericias[p]["nome"] for p in ficha.pericias if p in pericias)
    e1.markdown(f"**Perícias treinadas**  \n{treinadas}")
    e1.markdown(f"**Equipamento**  \n{', '.join(ficha.equipamento)}")
    if ficha.poderes:
        e2.markdown(f"**Técnica e feitiços**  \n{', '.join(ficha.poderes)}")
    with st.expander("🔮 Por que essas escolhas?", expanded=True):
        for e in ficha.explicacoes:
            st.write(f"- {e}")
    for p in regras.validar(ficha):
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)
    st.download_button(
        "Baixar ficha (JSON)",
        ficha.model_dump_json(indent=2),
        file_name=f"{ficha.nome.lower()}.json",
        mime="application/json",
        key="fm_baixar",
    )


def _fm_ficha_rapida(regras) -> None:
    defn = regras.definicao
    origens = defn.extras["origens"]
    c1, c2, c3 = st.columns([2, 2, 1])
    classes = {c.nome: c.id for c in defn.classes}
    classe_nome = c1.selectbox("Especialização", list(classes), key="fm_r_classe")
    nomes_origem = {o["nome"]: oid for oid, o in origens.items()}
    origem_nome = c2.selectbox("Origem", list(nomes_origem), key="fm_r_origem")
    nivel = c3.number_input("Nível", 1, defn.nivel_maximo, 1, key="fm_r_nivel")
    metodos = {"Valores fixos": "padrao", "Compra de pontos": "compra_pontos", "Livre": "livre"}
    metodo = st.radio("Atributos", list(metodos), horizontal=True, key="fm_r_metodo")
    valores = dict(
        zip(("for", "con", "des", "int", "sab", "pre"), defn.extras["conjunto_padrao"], strict=True)
    )
    atributos = {}
    for col, attr in zip(st.columns(6), defn.atributos, strict=True):
        atributos[attr.id] = col.number_input(
            attr.abrev, attr.minimo, attr.maximo, valores[attr.id], key=f"fm_attr_{attr.id}"
        )
    if metodos[metodo] == "compra_pontos":
        custo = fm_custo(atributos)
        orcamento = defn.extras["compra_pontos"]["orcamento"]
        if custo is None:
            st.caption("Na compra de pontos cada atributo começa entre 8 e 15.")
        else:
            progresso = max(0.0, min(custo / orcamento, 1.0))
            st.progress(progresso, text=f"Pontos gastos: {custo} / {orcamento}")
    ficha = Ficha(
        nome="Ficha rápida",
        sistema="fm",
        nivel=int(nivel),
        classe=classes[classe_nome],
        origem=nomes_origem[origem_nome],
        atributos=atributos,
        metodo_atributos=metodos[metodo],
    )
    _fm_resumo(ficha)
    problemas = regras.validar(ficha)
    if not problemas:
        st.success("Ficha válida pelas regras de Feiticeiros & Maldições.", icon="✅")
    for p in problemas:
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)


def _fm_grupo(regras) -> None:
    defn = regras.definicao
    st.caption("Monte um grupo de até 4 feiticeiros (fichas geradas) e veja as fraquezas dele.")
    nivel = st.slider("Nível do grupo", 1, 20, 5, key="fm_g_nivel")
    padrao = ["Lutador", "Especialista em Técnica", "Controlador", "—"]
    nomes = ["—", *(c.nome for c in defn.classes)]
    grupo = []
    for i, col in enumerate(st.columns(4)):
        escolha = col.selectbox(
            f"PJ {i + 1}", nomes, index=nomes.index(padrao[i]), key=f"fm_pj_{i}"
        )
        if escolha != "—":
            cid = next(c.id for c in defn.classes if c.nome == escolha)
            grupo.append(
                fm_gerador.gerar_ficha(nivel, classe=cid, nome=f"PJ {i + 1} ({escolha})", seed=i)
            )
    if not grupo:
        return
    linhas = []
    for p in (fm_analise.perfil(f) for f in grupo):
        energia = f"{p.energia} {'PE' if p.tipo_energia == 'pe' else 'estamina'}"
        linhas.append({
            "PJ": p.nome, "PV": p.pv, "Defesa": p.defesa, "Energia": energia,
            "Resistências treinadas": ", ".join(sorted(p.treinado_em)),
        })  # fmt: skip
    st.dataframe(linhas, hide_index=True, use_container_width=True)
    mostrar_achados(fm_analise.analisar_grupo(grupo))


def pagina_fm() -> None:
    regras = obter_regras("fm")
    st.title("Feiticeiros & Maldições")
    st.caption(
        "Segundo sistema do Oráculo. Mecânicas resumidas do Livro de Regras v2.5 (Setsugiri, "
        "Parker e equipe — projeto de fãs gratuito). O livro passa pelo porteiro do leitor no "
        "Databricks, mas o texto dele fica só no workspace privado."
    )
    aba_gerador, aba_ficha, aba_grupo = st.tabs(["Gerador", "Ficha rápida", "Análise de grupo"])
    with aba_gerador:
        _fm_gerador(regras)
    with aba_ficha:
        _fm_ficha_rapida(regras)
    with aba_grupo:
        _fm_grupo(regras)


# --------------------------------------------------------------------------- roteiro
def pagina_roteiro() -> None:
    st.title("Roteiro")
    st.markdown(
        """
| Fase | Entrega | Status |
|---|---|---|
| 0 · Fundação | Motor genérico de fichas, D&D 5e, site no ar, CI/CD | ✅ |
| 1 · D&D SRD | Pipeline no Databricks com o SRD → tabelas gold → gerador de fichas | ✅ |
| 2 · Análises | Fraquezas do grupo, desequilíbrio de encontros, dicas explicáveis | ✅ |
| 3a · Detector de livros | "É livro de RPG?" com modelo explicável, avaliado no MLflow | ✅ |
| 3b · Leitor de livros | Porteiro + extração com LLM avaliada contra o gabarito do SRD | ✅ |
| 4 · Feiticeiros & Maldições | Segundo sistema: fichas, análise de grupo e porteiro | ✅ |
| 5 · Polimento | Resultados, vídeo de demonstração | ⏳ |
"""
    )


# --------------------------------------------------------------------------- licenças
def pagina_conteudo() -> None:
    st.title("Conteúdo e licenças")
    st.markdown(
        """
Este site publica **apenas conteúdo com licença aberta**. O leitor de livros funciona com
qualquer PDF, mas o que é extraído de livros protegidos fica só no ambiente de quem o
processou, e nunca neste site ou no repositório.

Este trabalho inclui material do *System Reference Document 5.1* da Wizards of the Coast LLC,
licenciado sob [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

As mecânicas de **Feiticeiros & Maldições** (Livro de Regras v2.5) são de Setsugiri, Parker
e equipe, num projeto de fãs gratuito inspirado em *Jujutsu Kaisen*, de Gege Akutami. O livro
permite usar o sistema como base com crédito aos autores. Aqui aparecem só fórmulas
resumidas, sem texto do livro.
"""
    )


{
    "Início": pagina_inicio,
    "Gerador de fichas (D&D 5e)": pagina_gerador,
    "Análise de grupo e encontro (D&D 5e)": pagina_analise,
    "Leitor de livros de RPG": pagina_detector,
    "Ficha rápida (D&D 5e)": pagina_ficha,
    "Feiticeiros & Maldições": pagina_fm,
    "Roteiro": pagina_roteiro,
    "Conteúdo e licenças": pagina_conteudo,
}[pagina]()
