"""Cliente mínimo para os LLMs do Databricks (Foundation Model APIs, formato de chat).

Usado pelo site para ler um livro enviado na hora. Só biblioteca padrão: o site não ganha
dependência nova. Credenciais vêm de `DATABRICKS_HOST` e `DATABRICKS_TOKEN` (segredos do
Streamlit ou variáveis de ambiente) e nunca são versionadas.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

MODELO_PADRAO = "databricks-gpt-oss-120b"  # o melhor na avaliação do leitor (ADR 0005)


class ErroLLM(RuntimeError):
    """Falha ao falar com o LLM (rede, cota, credencial)."""


class ClienteLLM(Protocol):
    def completar(self, sistema: str, usuario: str, max_tokens: int = 6000) -> str: ...


def _texto_da_resposta(dados: dict) -> str:
    try:
        conteudo = dados["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ErroLLM("resposta do LLM sem conteúdo") from e
    if isinstance(conteudo, list):  # alguns modelos devolvem partes (raciocínio + texto)
        conteudo = "".join(
            p.get("text", "") for p in conteudo if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(conteudo or "")


@dataclass
class ClienteDatabricks:
    host: str
    token: str
    modelo: str = MODELO_PADRAO
    timeout: float = 240.0
    tentativas: int = 3

    def completar(self, sistema: str, usuario: str, max_tokens: int = 6000) -> str:
        url = f"{self.host.rstrip('/')}/serving-endpoints/{self.modelo}/invocations"
        corpo = json.dumps(
            {
                "messages": [
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": usuario},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.0,
            }
        ).encode()
        ultimo = ""
        for tentativa in range(self.tentativas):
            pedido = urllib.request.Request(
                url,
                data=corpo,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(pedido, timeout=self.timeout) as r:
                    return _texto_da_resposta(json.loads(r.read().decode()))
            except urllib.error.HTTPError as e:
                ultimo = f"HTTP {e.code}"
                if e.code in (401, 403):
                    raise ErroLLM("credencial do Databricks recusada (token inválido?)") from e
                if e.code not in (429, 500, 502, 503, 504):
                    raise ErroLLM(f"o LLM recusou o pedido ({ultimo})") from e
            except (urllib.error.URLError, TimeoutError) as e:
                ultimo = str(getattr(e, "reason", e))
            time.sleep(2 * (tentativa + 1))
        raise ErroLLM(f"o LLM não respondeu depois de {self.tentativas} tentativas ({ultimo})")


def cliente_configurado(segredos: Mapping | None = None) -> ClienteDatabricks | None:
    """Cliente a partir dos segredos (site) ou do ambiente (local). None se faltar algo."""
    fontes: list[Mapping] = [segredos or {}, os.environ]
    valores = {}
    for chave in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "MODELO_LEITOR"):
        valores[chave] = next((str(f[chave]) for f in fontes if f.get(chave)), "")
    if not valores["DATABRICKS_HOST"] or not valores["DATABRICKS_TOKEN"]:
        return None
    host = valores["DATABRICKS_HOST"]
    if not host.startswith("http"):
        host = "https://" + host
    return ClienteDatabricks(
        host, valores["DATABRICKS_TOKEN"], valores["MODELO_LEITOR"] or MODELO_PADRAO
    )
