"""Deploy completo no Databricks: código no volume + Asset Bundle.

Uso:  python scripts/deploy.py            (target dev)
      python scripts/deploy.py -t prod    (usado pelo CI)
      python scripts/deploy.py --run      (deploy e roda o pipeline)

Por que o código vai para um volume: no compute serverless, ler arquivos `.py` da pasta do
workspace falhou de forma intermitente (Errno 5). Volumes do Unity Catalog usam outro
armazenamento e funcionaram de forma estável. Ver docs/decisoes/0004-codigo-em-volume.md.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CLI = os.environ.get("DATABRICKS_CLI", "databricks")


def databricks(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    print("$ databricks", " ".join(args), flush=True)
    return subprocess.run(
        [CLI, *args], cwd=RAIZ, check=check, text=True, capture_output=True, encoding="utf-8"
    )


def variaveis_do_bundle(target: str) -> dict[str, str]:
    saida = databricks("bundle", "validate", "-t", target, "-o", "json").stdout
    config = json.loads(saida)
    return {nome: v.get("value", v.get("default")) for nome, v in config["variables"].items()}


def garantir_schema_e_volume(catalogo: str, schema: str) -> None:
    r = databricks(
        "schemas", "create", schema, catalogo, "--comment", "Oráculo do Mestre", check=False
    )
    if r.returncode and "already exists" not in (r.stderr + r.stdout).lower():
        sys.exit(r.stderr)
    r = databricks(
        "volumes", "create", catalogo, schema, "codigo", "MANAGED",
        "--comment", "Pacote Python do projeto (código, não dados)", check=False,
    )  # fmt: skip
    if r.returncode and "already exists" not in (r.stderr + r.stdout).lower():
        sys.exit(r.stderr)


def enviar_codigo(catalogo: str, schema: str) -> None:
    destino = f"dbfs:/Volumes/{catalogo}/{schema}/codigo/src"
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / "src"
        shutil.copytree(
            RAIZ / "src", copia, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
        )
        databricks("fs", "rm", "-r", destino, check=False)
        databricks("fs", "cp", "-r", str(copia), destino, "--overwrite")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-t", "--target", default="dev")
    parser.add_argument("--run", action="store_true", help="roda o pipeline após o deploy")
    args = parser.parse_args()

    v = variaveis_do_bundle(args.target)
    garantir_schema_e_volume(v["catalogo"], v["schema"])
    enviar_codigo(v["catalogo"], v["schema"])
    print(databricks("bundle", "deploy", "-t", args.target).stderr)
    if args.run:
        r = databricks("bundle", "run", "-t", args.target, "oraculo_pipeline", check=False)
        print(r.stdout[-3000:], r.stderr[-3000:])
        return r.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
