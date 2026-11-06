# 0007 · Qualquer livro de RPG: leitura com LLM e motor de regras genérico

**Status:** aceita · 2026-11-06

## Contexto

O objetivo do projeto é receber **qualquer** livro de RPG e montar o básico para jogar:
resumo do sistema, fichas e encontros. Até aqui só havia regras escritas à mão para D&D 5e e
Feiticeiros & Maldições, e a identificação do sistema usava termos comuns: um RPG brasileiro de
base 2d8 (Naruto *Shinobi no Sho*) foi classificado como "D&D 5e" porque usa "teste de
resistência", e o site entregou o gerador de D&D para ele.

Não dá para escrever regras à mão para cada sistema. Um LLM consegue ler o livro, mas erra e
varia entre leituras.

## Decisão

1. **Identificação por evidência forte:** regras prontas só quando o livro é mesmo D&D 5e (as
   12 classes + termos da 5ª edição) ou F&M (o título + "energia amaldiçoada"). Qualquer outro
   RPG vai para a leitura com LLM. Na dúvida (nota do detector entre 0,25 e o limiar), a
   leitura segue e o LLM confirma se é RPG.
2. **Leitura em três partes, com páginas escolhidas sem LLM:** visão geral e mecânica (inclui
   regra de dano e de encontros), criação de personagem (inclui o sumário, que lista classes e
   clãs) e criaturas. As três rodam em paralelo no LLM do Databricks (Foundation Model APIs,
   `databricks-gpt-oss-120b`, o melhor da avaliação da ADR 0005).
3. **Especificação validada (`SistemaLido`):** atributos (com rolagem própria e grupos com
   pontos separados), modificador, valores derivados com fórmulas (inclusive por arquétipo e
   encadeados), arquétipos, perícias, criaturas, nível e multiplicador de dano. Cada item é
   validado sozinho; o que não presta vira aviso.
4. **Fórmulas sem `eval`:** um avaliador sobre a árvore sintática aceita só números, nomes
   conhecidos, + − × ÷, min/max/arredondamentos e dados (2d8, 3d6×5, 4d6kh3). Nomes de várias
   palavras, acentos e palavras reservadas do Python ("for" = Força) são tratados.
5. **Correções determinísticas** para o que o LLM erra com frequência: tipo do valor derivado
   pelo nome (Vitalidade é vida), modificador d20 quando as fórmulas usam `mod_*`, marcadores
   como "outros" valem 0, nome desconhecido no dano (ex.: dano da arma) vale 0 com aviso.
6. **O usuário revisa:** o resumo mostra o que foi lido, os avisos e as páginas usadas, e
   permite corrigir números e fórmulas. O sistema lido pode ser salvo em JSON e recarregado
   sem gastar LLM.
7. **Sem bestiário, inimigos pelas regras:** muitos livros montam PdMs como personagens; a
   análise de encontro usa criaturas do livro quando existem e, senão, inimigos gerados com as
   mesmas regras.
8. **Privacidade e cota:** o PDF não é salvo; só trechos selecionados vão ao LLM e o resultado
   fica na sessão. Credenciais vêm dos segredos do Streamlit (`DATABRICKS_HOST`,
   `DATABRICKS_TOKEN`), nunca do repositório. Limite de 3 leituras por sessão.

## Consequências

- Funciona com sistemas que o projeto nunca viu, em português ou inglês, d20, 2d8, d100 ou
  parada de dados. Testado com o livro real do Naruto *Shinobi no Sho* (2d8), com o de F&M lido
  como sistema novo e com o SRD 5.1 em inglês.
- A leitura varia entre execuções e pode errar (ex.: no SRD 5.1, trouxe subclasses no lugar
  das classes). Por isso as regras prontas continuam valendo para D&D 5e e F&M, e a correção
  manual fica sempre à mão.
- As contas de encontro são estimativas por valor médio (dano × chance de acerto × multiplicador
  médio de dano) e o site diz isso; quando falta um número, a análise diz o que falta.
- Isso muda a ADR 0005 num ponto: o site agora envia trechos de livros a um LLM (o do
  Databricks), só durante a sessão de quem enviou o livro.
