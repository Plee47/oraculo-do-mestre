"""Oráculo do Mestre — vitrine pública (Streamlit Community Cloud)."""

from __future__ import annotations

import hashlib
import html
import io
import json
import sys
from pathlib import Path

# Usa sempre o código do repositório (src/), nunca um pacote `oraculo` instalado antes.
# O Streamlit Cloud reaproveita o ambiente entre deploys; sem isto, o site rodaria uma
# versão antiga do pacote depois de cada atualização.
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "app"))

import altair as alt
import streamlit as st
from recarga import recarregar_se_mudou

# O processo do Streamlit não reinicia a cada push: se src/ ou dados/ mudaram, descarta os
# módulos antigos da memória e os caches (ver app/recarga.py).
if recarregar_se_mudou([RAIZ / "src", RAIZ / "dados"]):
    st.cache_resource.clear()
    st.cache_data.clear()

from oraculo.fichas_pdf import (
    TEMAS,
    BlocoImpresso,
    FichaImpressa,
    Tema,
    ValorImpresso,
    atributo_em_branco,
    gerar_pdf,
    tema_para,
)
from oraculo.leitor.cache import cache_configurado
from oraculo.leitor.detector import (
    MINIMO_CARACTERES,
    ModeloDetector,
    Veredito,
    avaliar_documento,
)
from oraculo.leitor.llm import ErroLLM, cliente_configurado
from oraculo.leitor.porteiro import SISTEMAS_SUPORTADOS, Decisao, decidir
from oraculo.nucleo import Ficha, obter_regras
from oraculo.nucleo.analise import Achado
from oraculo.rolagens import (
    LIMITE_TEXTO,
    Distribuicao,
    ErroRolagem,
    distribuicao,
    montar,
)
from oraculo.rolagens import ler as ler_rolagem
from oraculo.rolagens import rolar as rolar_dados
from oraculo.sistemas.dnd5e import ATRIBUTOS, custo_compra_pontos, modificador
from oraculo.sistemas.dnd5e.analise import TIPOS_PT, analisar_encontro, analisar_grupo, perfil
from oraculo.sistemas.dnd5e.catalogo import Catalogo
from oraculo.sistemas.dnd5e.gerador import PAPEIS, calcular_ca, gerar_ficha
from oraculo.sistemas.fm import analise as fm_analise
from oraculo.sistemas.fm import custo_compra_pontos as fm_custo
from oraculo.sistemas.fm import gerador as fm_gerador
from oraculo.sistemas.generico.analise import ALVOS_DIFICULDADE, criatura_de_ficha, sugerir_encontro
from oraculo.sistemas.generico.analise import analisar_encontro as analisar_encontro_lido
from oraculo.sistemas.generico.analise import analisar_grupo as analisar_grupo_lido
from oraculo.sistemas.generico.analise import perfil as perfil_lido
from oraculo.sistemas.generico.formulas import normalizar_id
from oraculo.sistemas.generico.gerador import SISTEMA_LIDO
from oraculo.sistemas.generico.gerador import calcular_derivados as calcular_derivados_lido
from oraculo.sistemas.generico.gerador import gerar_ficha as gerar_ficha_lida
from oraculo.sistemas.generico.gerador import limites as limites_lido
from oraculo.sistemas.generico.gerador import validar as validar_lido
from oraculo.sistemas.generico.impressao import ficha_em_branco, ficha_impressa, tema_do_sistema
from oraculo.sistemas.generico.leitura import (
    ErroLeitura,
    detalhar_opcao,
    leitura_guardada,
    ler_mais_criaturas,
    ler_sistema,
)
from oraculo.sistemas.generico.modelo import SistemaLido, normalizar
from oraculo.sistemas.generico.narrativa import ContextoFicha, contexto_lido, sugerir_narrativa

st.set_page_config(
    page_title="Oráculo do Mestre", page_icon=":material/auto_stories:", layout="wide"
)
# Camada visual sobre o tema de .streamlit/config.toml (ver README, seção Design).
st.html(f"<style>{(Path(__file__).parent / 'estilo.css').read_text(encoding='utf-8')}</style>")

CATALOGO_DND5E = Path(__file__).parents[1] / "dados" / "publicos" / "dnd5e" / "catalogo.json"
MODELO_DETECTOR = Path(__file__).parents[1] / "dados" / "publicos" / "modelos" / "detector_rpg.json"
AVALIACAO_GENERICA = (
    Path(__file__).parents[1] / "dados" / "publicos" / "avaliacoes" / "leitor_generico_srd51.json"
)
AVALIACAO_LEITOR = (
    Path(__file__).parents[1] / "dados" / "publicos" / "avaliacoes" / "leitor_srd51.json"
)
INICIO = "Início"
RESUMO = "Resumo do sistema"
GERADOR = "Gerador de fichas"
FICHA = "Ficha rápida"
ANALISES = "Análises"
BASTIDORES = "Bastidores do leitor"
ROTEIRO = "Roteiro"
CONTEUDO = "Conteúdo e licenças"
EXTRAS = "Extras"
LIMITE_PAGINAS = 600  # livros de regras inteiros (o bestiário costuma estar no fim)
NOMES_SISTEMAS = {"dnd5e": "D&D 5e", "fm": "Feiticeiros & Maldições", "tagmar": "Tagmar"}
REPOSITORIO = "https://github.com/Plee47/oraculo-do-mestre"
CREDITO_FM = (
    "Mecânicas resumidas do Livro de Regras v2.5 de Feiticeiros & Maldições (Setsugiri, Parker "
    "e equipe — projeto de fãs gratuito). Nenhum texto do livro é publicado aqui."
)


@st.cache_resource
def catalogo_dnd5e() -> Catalogo:
    return Catalogo.carregar(CATALOGO_DND5E)


@st.cache_resource
def modelo_detector() -> ModeloDetector:
    return ModeloDetector.carregar(MODELO_DETECTOR)


@st.cache_data(max_entries=3, show_spinner="Lendo o PDF…")
def paginas_do_pdf(dados: bytes) -> tuple[list[str], int]:
    """Texto das primeiras páginas do PDF (só em memória; nada é salvo)."""
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(dados))
    paginas = [(p.extract_text() or "") for p in leitor.pages[:LIMITE_PAGINAS]]
    return paginas, len(leitor.pages)


# --------------------------------------------------------------------------- livro escolhido
# O site gira em torno de um livro validado pelo porteiro: o sistema dele define as regras do
# gerador, da ficha rápida e das análises.
def livro_atual() -> dict | None:
    return st.session_state.get("livro")


def sistema_atual() -> str:
    return livro_atual()["sistema"]


def _ir_para(pagina: str) -> None:
    st.session_state.pagina = pagina


def _downloads_da_ficha(ficha: Ficha, montar_pdf, tema: Tema, em_branco: FichaImpressa) -> None:
    """Ficha preenchida em PDF, ficha em branco do sistema e JSON. `montar_pdf(ficha)` devolve a
    ficha impressa, já com a narrativa, se houver."""
    chave = hashlib.sha256(ficha.model_dump_json().encode()).hexdigest()[:12]
    col_pdf, col_branco, col_json, _ = st.columns([1, 1, 1, 1])
    col_pdf.download_button(
        "Baixar ficha em PDF",
        gerar_pdf(montar_pdf(ficha), tema),
        file_name=f"{normalizar_id(ficha.nome)}.pdf",
        mime="application/pdf",
        icon=":material/picture_as_pdf:",
        type="primary",
        key=f"pdf_{chave}",
        width="stretch",
    )
    col_branco.download_button(
        "Ficha em branco",
        gerar_pdf(em_branco, tema),
        file_name=f"ficha_em_branco_{normalizar_id(em_branco.sistema)}.pdf",
        mime="application/pdf",
        icon=":material/edit_document:",
        help="Para preencher no leitor de PDF ou imprimir, com os campos deste sistema.",
        key=f"branca_{chave}",
        width="stretch",
    )
    col_json.download_button(
        "Baixar em JSON",
        ficha.model_dump_json(indent=2),
        file_name=f"{normalizar_id(ficha.nome)}.json",
        mime="application/json",
        icon=":material/data_object:",
        key=f"baixar_{chave}",
        width="stretch",
    )


def _acoes_da_ficha(
    ficha: Ficha, ctx: ContextoFicha, montar_pdf, tema: Tema, em_branco: FichaImpressa
) -> None:
    """Sugestão criativa e downloads: iguais para qualquer sistema."""
    chave = hashlib.sha256(ficha.model_dump_json().encode()).hexdigest()
    guardadas = st.session_state.setdefault("_narrativas", {})
    cliente = cliente_llm()
    if cliente is not None and st.button(
        "Sugerir aparência, personalidade e história",
        icon=":material/auto_awesome:",
        key=f"narrativa_{chave[:12]}",
    ):
        try:
            with st.spinner("Imaginando o personagem dentro das regras do livro…"):
                narrativa = sugerir_narrativa(
                    ctx, ficha, cliente, st.session_state.get("_paginas_livro")
                )
            guardadas[chave] = narrativa.para_ficha()
        except (ErroLLM, ErroLeitura) as erro:
            st.warning(f"Não consegui sugerir agora: {erro}")
    if chave in guardadas:
        ficha = ficha.model_copy(update={"narrativa": guardadas[chave]})
        with st.container(border=True):
            st.caption(
                "Sugestão criativa da IA, baseada nas escolhas, nos atributos e no livro. "
                "Não é regra: mude à vontade."
            )
            for rotulo, texto in ficha.narrativa.items():
                st.markdown(f"**{rotulo}.** {texto}")
    _downloads_da_ficha(ficha, montar_pdf, tema, em_branco)


def _usar_livro(sistema: str, nome: str, nota: float | None = None, demo: bool = False) -> None:
    st.session_state.livro = {"sistema": sistema, "nome": nome, "nota": nota, "demo": demo}
    st.session_state.pagina = RESUMO


def _trocar_livro() -> None:
    st.session_state.pop("livro", None)
    st.session_state.pop("_paginas_livro", None)
    st.session_state.pagina = INICIO


# --------------------------------------------------------------------------- início
def _pipeline_html() -> str:
    r = catalogo_dnd5e().resumo()
    leitor = "o LLM escolhido"
    if AVALIACAO_LEITOR.exists():
        dados = json.loads(AVALIACAO_LEITOR.read_text(encoding="utf-8"))
        melhor = max(dados["modelos"], key=lambda m: m["nota_geral"])
        nome = html.escape(melhor["modelo"].removeprefix("databricks-"))
        nota = f"{melhor['nota_geral']:.2f}".replace(".", ",")
        leitor = f"<b>{nome}</b> tirou nota <b>{nota}</b> contra o gabarito"
    etapas = [
        ("Ingestão", "Auto Loader · Unity Catalog",
         "PDFs e a API do SRD entram como tabelas <b>bronze</b> num volume do workspace."),
        ("Medalhão", "Delta · bronze → silver → gold",
         f"<b>{r['magias']}</b> magias e <b>{r['monstros']}</b> monstros limpos, validados e "
         "exportados."),
        ("Detector", "scikit-learn · MLflow",
         "Regressão logística com 6 sinais explicáveis: <b>12 de 12</b> livros certos em "
         "leave-one-book-out."),
        ("Leitor", "ai_query · 3 LLMs comparados", f"{leitor} do SRD 5.1."),
        ("Produto", "Asset Bundle · CI/CD · Streamlit",
         "Regras em Python transformam os dados em fichas e análises explicáveis."),
    ]  # fmt: skip
    itens = "".join(
        f'<li><div class="etapa">{e}</div><div class="tec">{tec}</div>'
        f'<div class="feito">{feito}</div></li>'
        for e, tec, feito in etapas
    )
    return f'<div class="pipeline"><ol>{itens}</ol></div>'


def _envio_do_livro() -> None:
    aba_pdf, aba_texto = st.tabs(["Enviar PDF", "Colar texto"])
    paginas: list[str] = []
    nome = ""
    with aba_pdf:
        arquivo = st.file_uploader("PDF do livro de regras", type=["pdf"])
        if arquivo is not None:
            paginas, total = paginas_do_pdf(arquivo.getvalue())
            nome = Path(arquivo.name).stem
            if total > LIMITE_PAGINAS:
                st.caption(f"Analisando as primeiras {LIMITE_PAGINAS} de {total} páginas.")
    with aba_texto:
        texto = st.text_area(
            "Trecho do livro",
            height=140,
            placeholder=f"Cole pelo menos {MINIMO_CARACTERES} caracteres de um livro…",
        )
        if not paginas and texto.strip():
            paginas, nome = [texto], "trecho colado"
    st.caption(
        "Funciona com qualquer livro de RPG: a IA do Databricks lê as regras dele. O arquivo não "
        "é salvo: só trechos selecionados vão ao LLM. O que ela extrai (nunca o texto do livro) "
        "fica numa tabela privada, para este livro abrir mais rápido da próxima vez."
    )

    if not paginas:
        _carregar_sistema_salvo()
        st.markdown("**Sem um livro à mão?** Teste com um sistema que o Oráculo já conhece.")
        for sid, nome_sistema in SISTEMAS_SUPORTADOS.items():
            st.button(
                f"Testar com {nome_sistema}",
                key=f"demo_{sid}",
                icon=":material/play_arrow:",
                on_click=_usar_livro,
                args=(sid, f"Demonstração de {nome_sistema}", None, True),
                width="stretch",
            )
        return

    modelo = modelo_detector()
    v = avaliar_documento(modelo, paginas)
    decisao = decidir(modelo, paginas)
    mostrar_veredito(v, decisao, paginas, modelo)
    pediu_leitura = False
    if decisao.aceito:
        pediu_leitura = st.button(
            "Ler o livro com IA e montar o sistema",
            type="primary",
            icon=":material/auto_awesome:",
        )
        if decisao.caminho == "pronto":
            st.button(
                f"Usar as regras prontas de {SISTEMAS_SUPORTADOS[v.sistema]} (sem IA)",
                icon=":material/bolt:",
                on_click=_usar_livro,
                args=(v.sistema, nome, v.nota),
            )
        st.caption(
            "Na primeira vez leva de 2 a 6 minutos: a IA indexa o livro e lê a mecânica, a "
            "criação e as criaturas. Depois, este livro abre em segundos."
        )
    if pediu_leitura:
        with st.status("Lendo o livro…", expanded=True) as status:
            st.write("Procurando no livro as páginas de mecânica, criação e criaturas.")
            st.write("A IA está lendo essas páginas; livros maiores levam mais tempo.")
            _ler_livro(paginas, nome, v.nota, decisao.incerto)
            status.update(label="Leitura concluída.", state="complete")
        if "_erro_leitura" not in st.session_state:
            st.rerun()
    if st.session_state.get("_erro_leitura"):
        st.error(st.session_state["_erro_leitura"], icon=":material/error:")


def pagina_inicio() -> None:
    texto, envio = st.columns([1.1, 1], gap="large", vertical_alignment="center")
    with texto:
        st.html(
            '<div class="vitrine">'
            "<h1>Conheceu um sistema de RPG? <em>Envie o livro.</em></h1>"
            '<p class="lead">Call of Cthulhu, Vampiro, aquele sistema obscuro da sua mesa: o '
            "Oráculo confere se o PDF é mesmo um livro de RPG, lê as regras e entrega "
            "<strong>o resumo do sistema, fichas e encontros dentro das regras dele</strong>. "
            "Por trás, um pipeline de dados e modelos no Databricks.</p>"
            '<ul class="fluxo">'
            '<li><span class="n">1</span><span><b>Envie</b> o PDF</span></li>'
            '<li><span class="n">2</span><span><b>O porteiro</b> valida</span></li>'
            '<li><span class="n">3</span><span><b>Crie</b> e analise</span></li>'
            "</ul></div>"
        )
    with envio:
        livro = livro_atual()
        if livro:
            origem = "modo demonstração" if livro["demo"] else f"nota {livro['nota']:.0%}"
            st.success(
                f"Livro validado: **{livro['nome']}** · sistema "
                f"**{nome_do_sistema(livro)}** ({origem}).",
                icon=":material/check_circle:",
            )
            b1, b2 = st.columns(2)
            b1.button(
                "Criar uma ficha",
                icon=":material/person_add:",
                on_click=_ir_para,
                args=(GERADOR,),
                type="primary",
                width="stretch",
            )
            b2.button(
                "Enviar outro livro",
                icon=":material/upload_file:",
                on_click=_trocar_livro,
                width="stretch",
            )
        else:
            with st.container(border=True):
                _envio_do_livro()

    st.html('<div style="height: 2.5rem"></div>')
    st.header("Por dentro: um pipeline de dados no Databricks")
    st.caption(
        "Cada número abaixo foi produzido pelo pipeline e vem dos dados exportados para este "
        f"repositório. Código, notebooks e decisões de arquitetura: [GitHub]({REPOSITORIO})."
    )
    st.html(_pipeline_html())


# --------------------------------------------------------------------------- gerador
def _dnd_gerador() -> None:
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
    if st.button("Gerar outra", icon=":material/casino:"):
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

    subclasse = ficha.escolhas.get("subclasse")
    titulo = f"{ficha.nome} · {raca} {classe.nome}"
    if subclasse:
        titulo += f" ({subclasse})"
    st.subheader(f"{titulo} de nível {ficha.nivel}")
    st.caption(f"Papel: {classe.papel} — {defn.extras['papeis'][classe.papel]}")

    m = st.columns(5)
    m[0].metric("PV máximo", d["pv_maximo"])
    m[1].metric("CA", calcular_ca(ficha.atributos, ficha.classe, armadura, escudo))
    m[2].metric("Iniciativa", f"{d['iniciativa']:+d}")
    m[3].metric("Proficiência", f"+{d['proficiencia']}")
    m[4].metric("CD de magia", d.get("cd_magia", "—"))

    st.html(atributos_html({a.abrev: ficha.atributos[a.id] for a in defn.atributos}, modificador))

    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Perícias**")
        st.write(", ".join(cat.pericia(p).nome for p in ficha.pericias))
        st.markdown("**Equipamento**")
        itens = []
        for item_id in ficha.equipamento:
            if item_id in armas:
                a = armas[item_id]
                itens.append((a.nome, f"{a.dano} {a.tipo_dano}"))
            else:
                a = armaduras[item_id]
                itens.append((a.nome, f"CA {'+' if a.categoria == 'escudo' else ''}{a.ca_base}"))
        st.html(itens_html(itens))
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

    with st.expander("Por que essas escolhas?", expanded=True, icon=":material/lightbulb:"):
        for e in ficha.explicacoes:
            st.write(f"- {e}")

    problemas = regras.validar(ficha)
    for p in problemas:
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)

    defn_racas = defn.extras["racas"]
    _acoes_da_ficha(
        ficha,
        ContextoFicha(
            sistema=defn.nome,
            contexto=defn.extras.get("resumo", ""),
            escolhas={
                "Raça": defn_racas.get(ficha.origem, ficha.origem or ""),
                "Classe": classe.nome,
                **({"Subclasse": subclasse} if subclasse else {}),
            },
            atributos=[(a.nome, ficha.atributos[a.id]) for a in defn.atributos],
            valores=[("Pontos de Vida", d["pv_maximo"])],
        ),
        lambda f: _impressa_dnd(f, cat),
        TEMAS["fantasia"],
        _branca_dnd(),
    )


_CREDITO_DND = "SRD 5.1, Wizards of the Coast LLC, CC BY 4.0"


def _impressa_dnd(ficha: Ficha, cat: Catalogo) -> FichaImpressa:
    regras = obter_regras("dnd5e")
    defn = regras.definicao
    d = regras.derivados(ficha)
    armas = {a.id: a for a in cat.armas}
    armaduras = {a.id: a for a in cat.armaduras}
    armadura = next((armaduras[i] for i in ficha.equipamento if i in armaduras
                     and armaduras[i].categoria != "escudo"), None)  # fmt: skip
    escudo = next((armaduras[i] for i in ficha.equipamento if i in armaduras
                   and armaduras[i].categoria == "escudo"), None)  # fmt: skip
    valores = [
        ValorImpresso("Pontos de Vida", str(d["pv_maximo"]), anotar=True),
        ValorImpresso(
            "Classe de Armadura", str(calcular_ca(ficha.atributos, ficha.classe, armadura, escudo))
        ),
        ValorImpresso("Iniciativa", f"{d['iniciativa']:+d}"),
        ValorImpresso("Proficiência", f"+{d['proficiencia']}"),
    ]
    if "cd_magia" in d:
        valores.append(ValorImpresso("CD de magia", str(d["cd_magia"])))
    equipamento = []
    for item in ficha.equipamento:
        if item in armas:
            equipamento.append(f"{armas[item].nome} ({armas[item].dano} {armas[item].tipo_dano})")
        elif item in armaduras:
            equipamento.append(armaduras[item].nome)
    magias = {m.id: m for m in cat.magias}
    por_circulo: dict[int, list[str]] = {}
    for mid in ficha.poderes:
        if mid in magias:
            por_circulo.setdefault(magias[mid].circulo, []).append(magias[mid].nome)
    resistencias = " · ".join(
        f"{a.abrev} {d.get(f'resistencia_{a.id}', d[f'mod_{a.id}']):+d}" for a in defn.atributos
    )
    treinadas = set(ficha.pericias)
    pericias = [ValorImpresso(p.nome, marcado=p.id in treinadas) for p in cat.pericias]
    secoes = [
        ("Testes de resistência", [resistencias]),
        ("Equipamento", equipamento),
        ("Magias", [
            f"{'Truques' if c == 0 else f'{c}º círculo'}: {', '.join(nomes)}"
            for c, nomes in sorted(por_circulo.items())
        ]),
    ]  # fmt: skip
    classe = defn.classe(ficha.classe)
    raca = defn.extras["racas"].get(ficha.origem, ficha.origem or "")
    return FichaImpressa(
        nome=ficha.nome,
        sistema=SISTEMAS_SUPORTADOS["dnd5e"],
        subtitulo=(
            f"{raca} {classe.nome}".strip()
            + (f" ({ficha.escolhas['subclasse']})" if "subclasse" in ficha.escolhas else "")
            + f" de nível {ficha.nivel}"
        ),
        atributos=[(a.abrev, ficha.atributos[a.id], d[f"mod_{a.id}"]) for a in defn.atributos],
        valores=valores,
        secoes=secoes,
        blocos=[BlocoImpresso("Perícias", "marcas", pericias)],
        narrativa=dict(ficha.narrativa),
        credito=_CREDITO_DND,
    )


def _branca_dnd() -> FichaImpressa:
    defn = obter_regras("dnd5e").definicao
    nomes = ["Pontos de Vida", "Classe de Armadura", "Iniciativa", "Proficiência", "CD de magia"]
    return FichaImpressa(
        nome="",
        sistema=SISTEMAS_SUPORTADOS["dnd5e"],
        subtitulo="Ficha em branco",
        atributos=[atributo_em_branco(a.abrev, True) for a in defn.atributos],
        valores=[ValorImpresso(n, anotar=n == "Pontos de Vida") for n in nomes],
        campos=["Nome", "Jogador", "Raça", "Classe", "Subclasse", "Nível"],
        blocos=[
            BlocoImpresso(
                "Testes de resistência",
                "valores",
                [ValorImpresso(a.nome) for a in defn.atributos],
            ),
            BlocoImpresso(
                "Perícias",
                "marcas",
                [ValorImpresso(p.nome) for p in catalogo_dnd5e().pericias],
            ),
            BlocoImpresso("Ataques e magias", linhas=6),
            BlocoImpresso("Equipamento", linhas=4),
            BlocoImpresso("Aparência e história", linhas=4),
        ],
        secoes=[
            (
                "Como calcular",
                [
                    "Modificador: (atributo - 10) / 2, arredondado para baixo.",
                    "Pontos de Vida no nível 1: maior valor do dado de vida da classe + "
                    "modificador de Constituição.",
                    "Classe de Armadura sem armadura: 10 + modificador de Destreza.",
                    "Iniciativa: modificador de Destreza.",
                    "Proficiência: +2 nos níveis 1 a 4, e +1 a cada quatro níveis depois disso.",
                    "CD de magia: 8 + proficiência + modificador do atributo de conjuração.",
                ],
            ),
        ],  # fmt: skip
        credito=_CREDITO_DND,
    )


# --------------------------------------------------------------------------- análise
_ESTILO = {"alerta": st.error, "atencao": st.warning, "info": st.info, "ok": st.success}
_ICONE = {
    "alerta": ":material/error:",
    "atencao": ":material/warning:",
    "info": ":material/info:",
    "ok": ":material/check_circle:",
}


def atributos_html(valores: dict[str, int], mod) -> str:
    """Bloco de atributos: sigla, valor e modificador, se o sistema tiver (sem títulos
    Markdown com âncora). A grade se ajusta à quantidade de atributos do sistema."""
    celulas = "".join(
        f'<div><div class="sigla">{html.escape(sigla)}</div><div class="valor">{v}</div>'
        + (f'<div class="mod">{mod(v):+d}</div>' if mod else "")
        + "</div>"
        for sigla, v in valores.items()
    )
    colunas = max(1, min(len(valores), 9))
    estilo = f"grid-template-columns: repeat({colunas}, minmax(0, 1fr))"
    return f'<div class="atributos" style="{estilo}">{celulas}</div>'


def itens_html(itens: list[tuple[str, str]]) -> str:
    linhas = "".join(
        f"<li>{html.escape(nome)}<span>{html.escape(detalhe)}</span></li>"
        for nome, detalhe in itens
    )
    return f'<ul class="itens">{linhas}</ul>'


def mostrar_achados(achados: list[Achado]) -> None:
    if not achados:
        st.success("Nenhum problema encontrado.", icon=":material/check_circle:")
    for a in achados:
        linhas = [f"**{a.titulo}**", a.detalhe, f"*Regra:* {a.regra}"]
        if a.sugestao:
            linhas.append(f"*Sugestão:* {a.sugestao}")
        texto = "  \n".join(linhas)  # dois espaços + \n = quebra de linha no Markdown
        _ESTILO[a.severidade](texto, icon=_ICONE[a.severidade])


def _cr(cr: float) -> str:
    return {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}.get(cr, f"{cr:g}")


def _dnd_analise() -> None:
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
        width="stretch",
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


# --------------------------------------------------------------------------- porteiro
def mostrar_veredito(
    v: Veredito, decisao: Decisao, paginas: list[str], modelo: ModeloDetector
) -> None:
    if v.paginas_analisadas == 0:
        st.warning(
            f"Texto insuficiente: cole ao menos {MINIMO_CARACTERES} caracteres, ou envie um PDF "
            "com texto selecionável (PDFs escaneados não têm texto)."
        )
        return
    if decisao.aceito:
        st.success(f"**Livro aceito pelo porteiro:** {decisao.motivo}.", icon=":material/verified:")
    else:
        st.info(
            f"**Não parece um livro de RPG** (nota {v.nota:.0%}), então não vira ficha.",
            icon=":material/menu_book:",
        )
    with st.expander("Por que o porteiro decidiu assim?"):
        m = st.columns(3)
        m[0].metric("Páginas analisadas", v.paginas_analisadas)
        m[1].metric("Páginas com cara de RPG", f"{v.fracao_paginas_rpg:.0%}")
        m[2].metric("Sistema provável", NOMES_SISTEMAS.get(v.sistema, "—") if v.sistema else "—")
        for motivo in v.motivos:
            st.write(f"- {motivo.capitalize()}")
        uteis = [p for p in paginas if len(p.strip()) >= MINIMO_CARACTERES]
        if len(uteis) > 1:
            st.caption("Nota de cada página")
            st.bar_chart([modelo.prob_pagina(p) for p in uteis], height=180)


def pagina_bastidores() -> None:
    st.title("Bastidores do leitor")
    st.markdown(
        """
**O porteiro** é um detector treinado no Databricks. Ele dá uma nota a cada página com base em
**6 sinais que um mestre reconheceria**: notação de dados (`1d20`), modificadores (`+2`),
siglas de atributos, vocabulário de regras, blocos de estatísticas e texto que fala com o
leitor. A nota do livro é a média das páginas. D&D 5e e Feiticeiros & Maldições são
reconhecidos por evidência forte (as 12 classes e termos da 5ª edição; o título e a "energia
amaldiçoada") e usam regras prontas; qualquer outro RPG segue para a leitura com IA.

Ele foi avaliado com *leave-one-book-out*: cada livro é julgado por um modelo que nunca viu
nenhuma página dele. Resultado: **12 de 12 livros certos**, incluindo romances de fantasia e um
livro de regras de xadrez.

**A leitura com IA** seleciona, sem LLM, as páginas de visão geral, mecânica, criação de
personagem e criaturas (busca híbrida, sumário e o mapa de títulos do livro) e faz as leituras em
paralelo com o LLM do Databricks. Cada opção só é lida a fundo quando entra numa ficha, e o que já
foi lido fica guardado. A saída vira uma especificação validada: fórmulas passam por um
avaliador seguro (nada de `eval`), itens malformados viram aviso, e você pode corrigir qualquer
número no resumo do sistema.

**A extração em lote** (magias e monstros do SRD) roda no Databricks com `ai_query`, sobre os
livros do seu workspace. O que vem de livros protegidos nunca sai de lá.
"""
    )
    mostrar_avaliacao_leitor()
    mostrar_avaliacao_generica()


def mostrar_avaliacao_generica() -> None:
    if not AVALIACAO_GENERICA.exists():
        return
    dados = json.loads(AVALIACAO_GENERICA.read_text(encoding="utf-8"))
    st.subheader("Como achar as páginas certas de um livro desconhecido?")
    st.caption(
        f"{dados['livro']} lido como se fosse um sistema desconhecido e comparado com o catálogo "
        f"oficial, {dados['repeticoes']} rodadas por estratégia. Rodado no Databricks; métricas "
        "no MLflow."
    )
    nomes = {"palavras": "Palavras-chave", "bm25": "BM25", "hibrida": "Híbrida (BM25 + embeddings)"}
    st.dataframe(
        [
            {
                "Estratégia": nomes.get(e["estrategia"], e["estrategia"]),
                "Nota geral": round(e["media_nota_geral"], 2),
                "Classes achadas": f"{e['media_classes_recall']:.0%}",
                "Criaturas reais": f"{e['media_criaturas_precisao']:.0%}",
                "PV das criaturas certos": f"{e['media_criaturas_pv_acerto']:.0%}",
                "Fórmulas calculáveis": f"{e['media_derivados_calculaveis']:.0%}",
            }
            for e in dados["estrategias"]
        ],
        hide_index=True,
        width="stretch",
    )


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
    st.dataframe(linhas, hide_index=True, width="stretch")
    st.caption(
        f"Escolhido para o leitor: **{dados['modelo_escolhido'].removeprefix('databricks-')}**"
    )


# --------------------------------------------------------------------------- ficha
def _dnd_ficha() -> None:
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
        st.success("Ficha válida pelas regras do SRD 5.1.", icon=":material/check_circle:")
    for p in problemas:
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)
    _downloads_da_ficha(
        ficha, lambda f: _impressa_dnd(f, catalogo_dnd5e()), TEMAS["fantasia"], _branca_dnd()
    )


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
    valores = {a.abrev: ficha.atributos.get(a.id, 10) for a in defn.atributos}
    st.html(atributos_html(valores, lambda v: (v - 10) // 2))
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
    if st.button("Gerar outra", key="fm_gerar", icon=":material/casino:"):
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
    with st.expander("Por que essas escolhas?", expanded=True, icon=":material/lightbulb:"):
        for e in ficha.explicacoes:
            st.write(f"- {e}")
    for p in regras.validar(ficha):
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)
    d = regras.derivados(ficha)
    _acoes_da_ficha(
        ficha,
        ContextoFicha(
            sistema=defn.nome,
            contexto=defn.extras.get("resumo", ""),
            escolhas={"Origem": origens[ficha.origem]["nome"], "Especialização": cls.nome},
            atributos=[(a.nome, ficha.atributos[a.id]) for a in defn.atributos],
            valores=[("Pontos de Vida", d["pv_maximo"])],
        ),
        lambda f: _impressa_fm(f, regras),
        _TEMA_FM,
        _branca_fm(regras),
    )


_TEMA_FM = tema_para("sobrenatural")
_CREDITO_FM = "Feiticeiros & Maldições v2.5, de Setsugiri, Parker e equipe"


def _impressa_fm(ficha: Ficha, regras) -> FichaImpressa:
    defn = regras.definicao
    d = regras.derivados(ficha)
    extras = defn.extras
    energia = "pe" if "pe" in d else "estamina"
    valores = [
        ValorImpresso("Pontos de Vida", str(d["pv_maximo"]), anotar=True),
        ValorImpresso(_ROTULOS_FM[energia], str(d[energia]), anotar=True),
        ValorImpresso("Defesa", str(d["defesa"])),
        ValorImpresso("CD de especialização", str(d["cd_especializacao"])),
        ValorImpresso("Atenção", str(d["atencao"])),
        ValorImpresso("Iniciativa", f"{d['iniciativa']:+d}"),
        ValorImpresso("Deslocamento", f"{d['deslocamento']} m"),
    ]
    if "cd_tecnica" in d:
        valores.append(ValorImpresso("CD de técnica", str(d["cd_tecnica"])))
    resistencias = " · ".join(
        f"{r['nome']} {d[f'resistencia_{rid}']:+d}" for rid, r in extras["resistencias"].items()
    )
    treinadas = set(ficha.pericias)
    pericias = [
        ValorImpresso(p["nome"], marcado=pid in treinadas) for pid, p in extras["pericias"].items()
    ]
    return FichaImpressa(
        nome=ficha.nome,
        sistema=SISTEMAS_SUPORTADOS["fm"],
        subtitulo=(
            f"{extras['origens'][ficha.origem]['nome']} · "
            f"{defn.classe(ficha.classe).nome} de nível {ficha.nivel}"
        ),
        atributos=[(a.abrev, ficha.atributos[a.id], d[f"mod_{a.id}"]) for a in defn.atributos],
        valores=valores,
        secoes=[
            ("Testes de resistência", [resistencias]),
            ("Técnica e feitiços", [", ".join(ficha.poderes)]),
            ("Equipamento", [", ".join(ficha.equipamento)]),
        ],
        blocos=[BlocoImpresso("Perícias", "marcas", pericias)],
        narrativa=dict(ficha.narrativa),
        credito=_CREDITO_FM,
    )


def _branca_fm(regras) -> FichaImpressa:
    extras = regras.definicao.extras
    nomes = ["Pontos de Vida", "PE ou Estamina", "Defesa", "CD de especialização", "Atenção",
             "Iniciativa", "Deslocamento", "CD de técnica"]  # fmt: skip
    return FichaImpressa(
        nome="",
        sistema=SISTEMAS_SUPORTADOS["fm"],
        subtitulo="Ficha em branco",
        atributos=[atributo_em_branco(a.abrev, True) for a in regras.definicao.atributos],
        valores=[ValorImpresso(n, anotar=i < 2) for i, n in enumerate(nomes)],
        campos=["Nome", "Jogador", "Origem", "Especialização", "Nível"],
        blocos=[
            BlocoImpresso(
                "Testes de resistência",
                "valores",
                [ValorImpresso(r["nome"]) for r in extras["resistencias"].values()],
            ),
            BlocoImpresso(
                "Perícias",
                "marcas",
                [ValorImpresso(p["nome"]) for p in extras["pericias"].values()],
            ),
            BlocoImpresso("Técnica e feitiços", linhas=6),
            BlocoImpresso("Equipamento", linhas=4),
            BlocoImpresso("Aparência e história", linhas=4),
        ],
        credito=_CREDITO_FM,
    )


def _fm_ficha_rapida(regras) -> None:
    defn = regras.definicao
    origens = defn.extras["origens"]
    nome = st.text_input("Nome", "Feiticeira", key="fm_r_nome")
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
        nome=nome or "Sem nome",
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
        st.success(
            "Ficha válida pelas regras de Feiticeiros & Maldições.", icon=":material/check_circle:"
        )
    for p in problemas:
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)
    _downloads_da_ficha(ficha, lambda f: _impressa_fm(f, regras), _TEMA_FM, _branca_fm(regras))


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
            "Resistências treinadas": ", ".join(
                sorted(defn.extras["resistencias"][r]["nome"] for r in p.treinado_em)
            ),
        })  # fmt: skip
    st.dataframe(linhas, hide_index=True, width="stretch")
    mostrar_achados(fm_analise.analisar_grupo(grupo))


def pagina_resumo() -> None:
    if sistema_atual() == SISTEMA_LIDO:
        _resumo_lido()
    else:
        _resumo_pronto(sistema_atual())


def pagina_gerador() -> None:
    if sistema_atual() == SISTEMA_LIDO:
        _gerador_lido()
    elif sistema_atual() == "fm":
        st.title("Gerador de fichas · Feiticeiros & Maldições")
        st.caption(CREDITO_FM)
        _fm_gerador(obter_regras("fm"))
    else:
        _dnd_gerador()


def pagina_ficha() -> None:
    if sistema_atual() == SISTEMA_LIDO:
        _ficha_rapida_lida()
    elif sistema_atual() == "fm":
        st.title("Ficha rápida · Feiticeiros & Maldições")
        st.caption(CREDITO_FM)
        _fm_ficha_rapida(obter_regras("fm"))
    else:
        _dnd_ficha()


def pagina_analises() -> None:
    if sistema_atual() == SISTEMA_LIDO:
        _analises_lido()
    elif sistema_atual() == "fm":
        st.title("Análises · Feiticeiros & Maldições")
        _fm_grupo(obter_regras("fm"))
        st.info(
            "Análise de encontro: o livro base de Feiticeiros & Maldições não tem bestiário, "
            "então ainda não há maldições para comparar com o grupo.",
            icon=":material/explore:",
        )
    else:
        _dnd_analise()


# --------------------------------------------------------------------------- sistema lido
# Qualquer livro de RPG: o LLM do Databricks lê o livro e devolve a especificação do sistema
# (oraculo.sistemas.generico). Tudo abaixo usa só essa especificação.
MAX_LEITURAS_POR_SESSAO = 3
MAX_DETALHES_POR_SESSAO = 30  # leituras a fundo de opções (as já guardadas não contam)


def cliente_llm():
    """Cliente do LLM a partir dos segredos do site (ou do ambiente, rodando localmente)."""
    if "_cliente_llm_teste" in st.session_state:  # testes automatizados do site
        return st.session_state["_cliente_llm_teste"]
    return cliente_configurado(_segredos())


def _segredos() -> dict:
    try:
        return dict(st.secrets)
    except Exception:  # sem secrets.toml: vale o ambiente
        return {}


def cache_leituras():
    """Tabela privada do Databricks onde ficam as leituras (nunca o texto do livro)."""
    if "_cache_teste" in st.session_state:  # testes automatizados do site
        return st.session_state["_cache_teste"]
    if "_cache" not in st.session_state:
        st.session_state["_cache"] = cache_configurado(_segredos())
    return st.session_state["_cache"]


def sistema_lido() -> SistemaLido:
    return SistemaLido.model_validate(livro_atual()["lido"])


def nome_do_sistema(livro: dict) -> str:
    if livro["sistema"] == SISTEMA_LIDO:
        return livro["lido"]["nome"]
    return SISTEMAS_SUPORTADOS[livro["sistema"]]


def _usar_sistema_lido(s: SistemaLido, nome_arquivo: str, nota: float | None) -> None:
    st.session_state.livro = {
        "sistema": SISTEMA_LIDO,
        "nome": nome_arquivo,
        "nota": nota,
        "demo": False,
        "lido": json.loads(s.model_dump_json()),
    }
    st.session_state["_pagina_pendente"] = RESUMO  # o menu pode já estar desenhado


def _ler_livro(paginas: list[str], nome: str, nota: float | None, incerto: bool) -> None:
    """Lê o livro com o LLM (uma vez por arquivo na sessão) e abre o resumo do sistema."""
    st.session_state["_paginas_livro"] = paginas  # só em memória: para as leituras a fundo
    chave = hashlib.sha256("\n".join(paginas).encode()).hexdigest()
    lidos = st.session_state.setdefault("_lidos", {})
    if chave not in lidos:
        cache = cache_leituras()
        guardada = leitura_guardada(paginas, cache)
        if guardada is not None:  # já lido antes (por qualquer pessoa): não gasta LLM
            lidos[chave] = guardada.sistema.model_dump_json()
            st.session_state.pop("_erro_leitura", None)
            _usar_sistema_lido(guardada.sistema, nome, nota)
            return
        feitas = st.session_state.get("_leituras", 0)
        if feitas >= MAX_LEITURAS_POR_SESSAO:
            st.session_state["_erro_leitura"] = (
                f"Limite de {MAX_LEITURAS_POR_SESSAO} leituras por sessão atingido (a cota de "
                "LLM é compartilhada). Recarregue a página mais tarde ou use um sistema salvo."
            )
            return
        cliente = cliente_llm()
        if cliente is None:
            st.session_state["_erro_leitura"] = (
                "A leitura com IA não está configurada neste servidor (faltam DATABRICKS_HOST e "
                "DATABRICKS_TOKEN nos segredos)."
            )
            return
        st.session_state["_leituras"] = feitas + 1
        try:
            leitura = ler_sistema(paginas, cliente, nome, cache=cache)
        except (ErroLLM, ErroLeitura) as e:
            st.session_state["_erro_leitura"] = f"Não consegui ler o livro: {e}"
            return
        if incerto and not leitura.e_rpg:
            st.session_state["_erro_leitura"] = (
                "A leitura confirmou que este arquivo não é um livro de regras de RPG."
            )
            return
        lidos[chave] = leitura.sistema.model_dump_json()
    st.session_state.pop("_erro_leitura", None)
    _usar_sistema_lido(SistemaLido.model_validate_json(lidos[chave]), nome, nota)


def _carregar_sistema_salvo() -> None:
    with st.expander("Já leu este livro antes? Carregue o sistema salvo (.json)"):
        arquivo = st.file_uploader(
            "Sistema salvo pelo Oráculo",
            type=["json"],
            key="sistema_salvo",
            label_visibility="collapsed",
        )
        if arquivo is None:
            return
        try:
            s = normalizar(SistemaLido.model_validate_json(arquivo.getvalue()))
        except ValueError:
            st.error("Esse arquivo não é um sistema salvo pelo Oráculo.")
            return
        st.button(
            f"Usar {s.nome}",
            icon=":material/arrow_forward:",
            type="primary",
            on_click=_usar_sistema_lido,
            args=(s, Path(arquivo.name).stem, None),
        )


def _faixa(s: SistemaLido, a) -> str:
    mn, mx = limites_lido(s, a)
    if mn is None and mx is None:
        return "—"
    return f"{mn if mn is not None else '…'} a {mx if mx is not None else '…'}"


def _paginas_html(paginas: list[int]) -> str:
    return ", ".join(str(p) for p in paginas[:12]) + ("…" if len(paginas) > 12 else "")


def _resumo_lido() -> None:
    s = sistema_lido()
    st.title(f"Resumo do sistema · {s.nome}")
    linha = " · ".join(x for x in (s.genero, s.autores) if x)
    if linha:
        st.caption(linha)
    st.caption(
        "Resumo escrito pela IA a partir do livro que você enviou (nada foi salvo). Confira e, "
        "se algo estiver errado, corrija em **Corrigir a leitura** no fim da página."
    )
    if s.resumo:
        st.markdown(s.resumo)
    if s.ambientacao:
        st.markdown(f"**Ambientação.** {s.ambientacao}")

    st.subheader("Como se joga")
    m = s.mecanica
    c = st.columns(3)
    c[0].metric("Dado base", m.dado_base or "—")
    c[1].metric("Acerto típico (estimado)", f"{m.chance_acerto_estimada:.0%}")
    c[2].metric(
        s.niveis.nome.capitalize() if s.niveis.usa_niveis else "Níveis",
        s.niveis.nivel_inicial if s.niveis.usa_niveis else "não usa",
    )
    if m.resolucao:
        st.markdown(f"**Teste.** {m.resolucao}")
    if m.criticos:
        st.markdown(f"**Críticos.** {m.criticos}")
    if m.dano_basico or m.dano_explicacao:
        extra = f" Fórmula usada nas análises: `{m.dano_basico}`." if m.dano_basico else ""
        st.markdown(f"**Dano.** {m.dano_explicacao}{extra}")

    st.subheader("Criação de personagem")
    if s.etapas:
        for i, e in enumerate(s.etapas, 1):
            quando = f" (a partir do nível {e.nivel_minimo})" if e.nivel_minimo > 1 else ""
            st.markdown(f"**{i}. {e.nome}**{quando}. {e.instrucao}")
            if e.opcoes:
                nomes = ", ".join(o.nome for o in e.opcoes[:30])
                st.caption(nomes + ("…" if len(e.opcoes) > 30 else ""))
    if s.geracao.explicacao:
        st.markdown(f"**Atributos.** {s.geracao.explicacao}")
    for g in s.geracao.grupos:
        st.markdown(f"- **{g.nome or 'Grupo'}:** {g.explicacao or g.metodo}")
    if s.modificador:
        st.markdown(f"**Modificador de atributo:** `{s.modificador}` (valor = atributo).")
    if s.atributos:
        st.dataframe(
            [
                {
                    "Atributo": a.nome,
                    "Sigla": a.sigla,
                    "Faixa": _faixa(s, a),
                    "Rolagem": a.rolagem or "",
                    "O que mede": a.descricao,
                }
                for a in s.atributos
            ],
            hide_index=True,
            width="stretch",
        )
    if s.derivados:
        st.markdown("**Valores calculados**")
        st.dataframe(
            [
                {
                    "Valor": d.nome,
                    "Fórmula": d.formula or "(não calculável: ver explicação)",
                    "Tipo": d.tipo,
                    "Explicação": d.explicacao,
                }
                for d in s.derivados
            ],
            hide_index=True,
            width="stretch",
        )
    if s.arquetipos:
        st.markdown(f"**{s.nome_arquetipo.capitalize()}s** ({len(s.arquetipos)})")
        st.dataframe(
            [
                {
                    "Nome": a.nome,
                    "Papel": a.papel,
                    "Atributos-chave": ", ".join(s.atributo(x).nome for x in a.atributos_chave),
                    "Descrição": a.descricao,
                }
                for a in s.arquetipos
            ],
            hide_index=True,
            width="stretch",
        )
    cols = st.columns(3)
    cols[0].metric("Perícias", len(s.pericias))
    cols[1].metric("Criaturas com estatísticas", len(s.criaturas))
    cols[2].metric("Páginas lidas pela IA", sum(len(v) for v in s.paginas_fonte.values()))
    if s.regras_encontro:
        st.markdown(f"**Encontros, segundo o livro.** {s.regras_encontro}")
    if s.avisos:
        with st.expander(
            f"O que a leitura não conseguiu ({len(s.avisos)})", icon=":material/info:"
        ):
            for a in s.avisos:
                st.write(f"- {a}")
    with st.expander("Páginas usadas em cada parte da leitura"):
        rotulos = {
            "visao": "Visão geral e mecânica",
            "criacao": "Criação de personagem",
            "criaturas": "Criaturas",
        }
        for k, v in s.paginas_fonte.items():
            st.write(f"- {rotulos.get(k, k)}: {_paginas_html(v) or '—'}")
    _corrigir_leitura(s)
    st.download_button(
        "Salvar o sistema lido (.json)",
        s.model_dump_json(indent=1),
        file_name=f"{normalizar_id(s.nome)}.json",
        mime="application/json",
        icon=":material/download:",
    )


def _corrigir_leitura(s: SistemaLido) -> None:
    with st.expander("Corrigir a leitura", icon=":material/edit:"):
        st.caption(
            "A IA pode errar um número. Ajuste aqui e as fichas e análises passam a usar a "
            "correção. As fórmulas usam os ids dos atributos (coluna id), mod_<id> para o "
            "modificador e nivel para o nível."
        )
        c = st.columns(3)
        nivel = c[0].number_input("Nível inicial", 1, 100, s.niveis.nivel_inicial)
        dano = c[1].text_input("Dano de um ataque básico (fórmula)", s.mecanica.dano_basico)
        mult = c[2].number_input(
            "Multiplicador médio de dano",
            0.1,
            10.0,
            float(s.mecanica.multiplicador_dano_medio),
            step=0.1,
        )
        modificador = st.text_input("Modificador de atributo (fórmula com valor)", s.modificador)
        atributos = st.data_editor(
            [
                {
                    "id": a.id,
                    "nome": a.nome,
                    "minimo": a.minimo,
                    "maximo": a.maximo,
                    "rolagem": a.rolagem or "",
                }
                for a in s.atributos
            ],
            hide_index=True,
            width="stretch",
            key="editor_atributos",
            disabled=["id", "nome"],
        )
        derivados = st.data_editor(
            [
                {"id": d.id, "nome": d.nome, "formula": d.formula, "tipo": d.tipo}
                for d in s.derivados
            ],
            hide_index=True,
            width="stretch",
            key="editor_derivados",
            disabled=["id", "nome"],
            column_config={
                "tipo": st.column_config.SelectboxColumn(
                    options=["vida", "defesa", "recurso", "iniciativa", "movimento", "outro"]
                )
            },
        )
        if st.button("Aplicar correções", icon=":material/check:"):
            dados = json.loads(s.model_dump_json())
            dados["niveis"]["nivel_inicial"] = int(nivel)
            dados["mecanica"]["dano_basico"] = dano
            dados["mecanica"]["multiplicador_dano_medio"] = mult
            dados["modificador"] = modificador
            por_id = {linha["id"]: linha for linha in atributos}
            for a in dados["atributos"]:
                linha = por_id.get(a["id"], {})
                for campo in ("minimo", "maximo"):
                    v = linha.get(campo)
                    a[campo] = None if v in (None, "") or v != v else int(v)
                a["rolagem"] = linha.get("rolagem") or None
            por_id = {linha["id"]: linha for linha in derivados}
            for d in dados["derivados"]:
                linha = por_id.get(d["id"], {})
                d["formula"] = linha.get("formula") or ""
                d["tipo"] = linha.get("tipo") or "outro"
            dados["avisos"] = []
            corrigido = normalizar(SistemaLido.model_validate(dados))
            st.session_state.livro["lido"] = json.loads(corrigido.model_dump_json())
            st.success("Correções aplicadas.", icon=":material/check_circle:")
            for a in corrigido.avisos:
                st.warning(a)


def _resumo_pronto(sistema: str) -> None:
    defn = obter_regras(sistema).definicao
    st.title(f"Resumo do sistema · {SISTEMAS_SUPORTADOS[sistema]}")
    st.caption(f"{defn.fonte} · {defn.licenca}")
    st.markdown(defn.extras.get("resumo", ""))
    st.markdown("**Atributos:** " + ", ".join(f"{a.nome} ({a.abrev})" for a in defn.atributos))
    rotulo = "Especializações" if sistema == "fm" else "Classes"
    st.markdown(f"**{rotulo}:** " + ", ".join(c.nome for c in defn.classes))
    st.caption("Regras prontas do Oráculo: escritas e testadas à mão, não lidas por IA.")


def _ficha_lida_html(s: SistemaLido, ficha: Ficha) -> None:
    derivados = calcular_derivados_lido(s, ficha.atributos, ficha.nivel, ficha.classe)
    principais = [(d, v) for d, v in derivados if v is not None][:5]
    if principais:
        for col, (d, v) in zip(st.columns(len(principais)), principais, strict=True):
            col.metric(d.nome, v)
    rotulos: dict[str, int] = {}
    for a in s.atributos:
        rotulo = (a.sigla or a.nome).upper()
        while rotulo in rotulos:  # siglas repetidas no livro não somem do bloco
            rotulo += "·"
        rotulos[rotulo] = ficha.atributos.get(a.id, 0)
    mod = (lambda v: int(s.modificador_de(v) or 0)) if s.modificador else None
    st.html(atributos_html(rotulos, mod))
    sem_valor = [d.nome for d, v in derivados if v is None]
    if sem_valor:
        st.caption(f"Sem fórmula calculável no livro: {', '.join(sem_valor)} (veja o resumo).")


def _colunas_de(n: int) -> list:
    """Colunas para n controles, em linhas de no máximo 4."""
    colunas = []
    while len(colunas) < n:
        colunas += st.columns(min(4, n - len(colunas)))
    return colunas


def _ler_a_fundo(s: SistemaLido, ficha: Ficha) -> bool:
    """Lê a fundo as opções escolhidas nesta ficha que ainda não foram lidas (no máx. uma vez
    cada: depois vêm do cache). Devolve True se algo mudou."""
    pendentes = [
        (e, e.opcao(ficha.escolhas[e.id]))
        for e in s.etapas
        if e.id in ficha.escolhas and e.opcao(ficha.escolhas[e.id])
        and not e.opcao(ficha.escolhas[e.id]).detalhada
    ]  # fmt: skip
    paginas = st.session_state.get("_paginas_livro")
    cliente = cliente_llm()
    if not pendentes or not paginas or cliente is None:
        return False
    if not st.toggle("Ler a fundo as opções desta ficha", True, key="lido_fundo"):
        return False
    feitos = st.session_state.get("_detalhes", 0)
    if feitos >= MAX_DETALHES_POR_SESSAO:
        st.caption("Limite de leituras a fundo desta sessão atingido (a cota é compartilhada).")
        return False
    mudou = False
    with st.status("Lendo no livro o que escolhemos…", expanded=True) as status:
        for e, o in pendentes:
            st.write(f"{e.nome}: {o.nome}")
            try:
                detalhar_opcao(s, e.id, o.nome, paginas, cliente, cache_leituras())
                mudou = True
            except (ErroLLM, ErroLeitura) as erro:
                st.warning(f"Não consegui ler {o.nome} a fundo: {erro}")
            st.session_state["_detalhes"] = feitos = feitos + 1
        status.update(label="Leitura concluída.", state="complete", expanded=False)
    if mudou:
        st.session_state.livro["lido"] = json.loads(s.model_dump_json())
    return mudou


def _habilidades_da_ficha(s: SistemaLido, ficha: Ficha) -> None:
    linhas = []
    for e in s.etapas:
        o = e.opcao(ficha.escolhas.get(e.id))
        if not o:
            continue
        for h in o.habilidades_detalhe:
            if h.nivel is None or h.nivel <= ficha.nivel:
                linhas.append({
                    "Vem de": o.nome, "Habilidade": h.nome, "Efeito": h.resumo,
                    "Página": "—" if h.pagina is None else str(h.pagina),
                })  # fmt: skip
    if linhas:
        st.markdown("**Habilidades deste nível, segundo o livro**")
        st.dataframe(linhas, hide_index=True, width="stretch")


def _gerador_lido() -> None:
    s = sistema_lido()
    st.title(f"Gerador de fichas · {s.nome}")
    st.caption("Fichas pelas regras lidas do seu livro, com cada escolha explicada.")
    nivel = None
    if s.niveis.usa_niveis:
        topo = s.niveis.nivel_maximo or max(20, s.niveis.nivel_inicial)
        nivel = st.slider(
            s.niveis.nome.capitalize(), 1, topo, s.niveis.nivel_inicial, key="lido_nivel"
        )
    pedidas: dict[str, str] = {}
    escolha = "Automático"
    etapas = s.etapas_de_escolha(nivel or s.niveis.nivel_inicial)
    if etapas:
        for e, col in zip(etapas, _colunas_de(len(etapas)), strict=True):
            opcoes = e.opcoes_de(pedidas.get(e.depende_de))
            rotulos = ["Automático", *(o.nome for o in opcoes)]
            valor = col.selectbox(e.nome, rotulos, key=f"lido_etapa_{e.id}")
            if valor != "Automático":
                pedidas[e.id] = valor
    elif s.arquetipos:
        rotulos = ["Automático", *(a.nome for a in s.arquetipos)]
        escolha = st.selectbox(s.nome_arquetipo.capitalize(), rotulos, key="lido_arq")
    if "lido_semente" not in st.session_state:
        st.session_state.lido_semente = 1
    if st.button("Gerar outra", key="lido_gerar", icon=":material/casino:"):
        st.session_state.lido_semente += 1
    args = {
        "arquetipo": None if escolha == "Automático" else escolha,
        "nivel": nivel,
        "seed": st.session_state.lido_semente,
        "escolhas": pedidas,
    }
    # O sorteio fica fixo até "Gerar outra": a leitura a fundo pode revelar novas opções, e a
    # ficha não pode mudar sozinha entre uma interação e outra.
    fixas = st.session_state.setdefault("_sorteios", {})
    chave_sorteio = (args["seed"], args["nivel"], args["arquetipo"], tuple(sorted(pedidas.items())))
    if chave_sorteio not in fixas:
        fixas[chave_sorteio] = gerar_ficha_lida(s, **args).escolhas
    args["sorteadas"] = fixas[chave_sorteio]
    ficha = gerar_ficha_lida(s, **args)
    if _ler_a_fundo(s, ficha):  # a leitura a fundo pode mudar atributos-chave, bônus e fórmulas
        s = sistema_lido()
        ficha = gerar_ficha_lida(s, **args)
    titulo = " · ".join(x for x in (ficha.nome, ficha.classe) if x)
    if s.niveis.usa_niveis:
        titulo += f" · {s.niveis.nome} {ficha.nivel}"
    st.subheader(titulo)
    _ficha_lida_html(s, ficha)
    e1, e2 = st.columns(2)
    if ficha.pericias:
        e1.markdown(f"**Perícias**  \n{', '.join(ficha.pericias)}")
    if ficha.equipamento:
        e1.markdown(f"**Equipamento**  \n{', '.join(ficha.equipamento)}")
    if ficha.poderes:
        e2.markdown(f"**Habilidades**  \n{', '.join(ficha.poderes)}")
    _habilidades_da_ficha(s, ficha)
    with st.expander("Por que essas escolhas?", expanded=True, icon=":material/lightbulb:"):
        for e in ficha.explicacoes:
            st.write(f"- {e}")
    for p in validar_lido(s, ficha):
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)
    _acoes_da_ficha(
        ficha,
        contexto_lido(s, ficha),
        lambda f: ficha_impressa(s, f),
        tema_do_sistema(s),
        ficha_em_branco(s),
    )


def _ficha_rapida_lida() -> None:
    s = sistema_lido()
    st.title(f"Ficha rápida · {s.nome}")
    st.caption("Digite os atributos e veja os valores calculados pelas fórmulas do livro.")
    nome = st.text_input("Nome", "Personagem", key="lido_r_nome")
    c1, c2 = st.columns(2)
    arquetipos = ["—", *(a.nome for a in s.arquetipos)]
    arq = c1.selectbox(s.nome_arquetipo.capitalize(), arquetipos, key="lido_r_arq")
    nivel = 1
    if s.niveis.usa_niveis:
        nivel = int(
            c2.number_input(
                s.niveis.nome.capitalize(), 1, 100, s.niveis.nivel_inicial, key="lido_r_nivel"
            )
        )
    base = gerar_ficha_lida(s, seed=1, nivel=nivel).atributos
    atributos = {}
    colunas = st.columns(max(1, min(len(s.atributos), 6)))
    for i, a in enumerate(s.atributos):
        mn, mx = limites_lido(s, a)
        atributos[a.id] = int(
            colunas[i % len(colunas)].number_input(
                f"{a.nome} ({a.sigla})" if a.sigla else a.nome,
                min_value=mn if mn is not None else -100,
                max_value=mx if mx is not None else 1000,
                value=base.get(a.id, mn or 0),
                key=f"lido_attr_{a.id}",
            )
        )
    ficha = Ficha(
        nome=nome or "Sem nome",
        sistema=SISTEMA_LIDO,
        nivel=nivel,
        atributos=atributos,
        classe=None if arq == "—" else arq,
    )
    st.divider()
    _ficha_lida_html(s, ficha)
    problemas = validar_lido(s, ficha)
    if not problemas:
        st.success("Ficha dentro das regras lidas do livro.", icon=":material/check_circle:")
    for p in problemas:
        (st.error if p.gravidade == "erro" else st.warning)(p.mensagem)
    _downloads_da_ficha(
        ficha, lambda f: ficha_impressa(s, f), tema_do_sistema(s), ficha_em_branco(s)
    )


def _tabela_criaturas(criaturas: list) -> None:
    linhas = []
    for c in criaturas:
        ataques = "; ".join(f"{a.nome} ({a.dano})" if a.dano else a.nome for a in c.ataques)
        linhas.append({
            "Criatura": c.nome,
            "Ameaça": c.ameaca or "—",
            "Vida": "—" if c.vida is None else str(c.vida),
            "Defesa": "—" if c.defesa is None else str(c.defesa),
            "Ataques": ataques or "—",
            "Página": "—" if c.pagina is None else str(c.pagina),
        })  # fmt: skip
    st.dataframe(linhas, hide_index=True, width="stretch")


def _mais_criaturas(s: SistemaLido) -> None:
    """Lê mais um lote de páginas de criaturas, só se a pessoa pedir."""
    paginas = st.session_state.get("_paginas_livro")
    cliente = cliente_llm()
    if not paginas or cliente is None:
        return
    st.caption(f"O Oráculo leu {len(s.criaturas)} criaturas deste livro até agora.")
    if not st.button("Ler mais criaturas do livro", icon=":material/menu_book:", key="lido_mais"):
        return
    try:
        with st.spinner("Lendo mais páginas de criaturas…"):
            novas = ler_mais_criaturas(s, paginas, cliente, cache_leituras())
    except (ErroLLM, ErroLeitura) as erro:
        st.warning(f"Não consegui ler mais criaturas: {erro}")
        return
    st.session_state.livro["lido"] = json.loads(s.model_dump_json())
    st.session_state["_aviso_criaturas"] = (
        f"{novas} criaturas novas." if novas else "Não achei mais criaturas com números."
    )
    st.rerun()


def _analises_lido() -> None:
    s = sistema_lido()
    st.title(f"Análises · {s.nome}")
    st.caption(
        "Cada dica cita a regra lida do livro. As contas de encontro são estimativas por valor "
        "médio; quando o livro não deu um número, a análise diz o que falta."
    )
    st.subheader("Grupo")
    nivel = None
    if s.niveis.usa_niveis:
        topo = s.niveis.nivel_maximo or max(20, s.niveis.nivel_inicial)
        nivel = st.slider(
            f"{s.niveis.nome.capitalize()} do grupo",
            1,
            topo,
            s.niveis.nivel_inicial,
            key="lido_g_nivel",
        )
    nomes = ["—", *(a.nome for a in s.arquetipos)] if s.arquetipos else ["—", "Personagem"]
    padrao = (nomes[1:] * 3)[:3] + ["—"]
    grupo = []
    for i, col in enumerate(st.columns(4)):
        escolha = col.selectbox(
            f"PJ {i + 1}", nomes, index=nomes.index(padrao[i]), key=f"lido_pj_{i}"
        )
        if escolha != "—":
            arq = escolha if s.arquetipos else None
            grupo.append(
                gerar_ficha_lida(s, arquetipo=arq, nivel=nivel, seed=i + 1, nome=f"PJ {i + 1}")
            )
    if not grupo:
        st.info("Escolha ao menos um personagem.")
        return
    linhas = []
    for f in grupo:
        p = perfil_lido(s, f)
        linhas.append(
            {
                "PJ": p.nome,
                s.nome_arquetipo.capitalize(): p.arquetipo,
                "Vida": p.vida,
                "Defesa": p.defesa,
                "Dano por ataque": None if p.dano is None else round(p.dano, 1),
            }
        )
    # Colunas que o livro não permitiu calcular para ninguém somem; células vazias viram "—".
    vazias = {k for k in linhas[0] if all(linha[k] is None for linha in linhas)}
    linhas = [{k: ("—" if v is None else str(v)) for k, v in linha.items() if k not in vazias}
              for linha in linhas]  # fmt: skip
    st.dataframe(linhas, hide_index=True, width="stretch")
    with st.expander("Fraquezas e forças do grupo", expanded=True):
        mostrar_achados(analisar_grupo_lido(s, grupo))

    st.subheader("Encontro")
    if "_aviso_criaturas" in st.session_state:
        st.success(st.session_state.pop("_aviso_criaturas"), icon=":material/check_circle:")
    fontes = ["Sugestão do Oráculo", "Inimigos montados com as regras do livro"]
    if s.criaturas:
        fontes.insert(1, "Criaturas do livro")
    fonte = st.radio("Inimigos", fontes, horizontal=True, key="lido_fonte")
    criaturas = []
    if fonte == "Sugestão do Oráculo":
        dificuldade = st.select_slider(
            "Dificuldade desejada", list(ALVOS_DIFICULDADE), value="equilibrado", key="lido_dific"
        )
        sugestao = sugerir_encontro(s, grupo, dificuldade)
        if sugestao is None:
            st.info(
                "O livro não deu os números para estimar (vida e dano dos personagens e dos "
                "inimigos). Corrija a leitura no resumo do sistema ou monte o encontro à mão.",
                icon=":material/info:",
            )
            _mais_criaturas(s)
            return
        criaturas = sugestao.criaturas
        de_onde = (
            "criaturas do próprio livro"
            if sugestao.origem == "livro"
            else "inimigos montados com as regras do livro (ele não traz criaturas com números)"
        )
        st.markdown(
            "**Encontro sugerido:** "
            + ", ".join(f"{n}× {c.nome}" for c, n in criaturas)
            + f". Vem de {de_onde}."
        )
        _tabela_criaturas([c for c, _ in criaturas])
        if sugestao.resumo.veredito != dificuldade:
            st.caption(
                f'O mais perto de "{dificuldade}" com as opções lidas até agora. Ler mais '
                "criaturas do livro pode aproximar."
            )
    elif fonte == "Criaturas do livro":
        rotulos = {f"{c.nome}" + (f" ({c.ameaca})" if c.ameaca else ""): c for c in s.criaturas}
        escolhidos = st.multiselect(
            "Criaturas", list(rotulos), default=list(rotulos)[:1], key="lido_criaturas"
        )
        if escolhidos:
            for r, col in zip(escolhidos, st.columns(len(escolhidos)), strict=True):
                qtd = int(col.number_input(f"Qtd. {rotulos[r].nome}", 1, 20, 1, key=f"lq_{r}"))
                criaturas.append((rotulos[r], qtd))
    else:
        st.caption(
            "Sem bestiário (ou para PdMs): cada inimigo é montado como um personagem, com as "
            "mesmas regras de criação do livro."
        )
        c1, c2 = st.columns(2)
        arq_inimigo = c1.selectbox(
            f"{s.nome_arquetipo.capitalize()} dos inimigos",
            nomes[1:] if s.arquetipos else ["Personagem"],
            key="lido_arq_ini",
        )
        qtd = int(c2.number_input("Quantidade", 1, 10, 2, key="lido_qtd_ini"))
        for i in range(qtd):
            ficha = gerar_ficha_lida(
                s,
                arquetipo=arq_inimigo if s.arquetipos else None,
                nivel=nivel,
                seed=100 + i,
                nome=f"Inimigo {i + 1}",
            )
            criaturas.append((criatura_de_ficha(s, ficha), 1))
    if not criaturas:
        st.info("Escolha ao menos um inimigo.")
        return
    resumo, achados = analisar_encontro_lido(s, grupo, criaturas)
    m = st.columns(3)
    m[0].metric("Balanço estimado", resumo.veredito)
    m[1].metric(
        "Rodadas para vencer",
        "—" if resumo.rodadas_para_vencer is None else f"{resumo.rodadas_para_vencer:.1f}",
    )
    m[2].metric(
        "Rodadas até o grupo cair",
        "—" if resumo.rodadas_para_perder is None else f"{resumo.rodadas_para_perder:.1f}",
    )
    mostrar_achados(achados)
    _mais_criaturas(s)


# --------------------------------------------------------------------------- roteiro
def pagina_roteiro() -> None:
    st.title("Roteiro")
    st.markdown(
        """
| Fase | Entrega | Status |
|---|---|---|
| 0 · Fundação | Motor genérico de fichas, D&D 5e, site no ar, CI/CD | Feito |
| 1 · D&D SRD | Pipeline no Databricks com o SRD → tabelas gold → gerador de fichas | Feito |
| 2 · Análises | Fraquezas do grupo, desequilíbrio de encontros, dicas explicáveis | Feito |
| 3a · Detector de livros | "É livro de RPG?" com modelo explicável, avaliado no MLflow | Feito |
| 3b · Leitor de livros | Porteiro + extração com LLM avaliada contra o gabarito do SRD | Feito |
| 4 · Feiticeiros & Maldições | Segundo sistema: fichas, análise de grupo e porteiro | Feito |
| 5a · Vitrine | Site que começa pelo livro, design de portfólio | Feito |
| 6 · Qualquer livro | Leitura com IA: resumo, fichas e encontros de qualquer sistema | Feito |
| 7 · Leitura profunda | Etapas de criação, leitura a fundo, narrativa e PDF com tema | Feito |
| 8 · Extras | Rolador de dados, com probabilidades e comparação | Feito |
| 5b · Demonstração | Vídeo curto do fluxo completo | ⏳ |
"""
    )


# --------------------------------------------------------------------------- licenças
# --------------------------------------------------------------------------- extras
_FACES_RAPIDAS = (4, 6, 8, 10, 12, 20, 100, "F")
_MAX_HISTORICO = 50
_MODOS = {"Normal": "normal", "Vantagem": "vantagem", "Desvantagem": "desvantagem"}
_MANUAL_DADOS = """
| Escreva | O que faz |
|---|---|
| `2d6+3` | Soma, subtração, `*`, `/` (arredonda para baixo) e parênteses |
| `d%` · `4dF` | Dado de 100 faces · dado Fudge (-1, 0, +1) |
| `4d6kh3` · `2d20kl1` | Mantém os maiores · os menores |
| `4d6dl1` · `4d6dh1` | Descarta os menores · os maiores |
| `vant` · `desv` | Vantagem e desvantagem (`2d20kh1` e `2d20kl1`) |
| `3d6!` · `3d6!>=5` | Explode no valor máximo · na condição |
| `2d6r1` · `2d6rr<=2` | Rola de novo uma vez · até sair da condição |
| `5d10>=8` · `5d10>=8f1` | Conta sucessos · e desconta as falhas |
| `max(1,1d4-2)` · `teto(1d6/2)` | Também `min` e `piso` |
| `1d20+5, 2d6+3` | Várias rolagens de uma vez, como ataque e dano |
| `6#4d6kh3` | Repete a mesma rolagem |
"""


@st.cache_data(max_entries=64, show_spinner=False)
def _distribuicao(expressao: str) -> Distribuicao:
    return distribuicao(expressao)


def _porcento(p: float) -> str:
    if 0 < p < 0.001:
        return "menos de 0,1%"
    if 0.999 < p < 1:
        return "mais de 99,9%"
    return f"{p:.1%}".replace(".", ",")


def _numero(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def _dado_html(d) -> str:
    classes = ["dado"]
    titulo = []
    if not d.mantido:
        classes.append("fora")
        titulo.append("descartado")
    if d.extremo == "max":
        classes.append("maximo")
        titulo.append("valor máximo")
    elif d.extremo == "min":
        classes.append("minimo")
        titulo.append("valor mínimo")
    if d.resultado:
        classes.append(d.resultado)
        titulo.append(d.resultado)
    if d.explosao:
        titulo.append("veio de uma explosão")
    if d.rerolado_de is not None:
        titulo.append(f"rolado de novo, era {d.rerolado_de}")
    marca = "!" if d.explosao else "↻" if d.rerolado_de is not None else ""
    dica = html.escape(", ".join(titulo))
    return f'<span class="{" ".join(classes)}" title="{dica}">{d.valor}{marca}</span>'


def _rolagem_html(r) -> str:
    grupos = "".join(
        f'<div class="grupo"><span class="notacao">{html.escape(g.notacao)}</span>'
        + "".join(_dado_html(d) for d in g.dados)
        + "</div>"
        for g in r.grupos
    )
    return (
        '<div class="rolagem">'
        f'<div class="topo"><span class="expressao">{html.escape(r.expressao)}</span>'
        f'<span class="total">{r.total}</span></div>{grupos}'
        f'<div class="conta">{html.escape(r.detalhe)} = {r.total}</div></div>'
    )


def _rolar_e_guardar(expressao: str) -> None:
    try:
        rolagens = rolar_dados(expressao)
    except ErroRolagem as erro:
        st.session_state["_erro_rolagem"] = str(erro)
        return
    st.session_state.pop("_erro_rolagem", None)
    st.session_state["_rolagens"] = rolagens
    historico = st.session_state.setdefault("_historico_dados", [])
    historico[:0] = [
        {"Rolagem": r.expressao, "Total": r.total, "Dados": r.detalhe} for r in reversed(rolagens)
    ]
    del historico[_MAX_HISTORICO:]


def _guia_rolar() -> None:
    c1, c2, c3 = st.columns([1, 1, 2])
    quantidade = int(c1.number_input("Quantidade", 1, 100, 1, key="dados_qtd"))
    modificador = int(c2.number_input("Modificador", -1000, 1000, 0, key="dados_mod"))
    modo = _MODOS[c3.radio("Modo", list(_MODOS), horizontal=True, key="dados_modo")]
    with st.container(horizontal=True):  # quebra a linha no celular, sem empilhar um por linha
        for faces in _FACES_RAPIDAS:
            rotulo = f"d{faces}"
            if st.button(rotulo, key=f"rolar_{rotulo}", width="stretch"):
                _rolar_e_guardar(montar(quantidade, faces, modificador, modo))
    dado_do_livro = _dado_do_livro()
    if dado_do_livro and st.button(
        f"Dado do livro: {dado_do_livro}", icon=":material/menu_book:", key="rolar_livro"
    ):
        _rolar_e_guardar(dado_do_livro)

    with st.form("form_rolagem", border=False):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        expressao = c1.text_input(
            "Ou escreva a rolagem", "1d20+5", key="dados_expressao", max_chars=LIMITE_TEXTO
        )
        if c2.form_submit_button(
            "Rolar", type="primary", icon=":material/casino:", width="stretch"
        ):
            _rolar_e_guardar(expressao)
    with st.expander("O que dá para escrever", icon=":material/help:"):
        st.markdown(_MANUAL_DADOS)

    if "_erro_rolagem" in st.session_state:
        st.error(st.session_state["_erro_rolagem"], icon=":material/error:")
    rolagens = st.session_state.get("_rolagens")
    if rolagens:
        st.html("".join(_rolagem_html(r) for r in rolagens))
        if len(rolagens) > 1:
            total = sum(r.total for r in rolagens)
            st.caption(f"Soma de todas: **{total}**")
        st.caption(
            "Riscado (~ na conta): descartado. Borda cheia: valor máximo. Borda tracejada: valor "
            "mínimo. ! explodiu. ↻ rolou de novo. Passe o mouse num dado para ver o motivo."
        )

    _rolagens_salvas()

    historico = st.session_state.get("_historico_dados")
    if historico:
        st.subheader("Histórico")
        st.dataframe(historico, hide_index=True, width="stretch")
        if st.button("Limpar histórico", icon=":material/delete:", key="limpar_historico"):
            st.session_state.pop("_historico_dados", None)
            st.session_state.pop("_rolagens", None)
            st.rerun()


def _dado_do_livro() -> str | None:
    """O dado principal do sistema lido, se ele for uma rolagem que dá para fazer."""
    livro = st.session_state.get("livro")
    if not livro or not livro.get("lido"):
        return None
    dado = sistema_lido().mecanica.dado_base.strip()
    try:
        ler_rolagem(dado)
    except ErroRolagem:
        return None
    return dado


def _rolagens_salvas() -> None:
    salvas = st.session_state.setdefault("_rolagens_salvas", {})
    st.subheader("Rolagens salvas")
    st.caption(
        "Ataque, dano, perícia... Ficam guardadas enquanto esta aba do navegador estiver aberta."
    )
    with st.form("form_salvar", border=False, clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 3, 1], vertical_alignment="bottom")
        nome = c1.text_input(
            "Nome", placeholder="Ataque com espada", key="salvar_nome", max_chars=40
        )
        expressao = c2.text_input(
            "Rolagem", placeholder="1d20+5, 1d8+3", key="salvar_expressao", max_chars=LIMITE_TEXTO
        )
        if c3.form_submit_button("Salvar", icon=":material/bookmark_add:", width="stretch"):
            try:
                ler_rolagem(expressao)
            except ErroRolagem as erro:
                st.error(str(erro), icon=":material/error:")
            else:
                if nome.strip():
                    salvas[nome.strip()] = expressao
                else:
                    st.warning("Dê um nome a esta rolagem.", icon=":material/warning:")
    for i, (nome, expressao) in enumerate(salvas.items()):
        c1, c2 = st.columns([5, 1])
        if c1.button(f"{nome}: {expressao}", key=f"salva_{i}", width="stretch"):
            _rolar_e_guardar(expressao)
            st.rerun()
        if c2.button("Apagar", key=f"apagar_salva_{i}", icon=":material/delete:", width="stretch"):
            del salvas[nome]
            st.rerun()


def _grafico_distribuicao(
    d: Distribuicao,
    alvo: int | None,
    dominio: list[int] | None = None,
    teto: float | None = None,
):
    """A chance de cada total. As barras que atingem o alvo ficam na cor de destaque."""
    # Valores muito raros só encolheriam o desenho; o texto da página avisa que ficam de fora.
    linhas = [
        {
            "Total": v,
            "Chance": p,
            "Texto": _porcento(p),
            "Situação": "Atinge o alvo" if alvo is not None and v >= alvo else "Abaixo do alvo",
        }
        for v, p in d.probs.items()
        if p >= 0.0001
    ]
    eixo_x = alt.Axis(
        labelOverlap=True, labelAngle=0, grid=False, tickColor="#dccfb9", domainColor="#dccfb9"
    )
    escala_x = alt.Scale(domain=dominio) if dominio else alt.Undefined
    return (
        alt.Chart(alt.Data(values=linhas))
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("Total:O", title="Total", axis=eixo_x, scale=escala_x, sort="ascending"),
            y=alt.Y(
                "Chance:Q",
                title=None,
                scale=alt.Scale(domain=[0, teto]) if teto else alt.Undefined,
                axis=alt.Axis(
                    format=".0%", grid=True, gridColor="#ebe2d2", domain=False, ticks=False
                ),
            ),
            color=alt.Color(
                "Situação:N",
                scale=alt.Scale(
                    domain=["Atinge o alvo", "Abaixo do alvo"], range=["#b5452b", "#9a8a70"]
                ),
                legend=alt.Legend(orient="top", title=None) if alvo is not None else None,
            ),
            tooltip=[
                alt.Tooltip("Total:O"),
                alt.Tooltip("Texto:N", title="Chance"),
            ],
        )
        .properties(height=260, background="transparent")
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor="#6b5f50", titleColor="#6b5f50")
        .configure_legend(labelColor="#6b5f50")
    )


def _resumo_distribuicao(d: Distribuicao, alvo: int) -> None:
    m = st.columns(4)
    m[0].metric(f"Chance de {alvo} ou mais", _porcento(d.chance(">=", alvo)))
    m[1].metric("Média", _numero(d.media))
    m[2].metric("Mínimo e máximo", f"{d.minimo} a {d.maximo}")
    m[3].metric("Desvio padrão", _numero(d.desvio))
    maior = max(d.probs.values())
    empate = sum(abs(p - maior) < 1e-9 for p in d.probs.values()) > 1
    provavel = "Sem total mais provável (empate)" if empate else f"Mais provável: **{d.moda}**"
    st.caption(
        f"{provavel} · Metade das rolagens fica entre **{d.percentil(0.25)}** e "
        f"**{d.percentil(0.75)}** · 90% ficam até **{d.percentil(0.9)}**"
    )


def _origem_distribuicao(d: Distribuicao) -> str:
    if d.exata:
        return "Conta exata."
    return (
        f"Simulação de {d.simulacoes:,} rolagens".replace(",", ".")
        + ": esta regra não tem conta exata com pouco processamento, então os valores são "
        "aproximados, e o mínimo e o máximo são os que apareceram."
    )


def _guia_probabilidades() -> None:
    c1, c2 = st.columns([3, 1])
    expressao = c1.text_input("Rolagem", "1d20+5", key="prob_expressao", max_chars=LIMITE_TEXTO)
    alvo = int(
        c2.number_input("Alvo (dificuldade, defesa...)", -100000, 100000, 15, key="prob_alvo")
    )
    try:
        d = _distribuicao(expressao)
    except ErroRolagem as erro:
        st.error(str(erro), icon=":material/error:")
        return
    _resumo_distribuicao(d, alvo)
    st.altair_chart(_grafico_distribuicao(d, alvo), width="stretch")
    st.caption(
        _origem_distribuicao(d) + " O gráfico omite totais com chance abaixo de 0,01%; a tabela "
        "mostra todos."
    )
    with st.expander("Ver como tabela", icon=":material/table:"):
        acumulado = {v: d.chance(">=", v) for v in d.probs}
        st.dataframe(
            [
                {
                    "Total": v,
                    "Chance": _porcento(p),
                    "Chance deste total ou mais": _porcento(acumulado[v]),
                }
                for v, p in d.probs.items()
            ],
            hide_index=True,
            width="stretch",
        )


def _guia_comparar() -> None:
    st.caption("Qual é melhor: 2d6 ou 1d12? Com vantagem ou com +2? As duas contra o mesmo alvo.")
    c1, c2, c3 = st.columns([2, 2, 1])
    texto_a = c1.text_input("Rolagem A", "1d20+5", key="comparar_a", max_chars=LIMITE_TEXTO)
    texto_b = c2.text_input("Rolagem B", "vant+3", key="comparar_b", max_chars=LIMITE_TEXTO)
    alvo = int(c3.number_input("Alvo", -100000, 100000, 15, key="comparar_alvo"))
    try:
        a, b = _distribuicao(texto_a), _distribuicao(texto_b)
    except ErroRolagem as erro:
        st.error(str(erro), icon=":material/error:")
        return
    chance_a, chance_b = a.chance(">=", alvo), b.chance(">=", alvo)
    diferenca = abs(chance_a - chance_b)
    if diferenca < 0.0005:
        st.info(f"As duas têm a mesma chance de atingir {alvo}: {_porcento(chance_a)}.")
    else:
        melhor = texto_a if chance_a > chance_b else texto_b
        st.info(
            f"**{melhor}** tem mais chance de atingir {alvo}: "
            f"{_porcento(max(chance_a, chance_b))} contra {_porcento(min(chance_a, chance_b))}, "
            f"{_numero(diferenca * 100)} pontos percentuais a mais."
        )
    # Mesmas escalas nos dois desenhos, para o olho comparar sem conta.
    teto = max(max(a.probs.values()), max(b.probs.values()))
    valores = [v for d in (a, b) for v, p in d.probs.items() if p >= 0.0001]
    dominio = list(range(min(valores), max(valores) + 1))
    colunas = st.columns(2)
    for coluna, texto, d in ((colunas[0], texto_a, a), (colunas[1], texto_b, b)):
        with coluna:
            st.markdown(f"**{html.escape(texto)}**")
            st.altair_chart(_grafico_distribuicao(d, alvo, dominio, teto), width="stretch")
            m = st.columns(2)
            m[0].metric(f"Chance de {alvo} ou mais", _porcento(d.chance(">=", alvo)))
            m[1].metric("Média", _numero(d.media))
            st.caption(_origem_distribuicao(d))


def pagina_extras() -> None:
    st.title("Extras")
    st.markdown("Ferramentas de mesa que funcionam com qualquer sistema, com ou sem livro.")
    rolar_guia, prob_guia, comparar_guia = st.tabs(["Rolar dados", "Probabilidades", "Comparar"])
    with rolar_guia:
        _guia_rolar()
    with prob_guia:
        _guia_probabilidades()
    with comparar_guia:
        _guia_comparar()


def pagina_conteudo() -> None:
    st.title("Conteúdo e licenças")
    st.markdown(
        """
Este site e o repositório publicam **apenas conteúdo com licença aberta**.

**Livros que você envia:** o PDF é lido na memória do servidor e não é salvo. Para montar o
sistema, trechos selecionados vão ao LLM do Databricks (Foundation Model APIs). O que é extraído
(regras resumidas, nunca o texto do livro) fica na sua sessão e numa tabela privada do dono do
site, para o mesmo arquivo não ser lido de novo; nada disso é publicado aqui. Use livros que
você tem o direito de ler.

Este trabalho inclui material do *System Reference Document 5.1* da Wizards of the Coast LLC,
licenciado sob [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

As mecânicas de **Feiticeiros & Maldições** (Livro de Regras v2.5) são de Setsugiri, Parker
e equipe, num projeto de fãs gratuito inspirado em *Jujutsu Kaisen*, de Gege Akutami. O livro
permite usar o sistema como base com crédito aos autores. Aqui aparecem só fórmulas
resumidas, sem texto do livro.
"""
    )


livro = livro_atual()
paginas = [
    INICIO,
    *([RESUMO, GERADOR, FICHA, ANALISES] if livro else []),
    EXTRAS,
    BASTIDORES,
    ROTEIRO,
    CONTEUDO,
]  # fmt: skip
if "_pagina_pendente" in st.session_state:
    st.session_state.pagina = st.session_state.pop("_pagina_pendente")
if st.session_state.get("pagina") not in paginas:
    st.session_state.pagina = INICIO
st.sidebar.html('<div class="marca">Oráculo <span>do Mestre</span></div>')
if livro:
    st.sidebar.html(
        '<div class="livro-atual"><div class="rotulo">Livro em uso</div>'
        f'<div class="nome">{html.escape(livro["nome"])}</div>'
        f'<div class="sistema">{html.escape(nome_do_sistema(livro))}</div></div>'
    )
    st.sidebar.button(
        "Trocar de livro",
        icon=":material/swap_horiz:",
        on_click=_trocar_livro,
        width="stretch",
    )
else:
    st.sidebar.caption("Envie um livro no **Início** para liberar o gerador e as análises.")
st.sidebar.radio("Navegação", paginas, key="pagina")
st.sidebar.caption(
    f"Projeto de portfólio de ciência de dados · Python, Databricks e GitHub · "
    f"[código]({REPOSITORIO})"
)

{
    INICIO: pagina_inicio,
    RESUMO: pagina_resumo,
    GERADOR: pagina_gerador,
    FICHA: pagina_ficha,
    ANALISES: pagina_analises,
    BASTIDORES: pagina_bastidores,
    ROTEIRO: pagina_roteiro,
    EXTRAS: pagina_extras,
    CONTEUDO: pagina_conteudo,
}[st.session_state.pagina]()
