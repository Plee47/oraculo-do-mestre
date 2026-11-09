# 0011 · Prévias abertas das leituras de D&D e de Feiticeiros & Maldições

**Status:** aceita · 2026-11-09 · altera a [0002](0002-politica-de-conteudo.md) e a
[0006](0006-feiticeiros-e-maldicoes.md)

## Contexto

O botão "Testar com D&D 5e" usa o catálogo do SRD, não uma leitura feita pela IA. Quem visita o
site só via o leitor funcionando se tivesse um PDF à mão. Duas leituras completas, com todas as
opções lidas a fundo, já existem: SRD 5.1 e Feiticeiros & Maldições v2.5.2.

Pela 0002, nada extraído de F&M podia ser publicado. O dono do projeto decidiu abrir as duas
prévias sem restrição de acesso.

## Decisão

1. **Duas prévias versionadas:** os arquivos ficam em `dados/publicos/previas/`. O site oferece um
   botão para cada uma, na página inicial.
2. **Lista fechada no guardião:** `PREVIAS_PUBLICAS` libera exatamente esses dois arquivos.
   Qualquer outro dado de F&M em `dados/publicos/` continua bloqueado.
3. **Só o que a IA resumiu:** a prévia é a especificação do sistema, com resumos curtos. O texto do
   livro e o PDF continuam fora do repositório.
4. **Crédito:** o site cita os autores de F&M, como o livro pede para quem usa o sistema como base.

## Verificação feita antes de publicar

As duas prévias foram comparadas com o texto dos livros, procurando trechos de 10 palavras ou mais
iguais ao original:

| Prévia | Palavras | Em trechos iguais ao livro |
|---|---|---|
| SRD 5.1 | 9.284 | 0 |
| F&M | 8.405 | 71 (0,8%), em 7 resumos de habilidade de uma frase |

## Consequências

- Qualquer visitante vê o leitor completo dos dois sistemas sem enviar um livro.
- F&M deixa de ser "nada extraído é publicado". O livro permite usar o sistema como base com
  crédito, mas não tem licença aberta formal. Se os autores pedirem, a prévia sai do repositório
  e do site, removendo o arquivo e a entrada em `PREVIAS_PUBLICAS`.
- Uma nova versão da leitura não atualiza as prévias sozinha: é preciso gerar e conferir de novo.
