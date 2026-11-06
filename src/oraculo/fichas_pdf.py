"""Ficha em PDF para os jogadores usarem na mesa, com a cara do sistema.

O tema vem do gênero do jogo (lido do livro): paleta, tipografia e ornamentos. Nada da arte do
livro é copiado. O fundo é sempre claro, para sair bem na impressão, e vida e recursos têm espaço
para anotar o valor atual a lápis. Usa as fontes embutidas de todo PDF, que cobrem o português.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from fpdf import FPDF

Cor = tuple[int, int, int]


@dataclass(frozen=True)
class Tema:
    id: str
    papel: Cor
    tinta: Cor
    destaque: Cor
    suave: Cor  # linhas e caixas
    fonte_titulo: str
    fonte_corpo: str
    ornamento: str


TEMAS = {
    "fantasia": Tema("fantasia", (250, 245, 232), (46, 33, 22), (122, 31, 36), (205, 188, 155),
                     "Times", "Times", "moldura"),
    "horror": Tema("horror", (244, 240, 230), (38, 36, 32), (74, 92, 74), (190, 184, 168),
                   "Courier", "Times", "dossie"),
    "gotico": Tema("gotico", (247, 243, 240), (30, 20, 22), (130, 16, 30), (205, 190, 190),
                   "Times", "Helvetica", "lamina"),
    "oriental": Tema("oriental", (252, 250, 245), (28, 28, 30), (190, 40, 30), (214, 208, 196),
                     "Helvetica", "Helvetica", "selo"),
    "scifi": Tema("scifi", (245, 248, 250), (20, 34, 48), (0, 112, 140), (182, 200, 210),
                  "Courier", "Helvetica", "colchetes"),
    "padrao": Tema("padrao", (252, 251, 248), (34, 30, 26), (150, 70, 40), (210, 202, 188),
                   "Helvetica", "Helvetica", "linha"),
}  # fmt: skip

# A ordem importa: a primeira palavra encontrada no gênero decide.
PALAVRAS_TEMA = (
    ("gotico", ("vampir", "gótic", "gotic", "sangue", "vampire", "gothic")),
    ("horror", ("horror", "terror", "cósmic", "cosmic", "investiga", "sobrenatural", "maldi")),
    ("oriental", ("ninja", "samurai", "shinobi", "oriental", "wuxia", "japon", "anime", "mangá")),
    ("scifi", ("ficção", "sci-fi", "scifi", "cyber", "futur", "espaç", "space", "mecha", "robô")),
    ("fantasia", ("fantasia", "fantasy", "medieval", "épic", "epic", "espada", "dragão")),
)


def tema_para(*textos: str) -> Tema:
    """O tema pelo gênero e nome do jogo, em palavras que o próprio livro usa."""
    texto = " ".join(textos).lower()
    for tema, palavras in PALAVRAS_TEMA:
        if any(p in texto for p in palavras):
            return TEMAS[tema]
    return TEMAS["padrao"]


@dataclass
class ValorImpresso:
    nome: str
    valor: str
    anotar: bool = False  # vida, recursos: espaço para o valor atual


@dataclass
class FichaImpressa:
    nome: str
    sistema: str
    subtitulo: str = ""
    atributos: list[tuple[str, int, int | None]] = field(default_factory=list)
    valores: list[ValorImpresso] = field(default_factory=list)
    secoes: list[tuple[str, list[str]]] = field(default_factory=list)
    narrativa: dict[str, str] = field(default_factory=dict)
    credito: str = ""


_TROCAS = {
    "—": "-", "–": "-", "‑": "-", "−": "-", "→": "->", "≥": ">=", "≤": "<=", "“": '"', "”": '"',
    "‘": "'", "’": "'", "…": "...", "•": "-", " ": " ", "÷": "/",
}  # fmt: skip


def texto_seguro(texto: object) -> str:
    """As fontes embutidas cobrem latin-1 (todo o português): troca o resto por equivalentes."""
    saida = re.sub(r"[^\S\n]", " ", str(texto))  # todo espaço Unicode vira espaço comum
    for velho, novo in _TROCAS.items():
        saida = saida.replace(velho, novo)
    return saida.encode("latin-1", "replace").decode("latin-1")


class _Pdf(FPDF):
    def __init__(self, ficha: FichaImpressa, tema: Tema) -> None:
        super().__init__(format="A4")
        self.ficha, self.tema = ficha, tema
        self.set_auto_page_break(True, margin=18)
        self.set_margins(16, 16, 16)
        self.set_title(texto_seguro(f"{ficha.nome} - {ficha.sistema}"))
        self.set_creator("Oráculo do Mestre")

    def header(self) -> None:
        t = self.tema
        self.set_fill_color(*t.papel)
        self.rect(0, 0, self.w, self.h, style="F")
        self._ornamento()
        self.set_y(16)

    def footer(self) -> None:
        self.set_y(-13)
        self.set_font(self.tema.fonte_corpo, size=7.5)
        self.set_text_color(*self.tema.tinta)
        credito = self.ficha.credito or self.ficha.sistema
        self.cell(0, 4, texto_seguro(f"{credito} · Oráculo do Mestre"), align="L")
        self.cell(0, 4, str(self.page_no()), align="R")

    def _ornamento(self) -> None:
        t, w, h = self.tema, self.w, self.h
        self.set_draw_color(*t.destaque)
        self.set_fill_color(*t.destaque)
        if t.ornamento == "moldura":  # moldura dupla com cantos em losango
            self.set_line_width(0.7)
            self.rect(7, 7, w - 14, h - 14)
            self.set_line_width(0.2)
            self.rect(8.6, 8.6, w - 17.2, h - 17.2)
            for x, y in ((7, 7), (w - 7, 7), (7, h - 7), (w - 7, h - 7)):
                self.polygon([(x, y - 2.4), (x + 2.4, y), (x, y + 2.4), (x - 2.4, y)], style="F")
        elif t.ornamento == "dossie":  # pasta de arquivo: linha de margem e carimbo
            self.set_line_width(0.3)
            self.line(11, 0, 11, h)
            self.set_line_width(0.5)
            self.circle(w - 24, 12, 8.5)
            self.set_line_width(0.2)
            self.circle(w - 24, 12, 7)
            self.line(w - 29, 16, w - 19, 8)
        elif t.ornamento == "lamina":  # faixa no topo com ponta, como uma lâmina
            self.polygon([(0, 0), (w, 0), (w, 4), (w / 2, 9), (0, 4)], style="F")
            self.set_line_width(0.2)
            self.line(10, h - 9, w - 10, h - 9)
        elif t.ornamento == "selo":  # faixa lateral vermelha e selo redondo
            self.rect(0, 0, 7, h, style="F")
            self.circle(w - 24, 18, 8, style="F")
            self.set_draw_color(*t.papel)
            self.set_line_width(0.5)
            self.circle(w - 24, 18, 6)
        elif t.ornamento == "colchetes":  # cantos de interface e grade fina
            self.set_line_width(0.6)
            for x, y, dx, dy in (
                (6, 6, 1, 1),
                (w - 6, 6, -1, 1),
                (6, h - 6, 1, -1),
                (w - 6, h - 6, -1, -1),
            ):
                self.line(x, y, x + 12 * dx, y)
                self.line(x, y, x, y + 12 * dy)
            self.set_draw_color(*t.suave)
            self.set_line_width(0.1)
            for y in range(30, int(h) - 20, 40):
                self.line(6, y, 9, y)
                self.line(w - 9, y, w - 6, y)
        else:
            self.set_line_width(1.2)
            self.line(16, 11, w - 16, 11)

    # ------------------------------------------------------------------ blocos
    def titulo(self) -> None:
        f, t = self.ficha, self.tema
        self.set_text_color(*t.tinta)
        self.set_font(t.fonte_titulo, "B", 24)
        largura = self.epw - (22 if t.ornamento in ("dossie", "selo") else 0)
        self.multi_cell(largura, 10, texto_seguro(f.nome), new_x="LMARGIN", new_y="NEXT")
        self.set_font(t.fonte_corpo, size=10.5)
        self.set_text_color(*t.destaque)
        linha = " · ".join(x for x in (f.subtitulo, f.sistema) if x)
        self.multi_cell(largura, 5.2, texto_seguro(linha), new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def _caixa(self, x: float, y: float, w: float, h: float) -> None:
        self.set_draw_color(*self.tema.suave)
        self.set_line_width(0.3)
        self.rect(x, y, w, h)

    def atributos(self) -> None:
        f, t = self.ficha, self.tema
        if not f.atributos:
            return
        por_linha = 9 if len(f.atributos) > 6 else 6
        largura = self.epw / por_linha
        altura = 19 if any(m is not None for _, _, m in f.atributos) else 15
        for i in range(0, len(f.atributos), por_linha):
            self._garantir(altura + 2)
            y = self.get_y()
            for j, (sigla, valor, mod) in enumerate(f.atributos[i : i + por_linha]):
                x = self.l_margin + j * largura
                self._caixa(x, y, largura, altura)
                self.set_xy(x, y + 1.2)
                self.set_text_color(*t.tinta)
                self.set_font(t.fonte_corpo, "B", 7.5)
                self.cell(largura, 4, texto_seguro(sigla)[:12], align="C")
                self.set_xy(x, y + 5.2)
                self.set_font(t.fonte_titulo, "B", 15)
                self.cell(largura, 7, str(valor), align="C")
                if mod is not None:
                    self.set_xy(x, y + 12.6)
                    self.set_font(t.fonte_corpo, size=9)
                    self.set_text_color(*t.destaque)
                    self.cell(largura, 5, f"{mod:+d}", align="C")
            self.set_xy(self.l_margin, y + altura + 2)
        self.ln(2)

    def valores(self) -> None:
        f, t = self.ficha, self.tema
        if not f.valores:
            return
        por_linha = 4
        largura = self.epw / por_linha
        altura = 17
        for i in range(0, len(f.valores), por_linha):
            self._garantir(altura + 2)
            y = self.get_y()
            for j, v in enumerate(f.valores[i : i + por_linha]):
                x = self.l_margin + j * largura
                self._caixa(x, y, largura, altura)
                self.set_xy(x + 1.5, y + 1.2)
                self.set_text_color(*t.tinta)
                self.set_font(t.fonte_corpo, size=7.5)
                self.cell(largura - 3, 4, texto_seguro(v.nome)[:30])
                self.set_xy(x + 1.5, y + 5.5)
                self.set_font(t.fonte_titulo, "B", 14)
                self.cell(largura - 3, 7, texto_seguro(v.valor))
                if v.anotar:  # espaço para o valor atual, a lápis
                    self.set_xy(x + 1.5, y + 12)
                    self.set_font(t.fonte_corpo, size=7)
                    self.set_text_color(*t.destaque)
                    self.cell(10, 4, "Atual:")
                    self.set_draw_color(*t.suave)
                    self.line(x + 11, y + 15.2, x + largura - 3, y + 15.2)
            self.set_xy(self.l_margin, y + altura + 2)
        self.ln(2)

    def _garantir(self, altura: float) -> None:
        if self.get_y() + altura > self.page_break_trigger:
            self.add_page()

    def secao(self, titulo: str, linhas: list[str]) -> None:
        t = self.tema
        self._garantir(14)
        self.set_font(t.fonte_titulo, "B", 11.5)
        self.set_text_color(*t.destaque)
        self.cell(0, 6, texto_seguro(titulo), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*t.destaque)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.l_margin + self.epw, self.get_y())
        self.ln(1.5)
        self.set_font(t.fonte_corpo, size=9.5)
        self.set_text_color(*t.tinta)
        for linha in linhas:
            self.multi_cell(0, 4.8, texto_seguro(linha), new_x="LMARGIN", new_y="NEXT")
            self.ln(0.8)
        self.ln(2.5)

    def anotacoes(self) -> None:
        t = self.tema
        self._garantir(40)
        self.set_font(t.fonte_titulo, "B", 11.5)
        self.set_text_color(*t.destaque)
        self.cell(0, 6, "Anotações", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*t.suave)
        self.set_line_width(0.2)
        y = self.get_y() + 6
        while y < self.page_break_trigger - 2:
            self.line(self.l_margin, y, self.l_margin + self.epw, y)
            y += 7


def gerar_pdf(ficha: FichaImpressa, tema: Tema) -> bytes:
    pdf = _Pdf(ficha, tema)
    pdf.add_page()
    pdf.titulo()
    pdf.atributos()
    pdf.valores()
    for titulo, linhas in ficha.secoes:
        if linhas:
            pdf.secao(titulo, linhas)
    if ficha.narrativa:
        pdf.secao(
            "Quem é esta pessoa (sugestão)",
            [f"{rotulo}: {texto}" for rotulo, texto in ficha.narrativa.items()],
        )
    pdf.anotacoes()
    return bytes(pdf.output())
