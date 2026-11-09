# 0002 · Política de conteúdo (direitos autorais)

**Status:** aceita · 2026-11-05 · alterada pela [0011](0011-previas-de-leitura-abertas.md)

## Contexto

O leitor de livros processa PDFs de RPG. Muitos são protegidos por direitos autorais, e um
repositório público no GitHub equivale a publicar o conteúdo.

## Decisão

| Pode ir para o GitHub e o site | Fica só no ambiente de quem processou |
|---|---|
| Todo o código | PDFs de livros |
| Dados de SRDs e livros com licença aberta (ex.: SRD 5.1, CC-BY-4.0) | Tudo que for extraído de livros protegidos |
| Métricas, gráficos e capturas de tela | Fichas e tabelas derivadas desses livros |

- Cada sistema declara `licenca` e `conteudo_publico` no seu `sistema.yaml`.
- No Databricks, os volumes `livros_abertos` e `livros_privados` são separados, e só o primeiro
  alimenta a exportação.
- O **guardião** (`python -m oraculo.guardiao`) roda no pre-commit e no CI. Ele falha se houver
  livros versionados, pastas `privado/` ou dados públicos de sistemas sem licença aberta.
- **Feiticeiros & Maldições** só entra em `dados/publicos/` se a licença permitir ou se o autor
  autorizar por escrito.

## Consequências

Recrutadores veem o código e a qualidade medida em conteúdo aberto, e o dono do projeto usa a
ferramenta completa com os próprios livros. Isto não é aconselhamento jurídico, e sim o padrão
conservador usado por projetos open source de RPG.
