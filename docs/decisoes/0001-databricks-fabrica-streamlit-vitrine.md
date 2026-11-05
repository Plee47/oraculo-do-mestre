# 0001 · Databricks como fábrica, Streamlit como vitrine

**Status:** aceita · 2026-11-05

## Contexto

O projeto precisa ser gratuito e acessível online como portfólio. O Databricks Free Edition
permite Databricks Apps, mas só para quem faz login no workspace, e os apps param sozinhos após
24 h. A internet de saída também é restrita e o uso é limitado a fins não comerciais.

## Decisão

- **Databricks** faz o trabalho pesado e *offline*: ingestão de livros, extração com LLM,
  tabelas Delta, treino e avaliação no MLflow. É orquestrado por um Asset Bundle versionado.
- **Streamlit Community Cloud** hospeda o site público, de graça, com deploy direto do GitHub.
- O Databricks **exporta** artefatos prontos (Parquet/JSON) só de sistemas com licença aberta, e o
  site lê esses arquivos.
- A lógica de regras vive num **pacote Python puro** (`src/oraculo`), usado pelos dois lados.

## Consequências

- O site funciona mesmo com o workspace desligado.
- O mesmo código roda no CI (testes em segundos), no Databricks e no site.
- Não há consultas ao vivo ao Databricks pelo site, então os dados ficam tão atuais quanto o
  último pipeline.
