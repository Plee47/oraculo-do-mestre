# 0009 · Leitura profunda: etapas de criação, leitura sob demanda e o livro em primeiro lugar

**Status:** aceita · 2026-11-06

## Contexto

O objetivo central do projeto é a adaptabilidade: criar as ferramentas de uma mesa a partir de
qualquer livro de RPG, por mais obscuro que seja. A leitura da ADR 0007 resumia regras, mas não
entendia a estrutura de escolhas de cada sistema (raça → classe → subclasse no nível certo) nem o
que cada opção concede. Ler tudo a fundo de uma vez, por outro lado, gastaria a cota e levaria
muitos minutos.

## Decisão

1. **Etapas de criação na especificação:** a leitura extrai a sequência de decisões do livro, com
   hierarquia (`depende_de`, `pai`), nível mínimo e a página de cada opção.
2. **Mapa do livro sem LLM:** os títulos de todas as páginas vão junto com o pedido de estrutura,
   para o LLM enxergar o livro inteiro mesmo quando ele não tem sumário.
3. **Leitura a fundo sob demanda:** uma opção só é lida a fundo quando aparece numa ficha, uma
   vez por livro (depois vem do cache). Traz descrição, bônus, fórmulas, habilidades por nível
   com página, poderes e subopções.
4. **Segunda leitura só das lacunas:** se a primeira leitura não trouxe a regra de dano ou de
   vida, um pedido extra busca só isso. Sem lacuna, não gasta nada.
5. **Correções determinísticas:** a etapa principal é decidida pelo nome quando ele é inequívoco
   (classe, especialização, profissão), e perícias ou equipamento não viram escolhas da ficha.
6. **Encontros por dificuldade:** a sugestão escolhe, entre as criaturas do livro ou inimigos
   montados pelas regras dele, o grupo mais perto da dificuldade pedida, usando a mesma conta da
   análise. Sem os números necessários, ela não inventa: diz o que falta.
7. **Narrativa como sugestão:** aparência, personalidade, história e poder de assinatura usam as
   escolhas, os atributos e trechos do livro, com o modelo pequeno, só quando pedido. O site marca
   como sugestão e o prompt proíbe copiar personagens da obra.
8. **PDF com a identidade do sistema:** seis temas escolhidos pelo gênero lido do livro (paleta,
   tipografia, ornamento), sem copiar arte. Fundo claro para imprimir e espaço para anotar valores
   atuais.
9. **O livro em primeiro lugar:** um livro enviado é lido pela IA por padrão, mesmo de D&D 5e ou
   F&M. As regras escritas à mão ficam como reserva, opção rápida, demonstração e gabarito.

## Consequências

- O custo acompanha o uso: a primeira leitura faz de 4 a 5 pedidos, e cada opção nova faz mais um.
- A leitura varia entre execuções e ainda erra. Por isso cada opção cita a página, o resumo mostra
  o que não foi lido e qualquer número pode ser corrigido à mão.
- O layout do PDF é o mesmo em todos os temas: muda a identidade visual, não a estrutura. A ficha
  não copia a ficha oficial de cada livro.
- As fontes do PDF são as embutidas em todo leitor de PDF (cobrem o português), para não baixar nem
  distribuir arquivos de fonte.
