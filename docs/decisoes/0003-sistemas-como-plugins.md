# 0003 · Sistemas de RPG como plugins

**Status:** aceita · 2026-11-05

## Contexto

O projeto começa com D&D 5e e Feiticeiros & Maldições, mas deve aceitar outros sistemas sem
reescrever o núcleo.

## Decisão

- Existe uma **ficha genérica** (`oraculo.nucleo.Ficha`, em pydantic) com nome, tipo
  (PJ/NPC/criatura), nível, classe, atributos e tags.
- Cada sistema é um subpacote `oraculo.sistemas.<id>` com:
  - `sistema.yaml`: dados estáticos (atributos, classes, tabelas, licença);
  - classe `Regras`: implementa `derivados()` e `validar()` em Python.
- A validação devolve `Problema`s com gravidade `erro` (fere a regra) ou `aviso` (dica). Os
  avisos são a semente do motor de análise da Fase 2.

## Alternativas descartadas

- **Regras 100% em YAML com fórmulas em texto:** exigiria um interpretador de expressões, seria
  difícil de testar e não daria conta de casos especiais (ex.: Defesa sem Armadura).
- **Um modelo de ficha por sistema:** duplicaria o motor de análise para cada sistema.
