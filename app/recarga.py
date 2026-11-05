"""Recarrega o pacote `oraculo` quando o código ou os dados mudam no servidor.

O Streamlit Cloud atualiza os arquivos a cada push, mas não reinicia o processo Python: os
módulos de `src/` já importados ficam na memória na versão antiga (o Streamlit só recarrega o
que está na pasta do app). Misturar módulo novo com módulo antigo quebra o site com
ImportError. Aqui comparamos uma "impressão digital" dos arquivos a cada execução do script e,
se mudou, descartamos os módulos do pacote para que sejam importados de novo.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

_ATRIBUTO = "_oraculo_impressao_digital"


def impressao_digital(pastas: Iterable[Path]) -> tuple:
    arquivos = []
    for pasta in pastas:
        for arq in sorted(pasta.rglob("*")):
            if arq.suffix in {".py", ".yaml", ".json"} and arq.is_file():
                info = arq.stat()
                arquivos.append((str(arq), info.st_mtime_ns, info.st_size))
    return tuple(arquivos)


def recarregar_se_mudou(pastas: Iterable[Path], pacote: str = "oraculo") -> bool:
    """Descarta os módulos de `pacote` se os arquivos mudaram desde a última execução.

    Retorna True quando houve recarga (o chamador deve limpar os caches do Streamlit).
    """
    atual = impressao_digital(pastas)
    anterior = getattr(sys, _ATRIBUTO, None)
    setattr(sys, _ATRIBUTO, atual)
    if anterior is None or anterior == atual:
        return False
    for nome in [n for n in sys.modules if n == pacote or n.startswith(pacote + ".")]:
        del sys.modules[nome]
    return True
