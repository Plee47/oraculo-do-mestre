# Databricks notebook source
# MAGIC %md
# MAGIC # 22 · Leitor — extração dos livros aceitos
# MAGIC
# MAGIC Para cada livro aceito pelo porteiro, manda ao LLM escolhido na avaliação só as páginas
# MAGIC que passam no pré-filtro barato (indício de magia ou bloco de estatísticas) e grava:
# MAGIC
# MAGIC * `silver_leitor_respostas`: resposta bruta do LLM por página (auditoria);
# MAGIC * `silver_leitor_magias` e `silver_leitor_monstros`: entradas extraídas, no formato do
# MAGIC   catálogo, com a coluna `privado`. **O que vem de `livros_privados` nunca é exportado.**

# COMMAND ----------

import sys

import pandas as pd
from pyspark.sql import functions as F

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
dbutils.widgets.text("max_paginas_por_livro", "350")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
MAX_PAGINAS = int(dbutils.widgets.get("max_paginas_por_livro"))
sys.path.insert(0, f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src")

from oraculo.leitor.extracao import converter, janelas, parece_ter_entradas, prompt_unico

ALVO = f"`{CATALOGO}`.`{SCHEMA}`"
PADRAO = "databricks-meta-llama-3-3-70b-instruct"
escolhido = (
    spark.table(f"{ALVO}.leitor_modelo_escolhido").first()
    if spark.catalog.tableExists(f"{CATALOGO}.{SCHEMA}.leitor_modelo_escolhido")
    else None
)
MODELO = escolhido["modelo"] if escolhido else PADRAO
print("Modelo do leitor:", MODELO)

# COMMAND ----------

livros = spark.table(f"{ALVO}.leitor_livros").filter("aceito").collect()
prompts = []
for livro in livros:
    paginas = [
        r.texto
        for r in spark.table(f"{ALVO}.bronze_leitor_paginas")
        .filter(F.col("livro") == livro.livro)
        .orderBy("pagina")
        .collect()
    ]
    selecionadas = [j for j in janelas(paginas) if parece_ter_entradas(paginas[j.pagina - 1])]
    print(f"{livro.livro}: {len(selecionadas)} de {len(paginas)} páginas passam no pré-filtro")
    for j in selecionadas[:MAX_PAGINAS]:
        prompts.append(
            {
                "livro": livro.livro,
                "privado": livro.privado,
                "pagina": j.pagina,
                "prompt": prompt_unico(j),
            }
        )
if not prompts:
    dbutils.notebook.exit("nenhum livro aceito")
spark.createDataFrame(pd.DataFrame(prompts)).createOrReplaceTempView("prompts_leitor")

# COMMAND ----------

respostas = spark.sql(f"""
    SELECT livro, privado, pagina, '{MODELO}' AS modelo, r.result AS resposta, r.errorMessage AS erro
    FROM (
      SELECT livro, privado, pagina, ai_query('{MODELO}', prompt,
               modelParameters => named_struct('max_tokens', 4000, 'temperature', 0.0),
               failOnError => false) AS r
      FROM prompts_leitor)
""")
respostas.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{ALVO}.silver_leitor_respostas"
)

# COMMAND ----------

magias, monstros = [], []
for livro in livros:
    linhas = (
        spark.table(f"{ALVO}.silver_leitor_respostas")
        .filter(F.col("livro") == livro.livro)
        .collect()
    )
    ext = converter([(r.pagina, r.resposta or "") for r in linhas])
    print(
        f"{livro.livro}: {len(ext.magias)} magias, {len(ext.monstros)} monstros, {len(ext.erros)} erros"
    )
    base = {"livro": livro.livro, "privado": livro.privado}
    magias += [
        {**base, "id": m.id, "nome": m.nome, "circulo": m.circulo, "escola": m.escola,
         "dano": m.dano or "", "tipo_dano": m.tipo_dano or "", "dados_json": m.model_dump_json()}
        for m in ext.magias
    ]  # fmt: skip
    monstros += [
        {**base, "id": m.id, "nome": m.nome, "cr": m.cr, "ca": m.ca, "pv": m.pv, "tipo": m.tipo,
         "voa": m.voa, "dados_json": m.model_dump_json()}
        for m in ext.monstros
    ]  # fmt: skip

for nome, linhas in (("silver_leitor_magias", magias), ("silver_leitor_monstros", monstros)):
    if linhas:
        (
            spark.createDataFrame(pd.DataFrame(linhas))
            .withColumn("extraido_em", F.current_timestamp())
            .write.mode("overwrite")
            .option("overwriteSchema", "true")
            .saveAsTable(f"{ALVO}.{nome}")
        )
display(spark.table(f"{ALVO}.silver_leitor_monstros").groupBy("livro", "privado").count())
