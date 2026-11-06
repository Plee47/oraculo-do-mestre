# 0008 · Busca nas páginas, cache privado e avaliação da leitura genérica

**Status:** aceita · 2026-11-06

## Contexto

A leitura com LLM (ADR 0007) escolhia páginas por palavras-chave e relia o livro a cada envio.
Isso gasta a cota do plano gratuito e, em livros longos, às vezes perde a parte certa (no SRD,
vieram subclasses no lugar das classes). Além disso, a qualidade da leitura era medida no olho.

## Decisão

1. **Índice do livro** (`oraculo.leitor.indice`): BM25 em Python puro (grátis e instantâneo) e,
   opcionalmente, embeddings do Databricks (`databricks-qwen3-embedding-0-6b`), em lotes de 16
   para respeitar o limite de vazão, com busca híbrida.
2. **Avaliação contra o gabarito** (`oraculo.leitor.avaliacao_generica`, notebook 23): o PDF do
   SRD 5.1 é lido como se fosse um sistema desconhecido e comparado com o catálogo: atributos,
   classes, criaturas (nome, PV, CA), mecânica e modificador. A estratégia do site é a de
   melhor média, com repetições, porque a leitura varia entre execuções.
3. **Cache em tabela Delta privada** (`leitor_cache`, no workspace do dono do site), via API de
   instruções SQL: guarda só o que foi extraído e os vetores, **nunca o texto do livro**. A
   chave é o hash do texto + a parte + a versão dos prompts, então mudar um prompt invalida o
   que foi lido com a versão antiga. Valores vão sempre como parâmetros, nunca dentro do SQL.
4. **O cache é só um acelerador:** qualquer falha vira aviso e a leitura segue sem ele.

## Resultado da avaliação

Média de 3 rodadas no Databricks (notebook 23, versão `2026-11-06.2`):

| Estratégia | Nota geral | Classes achadas | PV das criaturas certos | Fórmulas calculáveis |
|---|---:|---:|---:|---:|
| Palavras-chave | 0,72 | 8% | 89% | 47% |
| BM25 | 0,72 | 11% | 88% | 60% |
| **Híbrida** | **0,80** | **33%** | **94%** | **92%** |

A híbrida vira o padrão do site. O limite de uso do plano gratuito (HTTP 429) apareceu em leituras
seguidas; por isso o cliente limita 2 pedidos simultâneos e espera mais antes de tentar de novo.

## Consequências

- Um livro já lido abre em segundos e não gasta LLM, para qualquer pessoa que envie o mesmo
  arquivo. Isso é aceitável porque só quem tem o arquivo consegue chegar àquele hash.
- O warehouse leva alguns segundos para ligar na primeira consulta.
- Cada mudança de prompt pode ser medida antes de ir ao ar: a nota sobe ou desce no MLflow.
