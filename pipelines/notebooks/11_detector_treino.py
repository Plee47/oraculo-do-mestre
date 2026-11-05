# Databricks notebook source
# MAGIC %md
# MAGIC # 11 · Detector — treino e avaliação no MLflow
# MAGIC
# MAGIC * **Avaliação leave-one-book-out:** cada livro é previsto por um modelo que nunca viu
# MAGIC   nenhuma página dele.
# MAGIC * Compara o **modelo explicável** (6 features) com um **TF-IDF** como referência.
# MAGIC * Registra o modelo no Unity Catalog. O alias `champion` só vai para versões que acertam
# MAGIC   **todos** os livros, inclusive os casos difíceis (fantasia e regras de xadrez).
# MAGIC * Exporta o modelo em JSON (só coeficientes) para o site.

# COMMAND ----------

# MAGIC %pip install -q "scikit-learn>=1.3" "mlflow>=2.16" matplotlib

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import sys
import tempfile

import matplotlib.pyplot as plt
import mlflow
from mlflow import MlflowClient
from mlflow.models import infer_signature

dbutils.widgets.text("catalogo", "workspace")
dbutils.widgets.text("schema", "oraculo_dev")
CATALOGO = dbutils.widgets.get("catalogo")
SCHEMA = dbutils.widgets.get("schema")
CODIGO = f"/Volumes/{CATALOGO}/{SCHEMA}/codigo/src"
sys.path.insert(0, CODIGO)

from oraculo.leitor.detector import FEATURES, NOMES_FEATURES
from oraculo.leitor.treino import avaliar_leave_one_book_out, treinar_modelo_final

ALVO = f"`{CATALOGO}`.`{SCHEMA}`"
NOME_MODELO = f"{CATALOGO}.{SCHEMA}.detector_livro_rpg"
usuario = spark.sql("SELECT current_user()").first()[0]
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(f"/Users/{usuario}/oraculo-detector-livro-rpg")

# COMMAND ----------

paginas = spark.table(f"{ALVO}.silver_detector_paginas").toPandas()
textos = (
    spark.table(f"{ALVO}.bronze_corpus_paginas").select("fonte_id", "pagina", "texto").toPandas()
)
df = paginas.merge(textos, on=["fonte_id", "pagina"])  # o TF-IDF precisa do texto
print(f"{len(df)} páginas de {df['fonte_id'].nunique()} livros")

# COMMAND ----------

resultados = {}
for nome in ("features", "tfidf"):
    with mlflow.start_run(run_name=f"lobo-{nome}"):
        r = avaliar_leave_one_book_out(df, nome)
        mlflow.log_params({"modelo": nome, "livros": df["fonte_id"].nunique(), "paginas": len(df)})
        mlflow.log_metrics(r.metricas)
        mlflow.log_table(r.documentos, "documentos_leave_one_book_out.json")
        resultados[nome] = r
        print(nome, {k: round(v, 3) for k, v in r.metricas.items()})

display(resultados["features"].documentos)

# COMMAND ----------

final = treinar_modelo_final(df)
r = resultados["features"]
with mlflow.start_run(run_name="detector-final") as run:
    mlflow.log_params({"features": ",".join(FEATURES), "limiar_documento": final.limiar_documento})
    mlflow.log_metrics({f"lobo_{k}": v for k, v in r.metricas.items()})

    fig, ax = plt.subplots(figsize=(7, 4))
    coefs = sorted(final.coeficientes.items(), key=lambda x: x[1])
    ax.barh([NOMES_FEATURES[f] for f, _ in coefs], [c for _, c in coefs])
    ax.set_title("Peso de cada feature (dados padronizados)")
    fig.tight_layout()
    mlflow.log_figure(fig, "coeficientes.png")

    with tempfile.TemporaryDirectory() as tmp:
        caminho = f"{tmp}/detector_rpg.json"
        final.salvar(caminho)
        mlflow.log_artifact(caminho)

    # Versão sklearn no registro do Unity Catalog (mesmos coeficientes do JSON).
    from oraculo.leitor.treino import modelo_features

    pipe = modelo_features().fit(df[list(FEATURES)], df["rpg"].astype(int))
    info = mlflow.sklearn.log_model(
        pipe,
        "modelo",
        signature=infer_signature(
            df[list(FEATURES)].head(5), pipe.predict_proba(df[list(FEATURES)].head(5))
        ),
        input_example=df[list(FEATURES)].head(3),
        registered_model_name=NOME_MODELO,
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ### Portão de qualidade

# COMMAND ----------

aprovado = r.metricas["documentos_errados"] == 0 and r.metricas["pagina_recall"] >= 0.9
versao = info.registered_model_version
if aprovado:
    MlflowClient().set_registered_model_alias(NOME_MODELO, "champion", versao)
    destino = f"/Volumes/{CATALOGO}/{SCHEMA}/exportacao/modelos/detector_rpg.json"
    final.salvar(destino)
    print(f"Versão {versao} promovida a champion e exportada para {destino}")
else:
    raise RuntimeError(f"Versão {versao} reprovada no portão de qualidade: {r.metricas}")
