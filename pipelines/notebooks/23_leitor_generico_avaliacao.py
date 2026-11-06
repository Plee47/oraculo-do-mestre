# Databricks notebook source
# MAGIC %md
# MAGIC # 23 · Leitura genérica — avaliação contra o gabarito do SRD
# MAGIC
# MAGIC O site lê qualquer livro de RPG com um LLM. Aqui o PDF do SRD 5.1 é lido **como se fosse um
# MAGIC sistema desconhecido**, e o resultado é comparado com o catálogo (camada silver): atributos,
# MAGIC classes, criaturas (nome, PV, CA), mecânica e modificador.
# MAGIC
# MAGIC Compara as estratégias de seleção de páginas (palavras-chave, BM25, híbrida com embeddings),
# MAGIC com repetições, porque a leitura varia entre execuções. Um run do MLflow por estratégia. As
# MAGIC médias públicas vão para `exportacao/avaliacoes/leitor_generico_srd51.json`.

# COMMAND ----------

# MAGIC %pip install -q "mlflow>=2.16"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import statistics
import sys
import time

import mlflow

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
dbutils.widgets.text("estrategias", "palavras,bm25,hibrida")
dbutils.widgets.text("repeticoes", "3")
dbutils.widgets.text("pausa_segundos", "90")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
ESTRATEGIAS = [e.strip() for e in dbutils.widgets.get("estrategias").split(",") if e.strip()]
REPETICOES = int(dbutils.widgets.get("repeticoes"))
PAUSA = int(dbutils.widgets.get("pausa_segundos"))  # respeita o limite de uso do plano gratuito
sys.path.insert(0, f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src")

from oraculo.leitor.avaliacao_generica import avaliar_leitura
from oraculo.leitor.llm import ClienteDatabricks, ErroLLM
from oraculo.sistemas.dnd5e.tabelas import TABELAS, linhas_para_catalogo
from oraculo.sistemas.generico.leitura import VERSAO_LEITURA, ler_sistema

ALVO = f"`{CATALOGO}`.`{SCHEMA}`"
contexto = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
cliente = ClienteDatabricks(contexto.apiUrl().get(), contexto.apiToken().get())
usuario = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{usuario}/oraculo-leitor-generico")

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

# COMMAND ----------

resumo = []
for estrategia in ESTRATEGIAS:
    rodadas = []
    with mlflow.start_run(run_name=f"generico-{estrategia}"):
        mlflow.log_params(
            {"estrategia": estrategia, "repeticoes": REPETICOES, "versao": VERSAO_LEITURA}
        )
        for i in range(REPETICOES):
            time.sleep(PAUSA)
            inicio = time.time()
            try:
                leitura = ler_sistema(paginas, cliente, "srd51", estrategia=estrategia)
            except ErroLLM as erro:  # limite de uso: a rodada fica de fora, com registro
                print(f"{estrategia}, rodada {i}: {erro}")
                continue
            metricas = avaliar_leitura(leitura.sistema, gabarito)
            metricas["segundos"] = time.time() - inicio
            rodadas.append(metricas)
            mlflow.log_metrics(metricas, step=i)
        if not rodadas:
            print(f"{estrategia}: nenhuma rodada completa")
            continue
        medias = {f"media_{k}": statistics.mean(r[k] for r in rodadas) for k in rodadas[0]}
        medias["rodadas"] = len(rodadas)
        medias["desvio_nota_geral"] = (
            statistics.stdev(r["nota_geral"] for r in rodadas) if len(rodadas) > 1 else 0.0
        )
        mlflow.log_metrics(medias)
    resumo.append({"estrategia": estrategia, **medias})
    print(estrategia, {k: round(v, 3) for k, v in medias.items()})

# COMMAND ----------

display(spark.createDataFrame(resumo))

# Exporta só números (sem texto do livro) para o site e o README.
destino = f"/Volumes/{CATALOGO}/{SCHEMA}/exportacao/avaliacoes/leitor_generico_srd51.json"
dbutils.fs.mkdirs(destino.rsplit("/", 1)[0])
publico = {
    "livro": "D&D SRD 5.1 (CC-BY-4.0)",
    "versao": VERSAO_LEITURA,
    "repeticoes": REPETICOES,
    "estrategias": resumo,
}
with open(destino, "w", encoding="utf-8") as f:
    json.dump(publico, f, ensure_ascii=False, indent=1)
    f.write("\n")
