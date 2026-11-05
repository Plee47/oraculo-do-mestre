"""Atalho para rodar o guardião de conteúdo sem instalar o pacote (usado pelo pre-commit)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oraculo.guardiao import main  # noqa: E402

raise SystemExit(main())
