"""Cliente mínimo para as Foundation Model APIs do Databricks (chat e embeddings).

Usado pelo site para ler um livro enviado na hora. Só biblioteca padrão: o site não ganha
dependência nova. Credenciais vêm de `DATABRICKS_HOST` e `DATABRICKS_TOKEN` (segredos do
Streamlit ou variáveis de ambiente) e nunca são versionadas.

Dois modelos de chat: o grande para extrair regras (o melhor da avaliação, ADR 0005) e um
pequeno para tarefas simples (classificar, listar), que custam menos cota.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

MODELO_PADRAO = "databricks-gpt-oss-120b"  # extração de regras (ADR 0005)
MODELO_PEQUENO = "databricks-gpt-oss-20b"  # tarefas simples: menos cota, mais rápido
MODELO_EMBEDDINGS = "databricks-qwen3-embedding-0-6b"
LOTE_EMBEDDINGS = 16  # lotes maiores estouram o limite de vazão do plano gratuito
CARACTERES_EMBEDDING = 1200  # início de cada página: título e assunto
MAX_SIMULTANEOS = 2  # pedidos ao mesmo tempo: o plano gratuito recusa rajadas (HTTP 429)
_vagas = threading.BoundedSemaphore(MAX_SIMULTANEOS)


class ErroLLM(RuntimeError):
    """Falha ao falar com o LLM (rede, cota, credencial)."""


class ClienteLLM(Protocol):
    def completar(
        self, sistema: str, usuario: str, max_tokens: int = 6000, pequeno: bool = False
    ) -> str: ...


def espera(codigo: int | None, tentativa: int, retry_after: str | None = None) -> float:
    """Segundos até a próxima tentativa. O limite do plano gratuito (429) é por minuto, então
    ele pede mais paciência que uma falha passageira."""
    if codigo == 429:
        try:
            return min(90.0, float(retry_after))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return (10.0, 20.0, 40.0, 60.0)[min(tentativa, 3)]
    return 2.0 * (tentativa + 1)


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
    modelo_pequeno: str = MODELO_PEQUENO
    modelo_embeddings: str = MODELO_EMBEDDINGS
    timeout: float = 240.0
    tentativas: int = 6

    def _post(self, endpoint: str, corpo: dict) -> dict:
        url = f"{self.host.rstrip('/')}/serving-endpoints/{endpoint}/invocations"
        dados = json.dumps(corpo).encode()
        ultimo, motivo = "", ""
        for tentativa in range(self.tentativas):
            codigo, retry_after = None, None
            pedido = urllib.request.Request(
                url,
                data=dados,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with _vagas, urllib.request.urlopen(pedido, timeout=self.timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                ultimo = f"HTTP {e.code}"
                motivo = e.read()[:300].decode(errors="replace") if e.fp else ""
                codigo, retry_after = e.code, e.headers.get("Retry-After") if e.headers else None
                if e.code in (401, 403):
                    raise ErroLLM("credencial do Databricks recusada (token inválido?)") from e
                if e.code not in (429, 500, 502, 503, 504):
                    raise ErroLLM(f"o LLM recusou o pedido ({ultimo})") from e
            except (urllib.error.URLError, TimeoutError) as e:
                ultimo = str(getattr(e, "reason", e))
            if tentativa < self.tentativas - 1:
                time.sleep(espera(codigo, tentativa, retry_after))
        if ultimo == "HTTP 429":
            raise ErroLLM(
                "o limite de uso do LLM do Databricks foi atingido; tente de novo em alguns "
                f"minutos ({motivo})"
            )
        raise ErroLLM(f"o LLM não respondeu depois de {self.tentativas} tentativas ({ultimo})")

    def completar(
        self, sistema: str, usuario: str, max_tokens: int = 6000, pequeno: bool = False
    ) -> str:
        corpo = {
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        modelo = self.modelo_pequeno if pequeno else self.modelo
        return _texto_da_resposta(self._post(modelo, corpo))

    def embutir(self, textos: list[str]) -> list[list[float]]:
        """Vetores dos textos, em lotes pequenos (limite de vazão do plano gratuito)."""
        vetores: list[list[float]] = []
        for i in range(0, len(textos), LOTE_EMBEDDINGS):
            lote = [(t or ".")[:CARACTERES_EMBEDDING] for t in textos[i : i + LOTE_EMBEDDINGS]]
            dados = self._post(self.modelo_embeddings, {"input": lote})
            try:
                ordenados = sorted(dados["data"], key=lambda d: d["index"])
                vetores += [d["embedding"] for d in ordenados]
            except (KeyError, TypeError) as e:
                raise ErroLLM("resposta de embeddings inesperada") from e
        return vetores


def _valor(fontes: list[Mapping], chave: str) -> str:
    return next((str(f[chave]) for f in fontes if f.get(chave)), "")


def cliente_configurado(segredos: Mapping | None = None) -> ClienteDatabricks | None:
    """Cliente a partir dos segredos (site) ou do ambiente (local). None se faltar algo."""
    fontes: list[Mapping] = [segredos or {}, os.environ]
    host, token = _valor(fontes, "DATABRICKS_HOST"), _valor(fontes, "DATABRICKS_TOKEN")
    if not host or not token:
        return None
    if not host.startswith("http"):
        host = "https://" + host
    return ClienteDatabricks(
        host,
        token,
        modelo=_valor(fontes, "MODELO_LEITOR") or MODELO_PADRAO,
        modelo_pequeno=_valor(fontes, "MODELO_LEITOR_PEQUENO") or MODELO_PEQUENO,
    )
