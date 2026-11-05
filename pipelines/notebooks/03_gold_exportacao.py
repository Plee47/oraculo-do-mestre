# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold — análises e exportação para o site
# MAGIC
# MAGIC * `gold_dnd5e_magias_por_classe`: quantas magias de cada função (dano, controle, cura,
# MAGIC   utilidade) cada classe tem por círculo, base para as análises de grupo da Fase 2.
# MAGIC * Exporta o catálogo para o volume `exportacao` **somente se o sistema tiver licença aberta**
# MAGIC   (tabela `sistemas`, ADR 0002). Depois, `python scripts/sincronizar_dados.py` traz o arquivo
# MAGIC   para `dados/publicos/` no repositório.

# COMMAND ----------

import sys

from pyspark.sql import functions as F

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
sys.path.insert(0, f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src")

from oraculo.sistemas.dnd5e.tabelas import TABELAS, linhas_para_catalogo, validar_catalogo

ALVO = f"`{CATALOGO}`.`{SCHEMA}`"

# COMMAND ----------

magias = spark.table(f"{ALVO}.silver_dnd5e_magias")
(
    magias.withColumn("classe", F.explode(F.split("classes", ",")))
    .groupBy("classe", "circulo", "funcao")
    .agg(F.count("*").alias("magias"), F.sum(F.col("area").cast("int")).alias("em_area"))
    .write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{ALVO}.gold_dnd5e_magias_por_classe")
)
display(
    spark.table(f"{ALVO}.gold_dnd5e_magias_por_classe")
    .groupBy("classe")
    .pivot("funcao")
    .sum("magias")
    .orderBy("classe")
)

# COMMAND ----------

publico = spark.table(f"{ALVO}.sistemas").filter("sistema_id = 'dnd5e'").first()["conteudo_publico"]
assert publico, "dnd5e não está marcado como conteúdo público — exportação bloqueada (ADR 0002)"

linhas = {
    t: [
        r.dados_json for r in spark.table(f"{ALVO}.silver_dnd5e_{t}").select("dados_json").collect()
    ]
    for t in TABELAS
}
catalogo = linhas_para_catalogo(linhas)
assert not validar_catalogo(catalogo)

destino = f"/Volumes/{CATALOGO}/{SCHEMA}/exportacao/dnd5e/catalogo.json"
catalogo.salvar(destino)
print(f"Exportado para {destino}: {catalogo.resumo()}")
