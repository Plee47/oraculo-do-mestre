"""O site no Streamlit Cloud instala só o requirements.txt (o pacote vem de src/)."""

import re
from pathlib import Path

RAIZ = Path(__file__).parents[1]


def _nome(requisito: str) -> str:
    return re.split(r"[<>=!~\[ ]", requisito.strip(), maxsplit=1)[0].lower()


def test_requirements_contem_as_dependencias_do_pacote():
    pyproject = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    bloco = re.search(r"^dependencies = \[(.*?)\]", pyproject, re.MULTILINE | re.DOTALL).group(1)
    do_pacote = {_nome(d) for d in re.findall(r'"([^"]+)"', bloco)}

    linhas = (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
    do_site = {_nome(linha) for linha in linhas if linha.strip() and not linha.startswith("#")}

    assert do_pacote <= do_site, f"faltam no requirements.txt: {do_pacote - do_site}"


def test_site_importa_o_codigo_de_src():
    app = (RAIZ / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))' in app
