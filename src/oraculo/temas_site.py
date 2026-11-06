"""O visual do site de acordo com o livro em uso (opcional; o padrão é o grimório).

Os temas são os mesmos das fichas em PDF (`oraculo.fichas_pdf`), adaptados para a tela. O tema do
Streamlit (.streamlit/config.toml) vale para o servidor inteiro, então mudá-lo afetaria todos os
visitantes. Por isso cada tema é uma folha de estilo enviada só à sessão de quem escolheu o livro:
`app/temas/base.css` traz o que todo tema sobrepõe, e `app/temas/<tema>.css` as cores (variáveis em
`:root`, a única fonte delas), as fontes e os ornamentos do tema.

A troca é coberta por uma "capa" que se abre em duas folhas. Ela só usa `transform` e `opacity`,
não bloqueia cliques e, para quem pede menos movimento no sistema, vira um esmaecer curto.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import quote

GRIMORIO = "grimorio"
# Os temas de PDF com visual próprio no site. O tema "padrao" é o neutro dos gêneros que não
# reconhecemos: no site, ele fica no grimório, a identidade padrão.
TEMAS_DO_SITE = ("fantasia", "horror", "gotico", "oriental", "scifi")
_RE_IMPORT = re.compile(r'@import\s+url\("[^"]*"\);\s*')  # o endereço das fontes tem ";"
_RE_RAIZ = re.compile(r":root\s*\{(.*?)\}", re.S)
_RE_VARIAVEL = re.compile(r"--([\w-]+)\s*:\s*([^;]+);")
# Um d20 visto de frente: hexágono, triângulo central e arestas. O site limpa <svg> do HTML, então
# ele vai como imagem no CSS, já com a animação do traço. Sem a animação, o dado aparece pronto.
_D20 = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 220' fill='none' stroke='{cor}' "
    "stroke-width='2' stroke-linejoin='round'><style>"
    "path{{stroke-dasharray:1000;animation:t 760ms cubic-bezier(.23,1,.32,1) both}}"
    "path+path{{animation-delay:140ms}}path+path+path{{animation-delay:260ms}}"
    "@keyframes t{{from{{stroke-dashoffset:1000}}to{{stroke-dashoffset:0}}}}"
    "@media (prefers-reduced-motion:reduce){{path{{animation:none}}}}"
    "</style><path d='M100 10 178 55V165L100 210 22 165V55Z'/><path d='M100 62 148 146H52Z'/>"
    "<path d='M100 10V62M178 55 100 62M22 55 100 62M178 55 148 146M22 55 52 146"
    "M178 165 148 146M22 165 52 146M100 210 148 146M100 210 52 146'/></svg>"
)


def tema_do_site(tema_do_livro: str | None, ligado: bool) -> str:
    """O tema a usar. Sem livro, com a opção desligada ou em gênero neutro: o grimório."""
    if ligado and tema_do_livro in TEMAS_DO_SITE:
        return tema_do_livro
    return GRIMORIO


def tokens_do_tema(pasta: Path, tema: str) -> dict[str, str]:
    """As variáveis de cor e fonte do tema, lidas do próprio CSS."""
    achado = _RE_RAIZ.search((pasta / f"{tema}.css").read_text(encoding="utf-8"))
    if not achado:
        raise ValueError(f"o tema {tema} não define :root")
    return {nome: valor.strip() for nome, valor in _RE_VARIAVEL.findall(achado.group(1))}


def css_do_tema(pasta: Path, tema: str, sistema: str = "") -> str:
    """A folha de estilo do tema. O grimório não precisa de nada além do estilo normal do site."""
    if tema == GRIMORIO:
        return ""
    proprio = (pasta / f"{tema}.css").read_text(encoding="utf-8")
    base = (pasta / "base.css").read_text(encoding="utf-8")
    inicial = next((c.upper() for c in sistema if c.isalnum()), "O")
    # O @import precisa vir antes de qualquer regra, e o resto do tema depois da base, para vencer
    # as regras dela de mesma força.
    fontes = "".join(_RE_IMPORT.findall(proprio))
    resto = _RE_IMPORT.sub("", proprio)
    return f'{fontes}\n{base}\n{resto}\n:root {{ --inicial: "{inicial}"; }}\n'


def cortina_html(titulo: str, contador: int, cor: str = "#e0c07a") -> str:
    """A capa que cobre a troca de tema. O contador muda o HTML, e só isso reinicia a animação:
    nas outras execuções da página o texto é igual e ela não toca de novo."""
    if contador == 0:
        return '<div class="sem-cortina"></div>'
    imagem = quote(_D20.format(cor=cor), safe="/:=' ")
    return (
        f'<style>.cortina .d20 {{ background-image: url("data:image/svg+xml,{imagem}"); }}</style>'
        f'<div class="cortina" data-troca="{contador}" aria-hidden="true">'
        '<div class="folha esquerda"></div><div class="folha direita"></div>'
        f'<div class="selo"><div class="d20"></div><div class="titulo">{html.escape(titulo)}</div>'
        "</div></div>"
    )
