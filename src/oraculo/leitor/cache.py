"""Cache das leituras de livros numa tabela Delta privada do Databricks (ADR 0008).

Guarda só o que foi extraído (especificação do sistema, detalhes de opções, vetores de busca),
nunca o texto do livro. A chave é o hash do texto do livro + a parte lida + a versão dos
prompts: mudar um prompt invalida o que foi lido com a versão antiga.

O cache é um acelerador: qualquer falha (warehouse desligado, permissão) vira aviso e a leitura
segue sem ele. `CacheMemoria` serve para testes e para rodar sem Databricks.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

TABELA = "leitor_cache"
_RE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def hash_livro(paginas: list[str]) -> str:
    return hashlib.sha256("\n\f".join(paginas).encode()).hexdigest()


class CacheLeituras(Protocol):
    def ler(self, livro: str, parte: str, chave: str, versao: str) -> str | None: ...
    def gravar(self, livro: str, parte: str, chave: str, versao: str, conteudo: str) -> None: ...


@dataclass
class CacheMemoria:
    dados: dict[tuple[str, str, str, str], str] = field(default_factory=dict)

    def ler(self, livro: str, parte: str, chave: str, versao: str) -> str | None:
        return self.dados.get((livro, parte, chave, versao))

    def gravar(self, livro: str, parte: str, chave: str, versao: str, conteudo: str) -> None:
        self.dados[(livro, parte, chave, versao)] = conteudo


@dataclass
class CacheDatabricks:
    """Tabela `<catalogo>.<schema>.leitor_cache` via API de instruções SQL do Databricks."""

    host: str
    token: str
    catalogo: str = "workspace"
    schema: str = "oraculo_dev"
    warehouse_id: str = ""
    avisos: list[str] = field(default_factory=list)
    _pronto: bool = False

    def __post_init__(self) -> None:
        for nome in (self.catalogo, self.schema):
            if not _RE_IDENT.match(nome):
                raise ValueError(f"identificador inválido: {nome!r}")
        self.host = self.host.rstrip("/")

    @property
    def tabela(self) -> str:
        return f"`{self.catalogo}`.`{self.schema}`.`{TABELA}`"

    # ------------------------------------------------------------------ HTTP
    def _api(self, metodo: str, caminho: str, corpo: dict | None = None) -> dict:
        pedido = urllib.request.Request(
            f"{self.host}{caminho}",
            data=json.dumps(corpo).encode() if corpo is not None else None,
            method=metodo,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(pedido, timeout=120) as r:
            return json.loads(r.read().decode())

    def _warehouse(self) -> str:
        if not self.warehouse_id:
            lista = self._api("GET", "/api/2.0/sql/warehouses").get("warehouses", [])
            if not lista:
                raise RuntimeError("nenhum SQL warehouse no workspace")
            ligado = [w for w in lista if w.get("state") == "RUNNING"]
            self.warehouse_id = (ligado or lista)[0]["id"]
        return self.warehouse_id

    def _sql(self, instrucao: str, parametros: Mapping[str, str] | None = None) -> list[list]:
        corpo = {
            "warehouse_id": self._warehouse(),
            "statement": instrucao,
            "wait_timeout": "50s",
            "parameters": [
                {"name": k, "value": v, "type": "STRING"} for k, v in (parametros or {}).items()
            ],
        }
        r = self._api("POST", "/api/2.0/sql/statements", corpo)
        limite = time.time() + 120  # warehouse desligado pode levar alguns segundos para subir
        while r["status"]["state"] in ("PENDING", "RUNNING") and time.time() < limite:
            time.sleep(2)
            r = self._api("GET", f"/api/2.0/sql/statements/{r['statement_id']}")
        if r["status"]["state"] != "SUCCEEDED":
            erro = r["status"].get("error", {}).get("message", r["status"]["state"])
            raise RuntimeError(erro)
        return r.get("result", {}).get("data_array", []) or []

    def _garantir_tabela(self) -> None:
        if self._pronto:
            return
        self._sql(
            f"CREATE TABLE IF NOT EXISTS {self.tabela} (livro STRING, parte STRING, "
            "chave STRING, versao STRING, conteudo STRING, atualizado_em TIMESTAMP) "
            "COMMENT 'Oráculo: leituras de livros (só regras extraídas, nunca o texto)'"
        )
        self._pronto = True

    # ------------------------------------------------------------------ interface
    def ler(self, livro: str, parte: str, chave: str, versao: str) -> str | None:
        try:
            self._garantir_tabela()
            linhas = self._sql(
                f"SELECT conteudo FROM {self.tabela} WHERE livro = :livro AND parte = :parte "
                "AND chave = :chave AND versao = :versao ORDER BY atualizado_em DESC LIMIT 1",
                {"livro": livro, "parte": parte, "chave": chave, "versao": versao},
            )
        except (urllib.error.URLError, RuntimeError, KeyError, ValueError, TimeoutError) as e:
            self.avisos.append(f"cache indisponível ({e})")
            return None
        return linhas[0][0] if linhas else None

    def gravar(self, livro: str, parte: str, chave: str, versao: str, conteudo: str) -> None:
        try:
            self._garantir_tabela()
            self._sql(
                f"MERGE INTO {self.tabela} t USING (SELECT :livro AS livro, :parte AS parte, "
                ":chave AS chave, :versao AS versao, :conteudo AS conteudo) s "
                "ON t.livro = s.livro AND t.parte = s.parte AND t.chave = s.chave "
                "AND t.versao = s.versao "
                "WHEN MATCHED THEN UPDATE SET conteudo = s.conteudo, "
                "atualizado_em = current_timestamp() "
                "WHEN NOT MATCHED THEN INSERT (livro, parte, chave, versao, conteudo, "
                "atualizado_em) VALUES (s.livro, s.parte, s.chave, s.versao, s.conteudo, "
                "current_timestamp())",
                {"livro": livro, "parte": parte, "chave": chave, "versao": versao,
                 "conteudo": conteudo},
            )  # fmt: skip
        except (urllib.error.URLError, RuntimeError, KeyError, ValueError, TimeoutError) as e:
            self.avisos.append(f"cache indisponível ({e})")


def cache_configurado(segredos: Mapping | None = None) -> CacheDatabricks | None:
    import os

    fontes: list[Mapping] = [segredos or {}, os.environ]

    def valor(chave: str, padrao: str = "") -> str:
        return next((str(f[chave]) for f in fontes if f.get(chave)), padrao)

    host, token = valor("DATABRICKS_HOST"), valor("DATABRICKS_TOKEN")
    if not host or not token:
        return None
    return CacheDatabricks(
        host if host.startswith("http") else "https://" + host,
        token,
        catalogo=valor("ORACULO_CATALOGO", "workspace"),
        schema=valor("ORACULO_SCHEMA", "oraculo_dev"),
        warehouse_id=valor("DATABRICKS_WAREHOUSE_ID"),
    )
