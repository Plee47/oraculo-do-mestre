"""Oráculo do Mestre — vitrine pública (Streamlit Community Cloud)."""

from __future__ import annotations

import sys
from pathlib import Path

# Usa sempre o código do repositório (src/), nunca um pacote `oraculo` instalado antes.
# O Streamlit Cloud reaproveita o ambiente entre deploys; sem isto, o site rodaria uma
# versão antiga do pacote depois de cada atualização.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st

from oraculo.nucleo import Ficha, obter_regras
from oraculo.nucleo.analise import Achado
from oraculo.sistemas.dnd5e import ATRIBUTOS, custo_compra_pontos, modificador
from oraculo.sistemas.dnd5e.analise import TIPOS_PT, analisar_encontro, analisar_grupo, perfil
from oraculo.sistemas.dnd5e.catalogo import Catalogo
from oraculo.sistemas.dnd5e.gerador import PAPEIS, calcular_ca, gerar_ficha

st.set_page_config(page_title="Oráculo do Mestre", page_icon="🔮", layout="wide")

CATALOGO_DND5E = Path(__file__).parents[1] / "dados" / "publicos" / "dnd5e" / "catalogo.json"
PAGINAS = (
    "Início",
    "Gerador de fichas (D&D 5e)",
    "Análise de grupo e encontro (D&D 5e)",
    "Ficha rápida (D&D 5e)",
    "Roteiro",
    "Conteúdo e licenças",
)


@st.cache_resource
def catalogo_dnd5e() -> Catalogo:
    return Catalogo.carregar(CATALOGO_DND5E)


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
| 3 · Leitor de livros | Detector "é livro de RPG?" + extração com LLM avaliada no MLflow | ⏳ |
| 4 · Feiticeiros & Maldições | Segundo sistema, extraído pelo leitor | ⏳ |
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
"""
    )


{
    "Início": pagina_inicio,
    "Gerador de fichas (D&D 5e)": pagina_gerador,
    "Análise de grupo e encontro (D&D 5e)": pagina_analise,
    "Ficha rápida (D&D 5e)": pagina_ficha,
    "Roteiro": pagina_roteiro,
    "Conteúdo e licenças": pagina_conteudo,
}[pagina]()
