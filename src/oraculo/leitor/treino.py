"""Treino e avaliação do detector (usa scikit-learn; roda no Databricks e localmente).

Avaliação *leave-one-book-out*: cada livro é previsto por um modelo que nunca viu nenhuma
página dele. É a única forma honesta de medir com poucos livros — separar páginas do mesmo
livro entre treino e teste vazaria estilo, diagramação e vocabulário.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from oraculo.leitor.detector import FEATURES, MINIMO_CARACTERES, ModeloDetector, extrair_features


def tabela_de_paginas(paginas: pd.DataFrame) -> pd.DataFrame:
    """Recebe colunas fonte_id, texto, rpg, categoria; filtra páginas vazias e põe as features."""
    df = paginas[paginas["texto"].str.strip().str.len() >= MINIMO_CARACTERES].copy()
    feats = pd.DataFrame([extrair_features(t) for t in df["texto"]], index=df.index)
    return pd.concat([df, feats], axis=1)


def modelo_features():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000))


def modelo_tfidf():
    return make_pipeline(
        TfidfVectorizer(sublinear_tf=True, min_df=3, max_features=30000, ngram_range=(1, 2)),
        LogisticRegression(C=2.0, max_iter=2000),
    )


@dataclass
class ResultadoAvaliacao:
    paginas: pd.DataFrame  # predições fora da amostra, por página
    documentos: pd.DataFrame  # veredito por livro
    metricas: dict[str, float]


def avaliar_leave_one_book_out(df: pd.DataFrame, modelo: str = "features") -> ResultadoAvaliacao:
    y = df["rpg"].astype(int).to_numpy()
    probs = np.zeros(len(df))
    for fonte in df["fonte_id"].unique():
        teste = (df["fonte_id"] == fonte).to_numpy()
        if modelo == "features":
            m = modelo_features().fit(df.loc[~teste, list(FEATURES)], y[~teste])
            probs[teste] = m.predict_proba(df.loc[teste, list(FEATURES)])[:, 1]
        else:
            m = modelo_tfidf().fit(df.loc[~teste, "texto"], y[~teste])
            probs[teste] = m.predict_proba(df.loc[teste, "texto"])[:, 1]

    paginas = df[["fonte_id", "categoria", "rpg"]].assign(prob=probs, pred=(probs >= 0.5))
    docs = (
        paginas.groupby(["fonte_id", "categoria", "rpg"], as_index=False)
        .agg(nota=("prob", "mean"), paginas=("prob", "size"))
        .assign(e_rpg=lambda d: d["nota"] >= 0.5)
        .assign(acertou=lambda d: d["e_rpg"] == d["rpg"])
    )
    metricas = {
        "pagina_precisao": precision_score(y, paginas["pred"]),
        "pagina_recall": recall_score(y, paginas["pred"]),
        "pagina_f1": f1_score(y, paginas["pred"]),
        "pagina_auc": roc_auc_score(y, probs),
        "documento_acuracia": float(docs["acertou"].mean()),
        "documentos_errados": int((~docs["acertou"]).sum()),
    }
    for cat, grupo in paginas.groupby("categoria"):
        metricas[f"pagina_acuracia_{cat}"] = float((grupo["pred"] == grupo["rpg"]).mean())
    return ResultadoAvaliacao(paginas, docs, metricas)


def treinar_modelo_final(df: pd.DataFrame) -> ModeloDetector:
    """Treina com todos os livros e exporta no formato JSON do `ModeloDetector`."""
    pipe = modelo_features().fit(df[list(FEATURES)], df["rpg"].astype(int))
    escala, lr = pipe.named_steps["standardscaler"], pipe.named_steps["logisticregression"]
    return ModeloDetector(
        coeficientes={f: float(c) for f, c in zip(FEATURES, lr.coef_[0], strict=True)},
        intercepto=float(lr.intercept_[0]),
        medias={f: float(m) for f, m in zip(FEATURES, escala.mean_, strict=True)},
        desvios={f: float(s) for f, s in zip(FEATURES, escala.scale_, strict=True)},
    )
