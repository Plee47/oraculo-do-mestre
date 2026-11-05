# Databricks notebook source
# MAGIC %md
# MAGIC # 10 · Detector — corpus de treino
# MAGIC
# MAGIC Baixa as 12 obras de licença aberta (`oraculo.leitor.corpus.FONTES`) para o volume
# MAGIC `livros_abertos`, extrai o texto página a página e grava:
# MAGIC
# MAGIC | Tabela | Conteúdo |
# MAGIC |---|---|
# MAGIC | `bronze_corpus_paginas` | texto bruto de cada página + rótulo (RPG ou não) e categoria |
# MAGIC | `silver_detector_paginas` | páginas com texto suficiente + as features do detector |
# MAGIC
# MAGIC Se o workspace não alcançar os sites, rode `python scripts/carregar_corpus.py` localmente.

# COMMAND ----------

# MAGIC %pip install -q "pypdf>=4"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import sys
from pathlib import Path

import pandas as pd
from pyspark.sql import functions as F

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
sys.path.insert(0, f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src")

from oraculo.leitor.corpus import FONTES, baixar_corpus, paginas_do_arquivo
from oraculo.leitor.detector import FEATURES, MINIMO_CARACTERES, extrair_features

ALVO = f"`{CATALOGO}`.`{SCHEMA}`"
PASTA = Path(f"/Volumes/{CATALOGO}/{SCHEMA}/livros_abertos/corpus_detector")

# COMMAND ----------

try:
    print("baixados:", baixar_corpus(PASTA))
except Exception as erro:
    faltando = [f.id for f in FONTES if not (PASTA / f.arquivo).exists()]
    if faltando:
        raise RuntimeError(
            f"Sem acesso às fontes e faltam {faltando}. Rode: python scripts/carregar_corpus.py"
        ) from erro
    print(f"Fontes indisponíveis ({type(erro).__name__}); usando os arquivos do volume")

# COMMAND ----------

linhas = []
for f in FONTES:
    for i, texto in enumerate(paginas_do_arquivo(PASTA / f.arquivo)):
        linhas.append(
            {
                "fonte_id": f.id,
                "titulo": f.titulo,
                "pagina": i + 1,
                "texto": texto,
                "rpg": f.rpg,
                "categoria": f.categoria,
                "idioma": f.idioma,
                "licenca": f.licenca,
            }
        )
bronze = spark.createDataFrame(pd.DataFrame(linhas)).withColumn(
    "ingerido_em", F.current_timestamp()
)
bronze.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{ALVO}.bronze_corpus_paginas"
)

# COMMAND ----------

pdf = pd.DataFrame(linhas)
pdf = pdf[pdf["texto"].str.strip().str.len() >= MINIMO_CARACTERES].reset_index(drop=True)
feats = pd.DataFrame([extrair_features(t) for t in pdf["texto"]])
silver = pd.concat([pdf.drop(columns=["texto"]), feats], axis=1)
assert set(FEATURES) <= set(silver.columns)
assert silver.groupby("fonte_id").size().min() >= 20, "alguma obra ficou quase sem páginas"

spark.createDataFrame(silver).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{ALVO}.silver_detector_paginas"
)
display(
    spark.table(f"{ALVO}.silver_detector_paginas")
    .groupBy("fonte_id", "categoria", "rpg")
    .agg(F.count("*").alias("paginas"), *[F.round(F.avg(f), 2).alias(f) for f in FEATURES])
    .orderBy("rpg", "categoria")
)
