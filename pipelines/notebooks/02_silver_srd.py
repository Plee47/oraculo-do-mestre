# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver — catálogo normalizado do SRD
# MAGIC
# MAGIC * Deduplica a bronze (fica a versão mais recente de cada arquivo).
# MAGIC * Interpreta os JSONs com `oraculo.sistemas.dnd5e.srd`, **o mesmo código testado no CI**.
# MAGIC * Valida as expectativas de qualidade (contagens, tabela de níveis completa, referências
# MAGIC   entre magias e classes) e **falha o job** se algo estiver errado.
# MAGIC * Grava uma tabela silver por entidade: colunas planas para SQL + `dados_json` completo.

# COMMAND ----------

import json
import sys

import pandas as pd
from pyspark.sql import Window
from pyspark.sql import functions as F

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
sys.path.insert(0, f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src")

from oraculo.sistemas.dnd5e.srd import montar_catalogo
from oraculo.sistemas.dnd5e.tabelas import catalogo_para_linhas, validar_catalogo

ALVO = f"`{CATALOGO}`.`{SCHEMA}`"

# COMMAND ----------

recente = Window.partitionBy("arquivo").orderBy(F.col("ingerido_em").desc())
bronze = (
    spark.table(f"{ALVO}.bronze_srd")
    .withColumn("_rn", F.row_number().over(recente))
    .filter("_rn = 1")
    .select("recurso", "item_id", "json_bruto")
    .collect()
)

# ~600 registros: o parsing roda no driver, com as funções puras do pacote.
catalogo = montar_catalogo((r.recurso, r.item_id, json.loads(r.json_bruto)) for r in bronze)
problemas = validar_catalogo(catalogo)
assert not problemas, "Falhou nas expectativas de qualidade:\n" + "\n".join(problemas)
print(catalogo.resumo())

# COMMAND ----------

for tabela, linhas in catalogo_para_linhas(catalogo).items():
    nome = f"{ALVO}.silver_dnd5e_{tabela}"
    (
        spark.createDataFrame(pd.DataFrame(linhas))
        .withColumn("atualizado_em", F.current_timestamp())
        .write.mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(nome)
    )
    spark.sql(f"COMMENT ON TABLE {nome} IS 'Silver: {tabela} do SRD 5.1 (D&D 5e)'")

display(spark.table(f"{ALVO}.silver_dnd5e_classes").drop("dados_json"))
