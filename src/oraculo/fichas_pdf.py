"""Ficha em PDF para os jogadores usarem na mesa, com a cara do sistema.

O tema vem do gênero do jogo (lido do livro): paleta, tipografia, ornamentos e a forma das caixas e
dos títulos. Nada da arte do livro é copiado. O fundo é sempre claro, para sair bem na impressão, e
vida e recursos têm espaço para anotar o valor atual a lápis. Usa as fontes embutidas de todo PDF,
que cobrem o português.

É a ficha que o jogador usa para jogar. Todo espaço de escrever também é um campo do PDF: dá para
imprimir e usar a lápis, ou digitar no leitor de PDF. A mesma estrutura serve à ficha gerada e à
ficha em branco: nesta, os valores vêm vazios, e `campos` e `blocos` dão espaço para preencher.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from fpdf import FPDF
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

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
    valor: str = ""  # vazio na ficha em branco
    anotar: bool = False  # vida, recursos: espaço para o valor atual
    marcado: bool = False  # nos blocos de marcar: perícia treinada, por exemplo


@dataclass
class BlocoImpresso:
    """Uma parte da ficha para preencher. tipo: "texto" (linhas para escrever, com um rótulo por
    item, se houver), "valores" (caixas com valor) ou "marcas" (lista de marcar, com bônus)."""

    titulo: str
    tipo: str = "texto"
    itens: list[ValorImpresso] = field(default_factory=list)
    linhas: int = 3


@dataclass
class _CampoForm:
    """Área da página que vira campo de digitar. Medidas em mm, a partir do topo da página."""

    nome: str
    pagina: int
    x: float
    y: float
    w: float
    h: float
    tamanho: float
    centro: bool = False
    multilinha: bool = False
    caixa: bool = False
    marcado: bool = False


@dataclass
class FichaImpressa:
    nome: str
    sistema: str
    subtitulo: str = ""
    # (sigla, valor, modificador). Na ficha em branco o valor é None, e um modificador diferente de
    # None só pede o espaço dele (ver atributo_em_branco).
    atributos: list[tuple[str, int | None, int | None]] = field(default_factory=list)
    valores: list[ValorImpresso] = field(default_factory=list)
    secoes: list[tuple[str, list[str]]] = field(default_factory=list)
    narrativa: dict[str, str] = field(default_factory=dict)
    credito: str = ""
    campos: list[str] = field(default_factory=list)  # rótulos de campos para escrever à mão
    blocos: list[BlocoImpresso] = field(default_factory=list)


def atributo_em_branco(sigla: str, com_modificador: bool) -> tuple[str, None, int | None]:
    return (sigla, None, 0 if com_modificador else None)


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
        self.formulario: list[_CampoForm] = []
        self.set_auto_page_break(True, margin=18)
        self.set_margins(16, 16, 16)
        self.set_title(texto_seguro(f"{ficha.nome or 'Ficha em branco'} - {ficha.sistema}"))
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

    def _losango(self, x: float, y: float, r: float) -> None:
        self.polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], style="F")

    def _chanfro(self, x: float, y: float, w: float, h: float, c: float, todos: bool) -> None:
        """Caixa de cantos cortados: os quatro, ou só dois opostos (cara de interface)."""
        se = [(x + c, y), (x, y + c)] if todos else [(x, y)]
        id_ = [(x + w - c, y + h), (x + w, y + h - c)] if todos else [(x + w, y + h)]
        sd = [(x + w - c, y), (x + w, y + c)]
        ie = [(x + c, y + h), (x, y + h - c)]
        self.polygon([*se[::-1], *sd, *id_[::-1], *ie], style="D")

    def _ornamento(self) -> None:
        t, w, h = self.tema, self.w, self.h
        primeira = self.page_no() == 1  # carimbos e selos ficam fora das páginas de continuação
        self.set_draw_color(*t.destaque)
        self.set_fill_color(*t.destaque)
        if t.ornamento == "moldura":  # moldura dupla com cantos em losango
            self.set_line_width(0.7)
            self.rect(7, 7, w - 14, h - 14)
            self.set_line_width(0.2)
            self.rect(8.6, 8.6, w - 17.2, h - 17.2)
            for x, y in ((7, 7), (w - 7, 7), (7, h - 7), (w - 7, h - 7)):
                self._losango(x, y, 2.4)
        elif t.ornamento == "dossie":  # pasta de arquivo: linha de margem e carimbo
            self.set_line_width(0.3)
            self.line(11, 0, 11, h)
            self.line(12.2, 0, 12.2, h)
            if primeira:
                self.set_line_width(0.5)
                self.circle(w - 28, 21, 9.5)
                self.set_line_width(0.2)
                self.circle(w - 28, 21, 8)
                with self.rotation(18, w - 28, 21):
                    self.set_font(t.fonte_titulo, "B", 8)
                    self.set_text_color(*t.destaque)
                    self.set_xy(w - 38, 19)
                    self.cell(20, 4, "FICHA", align="C")
        elif t.ornamento == "lamina":  # faixa no topo com ponta, como uma lâmina
            self.set_fill_color(*t.tinta)
            self.polygon([(0, 0), (w, 0), (w, 4), (w / 2, 9), (0, 4)], style="F")
            self.set_line_width(0.2)
            self.line(10, h - 9, w - 10, h - 9)
        elif t.ornamento == "selo":  # faixa lateral vermelha; o selo com a inicial vem no título
            self.rect(0, 0, 7, h, style="F")
            self.set_draw_color(*t.papel)
            self.set_line_width(0.3)
            self.line(5.5, 0, 5.5, h)
        elif t.ornamento == "colchetes":  # cantos de interface e marcas de régua
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
            for y in range(30, int(h) - 20, 10):
                self.line(6, y, 8 if y % 40 else 10, y)
                self.line(w - 6, y, w - (8 if y % 40 else 10), y)
        else:
            self.set_line_width(1.2)
            self.line(16, 11, w - 16, 11)

    def _ajustar(
        self, texto: str, largura: float, familia: str, estilo: str, tamanho: float
    ) -> str:
        """Escolhe a fonte para o texto caber numa linha: reduz até 5,5 pt e, depois, corta."""
        saida = texto_seguro(texto).strip()
        while tamanho > 5.5:
            self.set_font(familia, estilo, tamanho)
            if self.get_string_width(saida) <= largura:
                return saida
            tamanho -= 0.5
        self.set_font(familia, estilo, 5.5)
        while saida and self.get_string_width(saida + "...") > largura:
            saida = saida[:-1]
        return saida + "..."

    # ------------------------------------------------------------------ blocos
    def titulo(self) -> None:
        f, t = self.ficha, self.tema
        nome = f.nome or f.sistema
        partes = [f.subtitulo, f.sistema if f.nome else ""]
        linha = " · ".join(x for x in partes if x)
        tamanho = 26 if len(nome) <= 26 else 20 if len(nome) <= 44 else 16
        altura = tamanho * 0.42
        o = t.ornamento
        reserva = 28 if o in ("dossie", "selo") else 0
        largura = self.epw - reserva
        centralizado = o == "moldura"
        alinhamento = "C" if centralizado else "L"
        estilo_linha = "I" if o in ("moldura", "lamina") else ""

        if o == "lamina":  # o título sai em papel sobre a faixa escura
            self.set_font(t.fonte_titulo, "B", tamanho)
            n = len(
                self.multi_cell(largura, altura, texto_seguro(nome), dry_run=True, output="LINES")
            )
            self.set_font(t.fonte_corpo, estilo_linha, 10.5)
            m = len(
                self.multi_cell(largura, 5.2, texto_seguro(linha), dry_run=True, output="LINES")
            )
            fim = 11 + n * altura + m * 5.2
            self.set_fill_color(*t.tinta)
            self.polygon(
                [(0, 0), (self.w, 0), (self.w, fim), (self.w / 2, fim + 7), (0, fim)], style="F"
            )
            self.set_draw_color(*t.destaque)
            self.set_line_width(1)
            self.line(0, fim, self.w / 2, fim + 7)
            self.line(self.w / 2, fim + 7, self.w, fim)
            self.set_y(9)
            self.set_text_color(*t.papel)
        else:
            self.set_text_color(*t.tinta)
        if o == "selo":
            self._selo()
        if o == "colchetes":
            self.set_fill_color(*t.destaque)
            self.rect(self.l_margin - 4, self.get_y() + 1, 1.6, altura - 1, style="F")

        self.set_font(t.fonte_titulo, "B", tamanho)
        self.multi_cell(
            largura, altura, texto_seguro(nome), align=alinhamento, new_x="LMARGIN", new_y="NEXT"
        )
        self.set_font(t.fonte_corpo, estilo_linha, 10.5)
        self.set_text_color(*(t.papel if o == "lamina" else t.destaque))
        self.multi_cell(
            largura, 5.2, texto_seguro(linha), align=alinhamento, new_x="LMARGIN", new_y="NEXT"
        )

        if o == "lamina":
            self.set_y(fim + 10)
            return
        y = self.get_y() + 2
        self.set_draw_color(*t.destaque)
        if o == "moldura":  # divisor com losango no meio
            meio = self.w / 2
            self.set_line_width(0.3)
            self.line(meio - 50, y, meio - 4, y)
            self.line(meio + 4, y, meio + 50, y)
            self.set_fill_color(*t.destaque)
            self._losango(meio, y, 1.8)
        elif o == "dossie":  # linha tracejada de formulário
            self.set_line_width(0.3)
            self.set_dash_pattern(dash=1.5, gap=1)
            self.line(self.l_margin, y, self.l_margin + largura, y)
            self.set_dash_pattern()
        elif o == "selo":  # traço curto e grosso
            self.set_line_width(1.1)
            self.line(self.l_margin, y, self.l_margin + 22, y)
        elif o == "colchetes":
            self.set_line_width(0.3)
            self.line(self.l_margin, y, self.l_margin + self.epw, y)
        self.set_y(y + 4)

    def _selo(self) -> None:
        t = self.tema
        x, y = self.w - 28, 22
        self.set_fill_color(*t.destaque)
        self.circle(x, y, 10, style="F")
        self.set_draw_color(*t.papel)
        self.set_line_width(0.5)
        self.circle(x, y, 8)
        inicial = next((c for c in texto_seguro(self.ficha.sistema) if c.isalnum()), "")
        self.set_font(t.fonte_titulo, "B", 18)
        self.set_text_color(*t.papel)
        self.set_xy(x - 10, y - 4.5)
        self.cell(20, 9, inicial.upper(), align="C")
        self.set_xy(self.l_margin, 16)
        self.set_text_color(*t.tinta)

    def campos(self) -> None:
        """Campos de escrever, em duas colunas: nome, jogador, classe, nível..."""
        f, t = self.ficha, self.tema
        if not f.campos:
            return
        vao = 6
        largura = (self.epw - vao) / 2
        for i, rotulo in enumerate(f.campos):
            if i % 2 == 0:
                self._garantir(10)
                y = self.get_y()
            x = self.l_margin + (i % 2) * (largura + vao)
            self._campo(rotulo, x, y, largura, 5.2, tamanho=10)
            texto = self._ajustar(rotulo, largura, t.fonte_corpo, "", 7.5)
            self.set_text_color(*t.destaque)
            self.set_xy(x, y + 5.5)
            self.cell(largura, 3.5, texto)
            self.set_draw_color(*t.tinta)
            self.set_line_width(0.25)
            self.line(x, y + 5.3, x + largura, y + 5.3)
            if i % 2 == 1 or i == len(f.campos) - 1:
                self.set_xy(self.l_margin, y + 10.5)
        self.ln(3.5)

    def _caixa(self, x: float, y: float, w: float, h: float, rotulo: str, centro: bool) -> None:
        """A caixa e o rótulo dela: a forma é o que mais muda de um tema para outro."""
        t = self.tema
        o = t.ornamento
        self.set_draw_color(*t.suave)
        self.set_line_width(0.3)
        cor_rotulo = t.tinta
        if o == "moldura":
            self.set_draw_color(*t.destaque)
            self._chanfro(x, y, w, h, 2.2, todos=True)
        elif o == "dossie":  # formulário: rótulo em tarja cinza
            self.set_fill_color(*t.suave)
            self.rect(x, y, w, 5, style="F")
            self.set_draw_color(*t.tinta)
            self.rect(x, y, w, h)
        elif o == "lamina":  # tampa escura com o rótulo em papel
            self.set_fill_color(*t.tinta)
            self.rect(x, y, w, 5, style="F")
            self.set_draw_color(*t.tinta)
            self.rect(x, y, w, h)
            cor_rotulo = t.papel
        elif o == "selo":  # traço vermelho em cima
            self.rect(x, y, w, h)
            self.set_fill_color(*t.destaque)
            self.rect(x, y, w, 1, style="F")
        elif o == "colchetes":  # dois cantos cortados e um traço na cor do tema
            self.set_draw_color(*t.destaque)
            self._chanfro(x, y, w, h, 2.5, todos=False)
            self.set_line_width(0.8)
            self.line(x + 3.2, y + h - 0.6, x + w * 0.45, y + h - 0.6)
        else:
            self.rect(x, y, w, h, round_corners=True, corner_radius=1.4)
        folga = 1.5
        texto = self._ajustar(rotulo, w - 2 * folga, t.fonte_corpo, "B" if centro else "", 7.5)
        self.set_text_color(*cor_rotulo)
        self.set_xy(x + folga, y + 0.6 if o in ("dossie", "lamina") else y + 1.4)
        self.cell(w - 2 * folga, 4, texto, align="C" if centro else "L")

    def atributos(self) -> None:
        f, t = self.ficha, self.tema
        if not f.atributos:
            return
        n = len(f.atributos)
        por_linha = max(n, 4) if n <= 9 else min(9, (n + 1) // 2)
        vao = 1.5
        largura = (self.epw - vao * (por_linha - 1)) / por_linha
        com_mod = any(m is not None for _, _, m in f.atributos)
        em_branco = all(v is None for _, v, _ in f.atributos)
        altura = (24 if com_mod else 19) if em_branco else (20 if com_mod else 16)
        for i in range(0, n, por_linha):
            self._garantir(altura + vao)
            y = self.get_y()
            for j, (sigla, valor, mod) in enumerate(f.atributos[i : i + por_linha]):
                x = self.l_margin + j * (largura + vao)
                self._caixa(x, y, largura, altura, sigla, centro=True)
                if valor is not None:
                    self.set_xy(x, y + 5.6)
                    self.set_text_color(*t.tinta)
                    self.set_font(t.fonte_titulo, "B", 15)
                    self.cell(largura, 7, str(valor), align="C")
                    if mod is not None:
                        self.set_xy(x, y + 13)
                        self.set_font(t.fonte_corpo, size=9)
                        self.set_text_color(*t.destaque)
                        self.cell(largura, 5, f"{mod:+d}", align="C")
                else:
                    fim = y + altura - (8 if mod is not None else 1)
                    self._campo(sigla, x + 1, y + 5.5, largura - 2, fim - y - 5.5, 14, centro=True)
                    if mod is not None:  # espaço do modificador, para escrever
                        self.set_draw_color(*t.suave)
                        self.set_line_width(0.25)
                        meio = x + largura / 2
                        self.line(meio - 4, y + altura - 2.6, meio + 4, y + altura - 2.6)
                        self._campo(
                            f"mod {sigla}", meio - 4, y + altura - 7, 8, 4.4, 9, centro=True
                        )
            self.set_xy(self.l_margin, y + altura + vao)
        self.ln(2.5)

    def valores(self) -> None:
        self._grade_valores(self.ficha.valores)

    def _grade_valores(self, itens: list[ValorImpresso]) -> None:
        t = self.tema
        if not itens:
            return
        por_linha = 4
        vao = 1.5
        largura = (self.epw - vao * (por_linha - 1)) / por_linha
        altura = 18
        for i in range(0, len(itens), por_linha):
            self._garantir(altura + vao)
            y = self.get_y()
            for j, v in enumerate(itens[i : i + por_linha]):
                x = self.l_margin + j * (largura + vao)
                self._caixa(x, y, largura, altura, v.nome, centro=False)
                if v.valor:
                    valor = self._ajustar(v.valor, largura - 3, t.fonte_titulo, "B", 14)
                    self.set_xy(x + 1.5, y + 5.5)
                    self.set_text_color(*t.tinta)
                    self.cell(largura - 3, 7, valor)
                elif not v.anotar:
                    self._campo(v.nome, x + 1.5, y + 6, largura - 3, 10.5, 14)
                if v.anotar:  # máximo (se ainda não há valor) e atual, para escrever
                    if not v.valor:
                        self._linha_anotada("Máximo:", v.nome, x, y + 7.2, largura)
                    self._linha_anotada("Atual:", v.nome, x, y + 12.2, largura)
            self.set_xy(self.l_margin, y + altura + vao)
        self.ln(2.5)

    def _linha_anotada(self, rotulo: str, nome: str, x: float, y: float, largura: float) -> None:
        t = self.tema
        self.set_font(t.fonte_corpo, size=7)
        self.set_text_color(*t.destaque)
        self.set_xy(x + 1.5, y)
        self.cell(10, 4, rotulo)
        self.set_draw_color(*t.suave)
        self.set_line_width(0.2)
        self.line(x + 12.5, y + 3.2, x + largura - 3, y + 3.2)
        self._campo(f"{nome} {rotulo}", x + 12.5, y - 0.3, largura - 15.5, 3.5, 8)

    def _campo(
        self,
        nome: str,
        x: float,
        y: float,
        w: float,
        h: float,
        tamanho: float = 10,
        *,
        centro: bool = False,
        multilinha: bool = False,
    ) -> None:
        """Marca uma área como campo de digitar no PDF (ver _com_formulario)."""
        self.formulario.append(
            _CampoForm(nome, self.page_no(), x, y, w, h, tamanho, centro, multilinha)
        )

    def _marca(self, nome: str, x: float, y: float, lado: float, marcado: bool) -> None:
        self.set_draw_color(*self.tema.tinta)
        self.set_line_width(0.25)
        self.rect(x, y, lado, lado)
        self.formulario.append(
            _CampoForm(nome, self.page_no(), x, y, lado, lado, 0, caixa=True, marcado=marcado)
        )

    def _garantir(self, altura: float) -> None:
        if self.get_y() + altura > self.page_break_trigger:
            self.add_page()

    def _titulo_secao(self, titulo: str) -> None:
        t = self.tema
        o = t.ornamento
        texto = texto_seguro(titulo)
        self._garantir(14)
        x, y, w = self.l_margin, self.get_y(), self.epw
        self.set_font(t.fonte_titulo, "B", 11.5)
        largura = self.get_string_width(texto)
        self.set_x(x)
        if o == "moldura":  # centrado entre fios, com losangos
            self.set_text_color(*t.destaque)
            self.cell(w, 6.5, texto, align="C", new_x="LMARGIN", new_y="NEXT")
            meio = y + 3.25
            esquerda, direita = x + (w - largura) / 2 - 3, x + (w + largura) / 2 + 3
            self.set_draw_color(*t.destaque)
            self.set_line_width(0.25)
            self.line(x, meio, esquerda - 2, meio)
            self.line(direita + 2, meio, x + w, meio)
            self.set_fill_color(*t.destaque)
            self._losango(esquerda, meio, 1)
            self._losango(direita, meio, 1)
            self.ln(1)
        elif o == "dossie":  # aba de pasta, e o fio segue até o fim da linha
            self.set_fill_color(*t.tinta)
            self.polygon(
                [(x, y + 6.5), (x, y), (x + largura + 6, y), (x + largura + 9, y + 6.5)], style="F"
            )
            self.set_draw_color(*t.tinta)
            self.set_line_width(0.5)
            self.line(x, y + 6.5, x + w, y + 6.5)
            self.set_text_color(*t.papel)
            self.set_x(x + 2)
            self.cell(largura + 4, 6.5, texto, new_x="LMARGIN", new_y="NEXT")
            self.ln(1.5)
        elif o == "lamina":  # faixa cheia na cor do sangue
            self.set_fill_color(*t.destaque)
            self.rect(x, y, w, 6.5, style="F")
            self.set_text_color(*t.papel)
            self.set_x(x + 2.5)
            self.cell(w - 5, 6.5, texto, new_x="LMARGIN", new_y="NEXT")
            self.ln(1.5)
        elif o == "selo":  # quadrado vermelho e fio fino
            self.set_fill_color(*t.destaque)
            self.rect(x, y + 1, 3.6, 3.6, style="F")
            self.set_text_color(*t.tinta)
            self.set_x(x + 5.5)
            self.cell(w - 5.5, 6, texto, new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*t.suave)
            self.set_line_width(0.3)
            self.line(x, y + 6.5, x + w, y + 6.5)
            self.ln(1.5)
        elif o == "colchetes":  # linha de terminal, com um bloco no fim do fio
            self.set_text_color(*t.destaque)
            self.cell(w, 6, f"// {texto}", new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*t.destaque)
            self.set_fill_color(*t.destaque)
            self.set_line_width(0.3)
            self.line(x, y + 6.3, x + w, y + 6.3)
            self.rect(x + w - 6, y + 5.5, 6, 0.9, style="F")
            self.ln(1.5)
        else:
            self.set_text_color(*t.destaque)
            self.cell(w, 6, texto, new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*t.destaque)
            self.set_line_width(0.3)
            self.line(x, y + 6, x + w, y + 6)
            self.ln(1.5)

    def secao(self, titulo: str, linhas: list[str]) -> None:
        t = self.tema
        self._titulo_secao(titulo)
        self.set_text_color(*t.tinta)
        for linha in linhas:
            texto = texto_seguro(linha)
            rotulo, separador, resto = texto.partition(": ")
            self.set_x(self.l_margin)
            if separador and 0 < len(rotulo) <= 40:  # "Nome: efeito", com o nome em negrito
                self.set_font(t.fonte_corpo, "B", 9.5)
                self.write(4.8, f"{rotulo}: ")
                self.set_font(t.fonte_corpo, size=9.5)
                self.write(4.8, resto)
            else:
                self.set_font(t.fonte_corpo, size=9.5)
                self.write(4.8, texto)
            self.ln(5.6)
        self.ln(2.5)

    def bloco(self, b: BlocoImpresso) -> None:
        if b.tipo == "valores":
            self._garantir(9 + 18)
            self._titulo_secao(b.titulo)
            self._grade_valores(b.itens)
        elif b.tipo == "marcas":
            self._bloco_marcas(b)
        else:
            self._bloco_texto(b)

    def _pautas(self, nome: str, linhas: int) -> None:
        t = self.tema
        self.set_draw_color(*t.suave)
        self.set_line_width(0.2)
        y = self.get_y()
        for i in range(1, linhas + 1):
            self.line(self.l_margin, y + i * 7, self.l_margin + self.epw, y + i * 7)
        self._campo(nome, self.l_margin, y + 0.5, self.epw, linhas * 7, 10, multilinha=True)
        self.set_y(y + linhas * 7 + 3)

    def _bloco_texto(self, b: BlocoImpresso) -> None:
        """Espaço para escrever, com um rótulo por item, se houver. Não se parte entre páginas."""
        t = self.tema
        linhas = b.linhas or 3
        if not b.itens:
            self._garantir(9 + linhas * 7)
            self._titulo_secao(b.titulo)
            self._pautas(b.titulo, linhas)
            return
        self._garantir(9 + 4 + linhas * 7)
        self._titulo_secao(b.titulo)
        for item in b.itens:
            self._garantir(4 + linhas * 7 + 3)
            self.set_x(self.l_margin)
            texto = self._ajustar(item.nome, self.epw, t.fonte_corpo, "B", 8.5)
            self.set_text_color(*t.destaque)
            self.cell(self.epw, 4, texto, new_x="LMARGIN", new_y="NEXT")
            self._pautas(f"{b.titulo} {item.nome}", linhas)

    def _bloco_marcas(self, b: BlocoImpresso) -> None:
        """Lista para marcar (treinado ou não), com espaço para o bônus, em três colunas."""
        t = self.tema
        colunas = 3
        vao = 4
        largura = (self.epw - vao * (colunas - 1)) / colunas
        altura = 5.6
        por_coluna = (len(b.itens) + colunas - 1) // colunas
        self._garantir(9 + min(por_coluna, 12) * altura)
        self._titulo_secao(b.titulo)
        for linha in range(por_coluna):
            self._garantir(altura)
            y = self.get_y()
            for col in range(colunas):
                indice = col * por_coluna + linha
                if indice >= len(b.itens):
                    continue
                item = b.itens[indice]
                x = self.l_margin + col * (largura + vao)
                self._marca(item.nome, x, y + 1, 3.2, item.marcado)
                texto = self._ajustar(item.nome, largura - 15, t.fonte_corpo, "", 8.5)
                self.set_text_color(*t.tinta)
                self.set_xy(x + 3.8, y + 0.6)
                self.cell(largura - 14, 4, texto)
                self.set_draw_color(*t.suave)
                self.set_line_width(0.2)
                self.line(x + largura - 9, y + 4.4, x + largura, y + 4.4)
                self._campo(
                    f"{item.nome} bônus", x + largura - 9, y + 0.6, 9, 3.8, 8.5, centro=True
                )
            self.set_xy(self.l_margin, y + altura)
        self.ln(3.5)

    def anotacoes(self) -> None:
        t = self.tema
        self._garantir(40)
        self._titulo_secao("Anotações")
        self.set_draw_color(*t.suave)
        self.set_line_width(0.2)
        inicio = self.get_y()
        y = inicio + 6
        while y < self.page_break_trigger - 2:
            self.line(self.l_margin, y, self.l_margin + self.epw, y)
            y += 7
        self._campo(
            "Anotações",
            self.l_margin,
            inicio,
            self.epw,
            y - 7 - inicio,
            10,
            multilinha=True,
        )


def _com_formulario(
    pdf: bytes, altura_pagina: float, campos: list[_CampoForm], tema: Tema
) -> bytes:
    """Acrescenta os campos de digitar: a ficha serve impressa ou preenchida no leitor de PDF.

    O fundo do campo é transparente, para o tema continuar aparecendo por baixo."""
    k = 72 / 25.4
    saida = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    nome_fonte = {"Helvetica": "Helv", "Times": "TiRo", "Courier": "Cour"}[tema.fonte_corpo]
    base = {"Helvetica": "Helvetica", "Times": "Times-Roman", "Courier": "Courier"}[
        tema.fonte_corpo
    ]
    fonte = saida._add_object(
        DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject(f"/{base}"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        })
    )  # fmt: skip
    cor = " ".join(f"{c / 255:.3f}" for c in tema.tinta)
    campos_pdf = ArrayObject()
    usados: dict[str, int] = {}
    for c in campos:
        base_nome = re.sub(r"[^\w ]", "", texto_seguro(c.nome)).strip() or "campo"
        usados[base_nome] = usados.get(base_nome, 0) + 1
        nome = base_nome if usados[base_nome] == 1 else f"{base_nome} {usados[base_nome]}"
        pagina = saida.pages[c.pagina - 1]
        x0, y0 = c.x * k, (altura_pagina - c.y - c.h) * k
        x1, y1 = (c.x + c.w) * k, (altura_pagina - c.y) * k
        widget = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/T"): TextStringObject(nome),
            NameObject("/F"): NumberObject(4),
            NameObject("/P"): pagina.indirect_reference,
            NameObject("/Rect"): ArrayObject([FloatObject(round(v, 2)) for v in (x0, y0, x1, y1)]),
        })  # fmt: skip
        if c.caixa:
            lado = x1 - x0
            valor = NameObject("/Sim" if c.marcado else "/Off")
            widget.update({
                NameObject("/FT"): NameObject("/Btn"),
                NameObject("/V"): valor,
                NameObject("/AS"): valor,
                NameObject("/AP"): DictionaryObject({NameObject("/N"): DictionaryObject({
                    NameObject("/Sim"): _aparencia(saida, lado, cor, True),
                    NameObject("/Off"): _aparencia(saida, lado, cor, False),
                })}),
            })  # fmt: skip
        else:
            bandeiras = 4096 if c.multilinha else 0
            widget.update({
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/Ff"): NumberObject(bandeiras),
                NameObject("/Q"): NumberObject(1 if c.centro else 0),
                NameObject("/DA"): TextStringObject(f"/{nome_fonte} {c.tamanho:g} Tf {cor} rg"),
            })  # fmt: skip
        ref = saida._add_object(widget)
        if "/Annots" not in pagina:
            pagina[NameObject("/Annots")] = ArrayObject()
        pagina["/Annots"].append(ref)
        campos_pdf.append(ref)
    saida._root_object[NameObject("/AcroForm")] = saida._add_object(
        DictionaryObject({
            NameObject("/Fields"): campos_pdf,
            NameObject("/NeedAppearances"): BooleanObject(True),
            NameObject("/DA"): TextStringObject(f"/{nome_fonte} 10 Tf {cor} rg"),
            NameObject("/DR"): DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject(f"/{nome_fonte}"): fonte})
            }),
        })
    )  # fmt: skip
    buffer = io.BytesIO()
    saida.write(buffer)
    return buffer.getvalue()


def _aparencia(saida: PdfWriter, lado: float, cor: str, marcada: bool):
    """Como a caixa de marcar aparece: um X na cor do tema, ou vazia."""
    desenho = ""
    if marcada:
        a, b = lado * 0.2, lado * 0.8
        desenho = (
            f"q {cor} RG 1.2 w {a:.2f} {a:.2f} m {b:.2f} {b:.2f} l "
            f"{a:.2f} {b:.2f} m {b:.2f} {a:.2f} l S Q"
        )
    fluxo = DecodedStreamObject()
    fluxo.set_data(desenho.encode())
    fluxo.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([FloatObject(v) for v in (0, 0, lado, lado)]),
    })  # fmt: skip
    return saida._add_object(fluxo)


def gerar_pdf(ficha: FichaImpressa, tema: Tema) -> bytes:
    pdf = _Pdf(ficha, tema)
    pdf.add_page()
    pdf.titulo()
    pdf.campos()
    pdf.atributos()
    pdf.valores()
    for bloco in ficha.blocos:
        pdf.bloco(bloco)
    for titulo, linhas in ficha.secoes:
        cheias = [linha for linha in linhas if linha.strip()]
        if cheias:
            pdf.secao(titulo, cheias)
    if ficha.narrativa:
        pdf.secao(
            "Quem é esta pessoa (sugestão)",
            [f"{rotulo}: {texto}" for rotulo, texto in ficha.narrativa.items()],
        )
    pdf.anotacoes()
    return _com_formulario(bytes(pdf.output()), pdf.h, pdf.formulario, tema)
