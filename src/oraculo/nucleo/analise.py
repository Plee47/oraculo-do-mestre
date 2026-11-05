"""Formato comum dos achados das análises (vale para qualquer sistema)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Severidade = Literal["alerta", "atencao", "info", "ok"]
ORDEM_SEVERIDADE = {"alerta": 0, "atencao": 1, "info": 2, "ok": 3}


class Achado(BaseModel):
    """Uma dica do Oráculo. Sempre diz qual regra a gerou (`regra`)."""

    severidade: Severidade
    categoria: str
    titulo: str
    detalhe: str
    regra: str
    sugestao: str | None = None


def ordenar(achados: list[Achado]) -> list[Achado]:
    return sorted(achados, key=lambda a: ORDEM_SEVERIDADE[a.severidade])
