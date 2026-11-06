# 0006 · Feiticeiros & Maldições: só mecânicas resumidas, sem extração por ora

**Status:** aceita · 2026-11-06

## Contexto

Feiticeiros & Maldições (F&M) é o segundo sistema do projeto. O Livro de Regras v2.5 é um
projeto de fãs gratuito, inspirado em *Jujutsu Kaisen*. Na seção de créditos, ele permite usar
o sistema como inspiração ou base, modificando ou adaptando, desde que os autores recebam
crédito. Ele não tem uma licença aberta formal (como CC BY), e o universo pertence a outra obra.

O livro base também não tem listas prontas para extrair: cada jogador monta a própria técnica
e os próprios feitiços, e as maldições (inimigos) ficam fora dele.

## Decisão

1. **Só mecânicas no repositório:** `sistemas/fm/sistema.yaml` traz números e fórmulas
   resumidos à mão, com crédito aos autores. Nenhum trecho do livro, nenhum personagem ou
   técnica da obra original.
2. **`conteudo_publico: false`:** o guardião bloqueia qualquer dado extraído do livro em
   `dados/publicos/fm/`. O PDF fica em `livros_privados`, no workspace de quem o tem.
3. **Porteiro aceita F&M, extrator não:** o livro é aceito e as páginas entram no bronze
   (privadas), mas `SISTEMAS_COM_EXTRATOR` mantém o extrator de magias e monstros só no D&D.
   Isso evita gastar a cota de LLM em páginas sem o que extrair.
4. **Fórmulas testadas contra o próprio livro:** os testes reproduzem o exemplo de criação
   passo a passo do livro.

## Consequências

- O site mostra gerador, ficha rápida e análise de grupo de F&M, mas não análise de encontro
  (não há bestiário).
- Uma fase futura pode extrair talentos, armas e aptidões do livro para tabelas privadas no
  Databricks, avaliadas por amostragem manual (não há gabarito público como o do SRD).
