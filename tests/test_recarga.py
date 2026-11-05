"""Reproduz o bug do site: módulo novo importando módulo antigo que ficou na memória."""

import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))

from recarga import _ATRIBUTO, recarregar_se_mudou  # noqa: E402


@pytest.fixture
def pacote_temporario(tmp_path, monkeypatch):
    src = tmp_path / "src"
    (src / "pkgx").mkdir(parents=True)
    (src / "pkgx" / "__init__.py").write_text("", encoding="utf-8")
    (src / "pkgx" / "catalogo.py").write_text("class Catalogo: ...\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(src))
    monkeypatch.delattr(sys, _ATRIBUTO, raising=False)
    yield src
    for nome in [n for n in sys.modules if n.startswith("pkgx")]:
        del sys.modules[nome]


def _atualizar(arquivo: Path, conteudo: str) -> None:
    arquivo.write_text(conteudo, encoding="utf-8")
    t = arquivo.stat().st_mtime_ns + 10_000_000  # garante mtime diferente
    os.utime(arquivo, ns=(t, t))
    importlib.invalidate_caches()


def test_sem_recarga_o_modulo_antigo_quebra_o_import(pacote_temporario):
    importlib.import_module("pkgx.catalogo")
    _atualizar(
        pacote_temporario / "pkgx" / "catalogo.py", "class Catalogo: ...\nclass Monstro: ...\n"
    )
    (pacote_temporario / "pkgx" / "analise.py").write_text(
        "from pkgx.catalogo import Monstro\n", encoding="utf-8"
    )
    importlib.invalidate_caches()
    with pytest.raises(ImportError):  # o mesmo erro do site
        importlib.import_module("pkgx.analise")


def test_com_recarga_o_import_funciona(pacote_temporario):
    assert recarregar_se_mudou([pacote_temporario], "pkgx") is False  # 1ª execução
    importlib.import_module("pkgx.catalogo")
    assert recarregar_se_mudou([pacote_temporario], "pkgx") is False  # nada mudou

    _atualizar(
        pacote_temporario / "pkgx" / "catalogo.py", "class Catalogo: ...\nclass Monstro: ...\n"
    )
    (pacote_temporario / "pkgx" / "analise.py").write_text(
        "from pkgx.catalogo import Monstro\n", encoding="utf-8"
    )
    assert recarregar_se_mudou([pacote_temporario], "pkgx") is True
    assert "pkgx.catalogo" not in sys.modules
    assert importlib.import_module("pkgx.analise").Monstro
