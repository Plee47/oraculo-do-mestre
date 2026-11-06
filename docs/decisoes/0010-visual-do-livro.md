# 0010 · O visual do site muda com o livro, por sessão

**Status:** aceita · 2026-11-06

## Contexto

As fichas em PDF já têm o tema do gênero do livro. A ideia é o site inteiro acompanhar, como opção,
mantendo o grimório como padrão. O tema do Streamlit vem de `.streamlit/config.toml` e vale para o
servidor inteiro.

## Decisão

1. **Uma folha de estilo por sessão.** Trocar a configuração do servidor (`st._config.set_option`)
   mudaria o site de todos os visitantes, então foi descartado. Cada tema é um CSS enviado só à
   sessão de quem escolheu o livro: `app/temas/base.css` sobrepõe os componentes, e
   `app/temas/<tema>.css` traz cores, fontes e ornamentos.
2. **As cores ficam só no CSS.** Gráficos e testes leem as variáveis do próprio arquivo do tema.
3. **Grimório sem sobreposição.** Com a opção desligada, sem livro ou em gênero neutro, nada é
   sobreposto, e o site é exatamente o visual padrão.
4. **Transição sem JavaScript.** Estilo e capa chegam no mesmo elemento. A capa aparece junto com o
   tema, esconde a troca das fontes e se abre em duas folhas. Um contador no HTML faz a animação
   tocar só quando o tema muda. Ela leva 1,6 s, mais que os 300 ms usados em interações comuns,
   porque é um evento raro: só acontece ao trocar de livro ou de opção.
5. **Auditoria no navegador.** Um script percorre cada tema e cada página, mede o contraste de todo
   texto e procura cores do tema antigo. Foi ele que achou a maior parte dos problemas.

## Consequências

- Os seletores dependem da estrutura interna do Streamlit e podem precisar de ajuste ao atualizá-lo.
  Se um seletor deixar de valer, o componente volta às cores do grimório, sem quebrar a página.
- Tabelas são desenhadas em canvas e não aceitam CSS de cor: um filtro as aproxima da paleta.
- A trilha do controle deslizante traz a cor no próprio elemento, então fica lisa nos temas.
- A primeira vez em cada tema baixa as fontes dele.
