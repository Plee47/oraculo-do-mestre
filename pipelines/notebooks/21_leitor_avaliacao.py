# Databricks notebook source
# MAGIC %md
# MAGIC # 21 · Leitor — avaliação dos LLMs contra o gabarito
# MAGIC
# MAGIC O SRD 5.1 existe em **PDF** (entrada do leitor) e em **dados estruturados** (catálogo da
# MAGIC API, camada silver). Então dá para medir a extração campo a campo:
# MAGIC
# MAGIC 1. Sorteia páginas com magias e com monstros (as entradas esperadas em cada página são
# MAGIC    achadas por regra, sem LLM: `oraculo.leitor.avaliacao.esperadas_na_pagina`).
# MAGIC 2. Roda **cada LLM** com `ai_query` sobre as mesmas páginas.
# MAGIC 3. Mede precisão, recall e acerto por campo. Um run do MLflow por modelo.
# MAGIC 4. O melhor modelo (`nota_geral`) vira o modelo do leitor em `leitor_modelo_escolhido`.

# COMMAND ----------

# MAGIC %pip install -q "mlflow>=2.16"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import hashlib
import json
import random
import sys
import time

import mlflow
import pandas as pd
from pyspark.sql import functions as F

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
dbutils.widgets.text(
    "modelos_llm",
    "databricks-meta-llama-3-3-70b-instruct,databricks-qwen3-next-80b-a3b-instruct,"
    "databricks-gpt-oss-120b",
)
dbutils.widgets.text("paginas_por_tipo", "12")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
MODELOS = [m.strip() for m in dbutils.widgets.get("modelos_llm").split(",") if m.strip()]
N_PAGINAS = int(dbutils.widgets.get("paginas_por_tipo"))
sys.path.insert(0, f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src")

from oraculo.leitor.avaliacao import avaliar_extracao, esperadas_na_pagina
from oraculo.leitor.extracao import INSTRUCOES, converter, janelas, prompt_unico
from oraculo.sistemas.dnd5e.tabelas import TABELAS, linhas_para_catalogo

ALVO = f"`{CATALOGO}`.`{SCHEMA}`"
usuario = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{usuario}/oraculo-leitor-llm")

# COMMAND ----------

gabarito = linhas_para_catalogo(
    {
        t: [
            r.dados_json
            for r in spark.table(f"{ALVO}.silver_dnd5e_{t}").select("dados_json").collect()
        ]
        for t in TABELAS
    }
)
paginas = [
    r.texto
    for r in spark.table(f"{ALVO}.bronze_leitor_paginas")
    .filter("livro = 'srd51'")
    .orderBy("pagina")
    .collect()
]
assert paginas, "o SRD 5.1 não passou pelo porteiro (rode a tarefa leitor_porteiro)"
por_pagina = {j.pagina: j for j in janelas(paginas)}
esperadas = {p: esperadas_na_pagina(paginas[p - 1], gabarito) for p in por_pagina}

rng = random.Random(42)
com_magias = sorted(p for p, (m, _) in esperadas.items() if m)
com_monstros = sorted(p for p, (_, mo) in esperadas.items() if mo)
amostra = sorted(set(rng.sample(com_magias, N_PAGINAS) + rng.sample(com_monstros, N_PAGINAS)))
esp_magias = set().union(*(esperadas[p][0] for p in amostra))
esp_monstros = set().union(*(esperadas[p][1] for p in amostra))
print(f"{len(amostra)} páginas | esperadas: {len(esp_magias)} magias, {len(esp_monstros)} monstros")

spark.createDataFrame(
    pd.DataFrame([{"pagina": p, "prompt": prompt_unico(por_pagina[p])} for p in amostra])
).createOrReplaceTempView("amostra_leitor")

# COMMAND ----------

hash_prompt = hashlib.sha256(INSTRUCOES.encode()).hexdigest()[:10]
resumo = []
for modelo in MODELOS:
    inicio = time.time()
    linhas = spark.sql(f"""
        SELECT pagina, r.result AS resposta, r.errorMessage AS erro
        FROM (
          SELECT pagina, ai_query('{modelo}', prompt,
                   modelParameters => named_struct('max_tokens', 4000, 'temperature', 0.0),
                   failOnError => false) AS r
          FROM amostra_leitor)
    """).collect()
    segundos = time.time() - inicio
    extracao = converter([(r.pagina, r.resposta or "") for r in linhas])
    res = avaliar_extracao(extracao, esp_magias, esp_monstros, gabarito)
    metricas = {
        **res.metricas,
        "segundos": segundos,
        "erros_api": sum(1 for r in linhas if r.erro),
        "erros_json": len(extracao.erros),
    }
    with mlflow.start_run(run_name=f"leitor-{modelo.removeprefix('databricks-')}"):
        mlflow.log_params(
            {"modelo": modelo, "paginas": len(amostra), "prompt_sha": hash_prompt, "temperatura": 0}
        )
        mlflow.log_metrics(metricas)
        mlflow.log_text(INSTRUCOES, "prompt.txt")
        mlflow.log_table(pd.DataFrame(res.campos), "campos.json")
    resumo.append({"modelo": modelo, **metricas})
    print(modelo, {k: round(v, 3) for k, v in metricas.items() if not k.endswith("_campo_x")})

tabela = pd.DataFrame(resumo).sort_values("nota_geral", ascending=False)
display(tabela)

# COMMAND ----------

melhor = tabela.iloc[0]
(
    spark.createDataFrame(tabela)
    .withColumn("avaliado_em", F.current_timestamp())
    .write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{ALVO}.leitor_avaliacao")
)
spark.createDataFrame(
    [{"modelo": melhor["modelo"], "nota_geral": float(melhor["nota_geral"])}]
).write.mode("overwrite").saveAsTable(f"{ALVO}.leitor_modelo_escolhido")

# Exporta só números (sem texto do livro) para o site.
destino = f"/Volumes/{CATALOGO}/{SCHEMA}/exportacao/avaliacoes/leitor_srd51.json"
dbutils.fs.mkdirs(destino.rsplit("/", 1)[0])
publico = {
    "livro": "D&D SRD 5.1 (CC-BY-4.0)",
    "paginas_avaliadas": len(amostra),
    "magias_esperadas": len(esp_magias),
    "monstros_esperados": len(esp_monstros),
    "modelo_escolhido": melhor["modelo"],
    "modelos": json.loads(tabela.to_json(orient="records")),
}
with open(destino, "w", encoding="utf-8") as f:
    json.dump(publico, f, ensure_ascii=False, indent=1)
    f.write("\n")
print(f"Modelo escolhido: {melhor['modelo']} (nota {melhor['nota_geral']:.3f})")
