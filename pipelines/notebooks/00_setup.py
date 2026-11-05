# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Setup do Unity Catalog
# MAGIC
# MAGIC | Objeto | Para quê |
# MAGIC |---|---|
# MAGIC | volume `livros_abertos` | PDFs de licença aberta (SRDs, Creative Commons) — podem virar dados públicos |
# MAGIC | volume `livros_privados` | PDFs que você possui — o que sai daqui **nunca** é exportado |
# MAGIC | volume `exportacao` | Arquivos prontos para o site (somente sistemas com licença aberta) |

# COMMAND ----------

import sys

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
ALVO = f"`{CATALOGO}`.`{SCHEMA}`"

# O pacote `oraculo` é lido do volume `codigo` (enviado pelo deploy). pydantic e pyyaml já
# vêm no ambiente serverless.
sys.path.insert(0, f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src")

from oraculo.nucleo import SISTEMAS_DISPONIVEIS, obter_regras

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {ALVO} COMMENT 'Oráculo do Mestre'")
VOLUMES = {
    "livros_abertos": "PDFs de licença aberta (SRDs, Creative Commons)",
    "livros_privados": "PDFs do usuário. O conteúdo extraído daqui nunca é exportado.",
    "exportacao": "Arquivos gerados para o site público (apenas sistemas abertos)",
}
for nome, comentario in VOLUMES.items():
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {ALVO}.{nome} COMMENT '{comentario}'")

# COMMAND ----------

# Catálogo de sistemas: registra quais podem ser publicados (usado pelas fases seguintes).
sistemas = [
    {
        "sistema_id": s,
        "nome": (d := obter_regras(s).definicao).nome,
        "licenca": d.licenca,
        "conteudo_publico": d.conteudo_publico,
    }
    for s in SISTEMAS_DISPONIVEIS
]
spark.createDataFrame(sistemas).write.mode("overwrite").saveAsTable(f"{ALVO}.sistemas")
display(spark.table(f"{ALVO}.sistemas"))
