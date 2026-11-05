# Databricks notebook source
# MAGIC %md
# MAGIC # 20 · Leitor — porteiro
# MAGIC
# MAGIC Lê todos os PDFs de duas pastas e decide quais seguem para o LLM:
# MAGIC
# MAGIC | Pasta | Conteúdo | Pode ser exportado? |
# MAGIC |---|---|---|
# MAGIC | `livros_abertos/leitor/` | livros de licença aberta (ex.: SRD 5.1) | sim |
# MAGIC | `livros_privados/` | **seus** livros, enviados por você pela interface do Catalog | **nunca** |
# MAGIC
# MAGIC O porteiro (`oraculo.leitor.porteiro`) usa o detector `champion`: só passam livros de RPG
# MAGIC de sistemas suportados. Resultado em `leitor_livros` (decisão por livro) e
# MAGIC `bronze_leitor_paginas` (texto dos livros aceitos).

# COMMAND ----------

# MAGIC %pip install -q "pypdf>=4"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import shutil
import sys
from pathlib import Path

import pandas as pd
from pyspark.sql import functions as F

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
sys.path.insert(0, f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src")

from oraculo.leitor.corpus import paginas_de_pdf
from oraculo.leitor.detector import ModeloDetector
from oraculo.leitor.porteiro import decidir

ALVO = f"`{CATALOGO}`.`{SCHEMA}`"
BASE = Path(f"/Volumes/{CATALOGO}/{SCHEMA}")
PASTAS = {BASE / "livros_abertos" / "leitor": False, BASE / "livros_privados": True}

# COMMAND ----------

# O SRD 5.1 é o livro de referência da avaliação: copia do corpus do detector se faltar.
pasta_aberta = BASE / "livros_abertos" / "leitor"
pasta_aberta.mkdir(parents=True, exist_ok=True)
srd = pasta_aberta / "srd51.pdf"
if not srd.exists():
    shutil.copy(BASE / "livros_abertos" / "corpus_detector" / "srd51.pdf", srd)

modelo = ModeloDetector.carregar(BASE / "exportacao" / "modelos" / "detector_rpg.json")

# COMMAND ----------

livros, paginas = [], []
for pasta, privado in PASTAS.items():
    for pdf in sorted(pasta.glob("*.pdf")):
        textos = paginas_de_pdf(pdf)
        d = decidir(modelo, textos)
        livros.append(
            {
                "livro": pdf.stem,
                "privado": privado,
                "aceito": d.aceito,
                "motivo": d.motivo,
                "nota_rpg": float(d.veredito.nota),
                "sistema": d.veredito.sistema or "",
                "paginas": len(textos),
            }
        )
        if d.aceito:
            paginas += [
                {"livro": pdf.stem, "privado": privado, "pagina": i + 1, "texto": t}
                for i, t in enumerate(textos)
            ]
        print(f"{'✔' if d.aceito else '✘'} {pdf.name}: {d.motivo}")

(
    spark.createDataFrame(pd.DataFrame(livros))
    .withColumn("decidido_em", F.current_timestamp())
    .write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{ALVO}.leitor_livros")
)
(
    spark.createDataFrame(pd.DataFrame(paginas))
    .write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{ALVO}.bronze_leitor_paginas")
)
display(spark.table(f"{ALVO}.leitor_livros"))
