# 0005 · Leitor de livros com LLM: porteiro, ai_query e avaliação por gabarito

**Status:** aceita · 2026-11-05

## Contexto

O leitor transforma o PDF de um livro de RPG em magias e monstros estruturados, usados pelo
gerador de fichas e pelas análises. Restrições:

- qualquer pessoa pode enviar qualquer arquivo, e só livros de RPG de sistemas suportados
  devem virar dados;
- o Databricks Free Edition tem cota diária de LLM;
- livros protegidos não podem sair do workspace de quem os possui (ADR 0002);
- "o LLM parece bom" não é métrica.

## Decisão

1. **Porteiro antes do LLM** (`oraculo.leitor.porteiro`): o detector `champion` (Fase 3a)
   precisa dizer "é RPG" e reconhecer um sistema suportado. Caso contrário, o livro é barrado
   com o motivo, sem nenhuma chamada de LLM.
2. **Pré-filtro de páginas:** dentro de um livro aceito, só vão ao LLM as páginas com indício
   de magia ou bloco de estatísticas. No SRD 5.1, isso corta 22% das páginas sem perder
   nenhuma entrada.
3. **LLMs do próprio Databricks via `ai_query`:** a extração roda em lote dentro do Spark,
   sem chave externa nem dado saindo da plataforma.
4. **Janelas de 2 páginas:** o LLM extrai só o que começa na página A e usa a página B para
   completar entradas cortadas, evitando duplicatas e cortes.
5. **Validação da saída no código:** o JSON do LLM é convertido para os mesmos modelos pydantic
   do catálogo, e o que não for válido é descartado (ex.: condições como "charmed" nas
   imunidades a dano).
6. **Avaliação por gabarito:** o SRD 5.1 existe em PDF e em dados estruturados (API). As
   entradas esperadas em cada página são achadas por regra, sem LLM. Cada modelo é medido em
   precisão, recall e acerto por campo, com um run do MLflow por modelo, e o melhor vira o
   modelo do leitor.
7. **Privacidade:** livros em `livros_privados` passam pelo mesmo fluxo, mas suas tabelas têm
   `privado = true` e nada delas é exportado. O site público não envia livros a LLM nenhum:
   ele só mostra a decisão do porteiro e as métricas da avaliação no SRD.

## Consequências

- A troca de modelo é guiada por números (nota geral, F1, acerto por campo, tempo).
- A avaliação só cobre D&D 5e em inglês. Para Feiticeiros & Maldições (Fase 4) não há
  gabarito público, e a qualidade terá de ser verificada por amostragem manual.
