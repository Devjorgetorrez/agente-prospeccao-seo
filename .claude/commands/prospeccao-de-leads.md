---
description: Executa uma rodada completa de prospecção SEO + GEO + GMN — qualifica a keyword, coleta candidatos no Google e no Maps, aplica portões de qualificação, gera diagnóstico e link de WhatsApp, e grava no leads.csv.
---

Execute uma rodada completa do agente de prospecção conforme o processo definido em `CLAUDE.md`.

## Argumentos

`$ARGUMENTS` contém keyword e cidade quando o usuário digita algo como `/prospeccao-de-leads advogado em Campinas`.

- Se `$ARGUMENTS` vier preenchido, extraia keyword e cidade e confirme antes de continuar: *"Vou rodar para **{keyword}** em **{cidade}** — pode confirmar?"*
- Se `$ARGUMENTS` estiver vazio, pergunte uma coisa de cada vez:
  1. "Qual é a keyword? (ex.: advogado, contador, encanador)"
  2. Após a resposta: "Qual é a cidade? (ex.: Campinas, Recife, São Paulo)"

Não avance sem ter as duas respostas confirmadas.

## Pré-voo

Antes de qualquer coleta, rode:

```
python scripts/pre_voo.py
```

Se falhar, pare aqui. Explique o que falta — extensão do Chrome sem resposta, `config.yaml` incompleto, `leads.csv` inacessível — e aguarde o operador resolver. Não continue com pré-voo reprovado.

## Sequência

Com keyword, cidade e pré-voo confirmados, siga as 18 etapas da seção **"A sequência da rodada, passo a passo"** no `CLAUDE.md`, na ordem exata em que estão descritas lá.

O `CLAUDE.md` é a fonte de verdade de tudo: portões, critérios de qualificação, formatos de arquivo, checagens de qualidade, regras de diagnóstico e montagem de mensagem. Não pule etapas, não altere a ordem, não tome decisões que o `CLAUDE.md` atribui ao Python.
