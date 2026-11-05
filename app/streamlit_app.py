"""Oráculo do Mestre — vitrine pública (Streamlit Community Cloud)."""

from __future__ import annotations

import streamlit as st

from oraculo.nucleo import Ficha, obter_regras
from oraculo.sistemas.dnd5e import ATRIBUTOS, custo_compra_pontos

st.set_page_config(page_title="Oráculo do Mestre", page_icon="🔮", layout="wide")

PAGINAS = ("Início", "Ficha rápida (D&D 5e)", "Roteiro", "Conteúdo e licenças")
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
- **Gerador de fichas:** cria personagens e NPCs válidos pelas regras do sistema.
- **Análise:** encontra fraquezas do grupo e desequilíbrios nos encontros, sempre explicando
  *qual regra* gerou a dica.

Sistemas: **D&D 5ª edição** (SRD) e **Feiticeiros & Maldições** (em breve).
"""
    )
    st.info("Em construção: experimente a **Ficha rápida** no menu ao lado.", icon="🛠️")


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
| 1 · D&D SRD | Pipeline no Databricks com o SRD → tabelas gold → gerador de fichas | ⏳ |
| 2 · Análises | Fraquezas do grupo, desequilíbrio de encontros, dicas explicáveis | ⏳ |
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
    "Ficha rápida (D&D 5e)": pagina_ficha,
    "Roteiro": pagina_roteiro,
    "Conteúdo e licenças": pagina_conteudo,
}[pagina]()
