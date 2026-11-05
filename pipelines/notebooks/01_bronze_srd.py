# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze — SRD 5.1 bruto
# MAGIC
# MAGIC 1. Baixa raças, classes (com os 20 níveis), magias, equipamentos e perícias da API pública
# MAGIC    [dnd5eapi.co](https://www.dnd5eapi.co) para o volume `livros_abertos` (pula o que já existe).
# MAGIC 2. **Auto Loader** carrega só os arquivos novos na tabela `bronze_srd`, guardando o JSON
# MAGIC    exatamente como veio.
# MAGIC
# MAGIC Se o workspace não tiver acesso à API, rode `python scripts/carregar_srd.py` localmente:
# MAGIC ele baixa e envia os arquivos para o mesmo volume.

# COMMAND ----------

import os
import sys

from pyspark.sql import functions as F

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
sys.path.insert(0, f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src")

from oraculo.sistemas.dnd5e.srd import baixar_srd

PASTA = f"/Volumes/{CATALOGO}/{SCHEMA}/livros_abertos/dnd5e_srd51_api"
CHECKPOINT = f"/Volumes/{CATALOGO}/{SCHEMA}/livros_abertos/_checkpoints/bronze_srd"
TABELA = f"`{CATALOGO}`.`{SCHEMA}`.bronze_srd"

# COMMAND ----------

try:
    print(f"{baixar_srd(PASTA)} arquivos novos baixados da API")
except Exception as erro:
    existentes = sum(len(arqs) for _, _, arqs in os.walk(PASTA)) if os.path.exists(PASTA) else 0
    if existentes == 0:
        raise RuntimeError(
            "Sem acesso à API e o volume está vazio. Rode localmente: python scripts/carregar_srd.py"
        ) from erro
    print(f"API indisponível ({type(erro).__name__}); seguindo com {existentes} arquivos do volume")

# COMMAND ----------

(
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "binaryFile")
    .option("recursiveFileLookup", "true")
    .option("pathGlobFilter", "*.json")
    .load(PASTA)
    .select(
        F.regexp_extract("path", r"/([^/]+)/[^/]+\.json$", 1).alias("recurso"),
        F.regexp_extract("path", r"/([^/]+)\.json$", 1).alias("item_id"),
        F.col("content").cast("string").alias("json_bruto"),
        F.col("path").alias("arquivo"),
        F.current_timestamp().alias("ingerido_em"),
    )
    .writeStream.option("checkpointLocation", CHECKPOINT)
    .trigger(availableNow=True)
    .toTable(TABELA)
    .awaitTermination()
)

spark.sql(f"COMMENT ON TABLE {TABELA} IS 'Bronze: JSON bruto do SRD 5.1 (dnd5eapi.co)'")
display(spark.table(TABELA).groupBy("recurso").count().orderBy("recurso"))
