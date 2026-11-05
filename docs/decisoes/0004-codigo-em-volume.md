# 0004 · Código do pacote servido por um volume do Unity Catalog

**Status:** aceita · 2026-11-05

## Contexto

O padrão dos templates de Asset Bundles é que os notebooks importem o código de `../src`
(arquivos do workspace). No Databricks Free Edition (serverless), isso falhou de duas formas:

- `%pip install ../../` → `403 Forbidden` no armazenamento dos arquivos do workspace;
- `sys.path` apontando para `../../src` → `OSError: [Errno 5] Input/output error`, de forma
  intermitente (cada execução falhava em um arquivo diferente).

Pela API (`databricks workspace export`), os mesmos arquivos eram lidos normalmente, então o
problema é a leitura pelo compute serverless, não o upload.

## Decisão

- O deploy (`scripts/deploy.py`) copia `src/` para o volume `<catalogo>.<schema>.codigo` e depois
  roda `databricks bundle deploy`.
- Os notebooks importam o pacote de `/Volumes/<catalogo>/<schema>/codigo/src`.
- O CI usa o mesmo script, então dev e prod seguem o mesmo caminho.

## Consequências

- O pipeline passou a rodar com sucesso no serverless.
- O deploy agora tem um passo extra fora do bundle. Se a leitura de arquivos do workspace
  estabilizar, dá para voltar ao padrão do template, ou empacotar um *wheel* no volume.
