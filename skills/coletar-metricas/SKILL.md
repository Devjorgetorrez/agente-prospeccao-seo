# Skill: coletar-metricas

## Para que serve
Para cada candidato da rodada com `status_tecnico = "ok"` e domínio,
busca tráfego mensal orgânico, autoridade de domínio e número de keywords
orgânicas. Usa cadeia de fallback: Ubersuggest primeiro; Semrush se o
Ubersuggest falhar ou retornar `{"noData":true}`; `fonte_metrica =
"nenhuma"` se ambos falharem. Grava `fonte_metrica` em toda linha, sem
exceção.

Roda em lotes de `tamanho_lote` (padrão: 10), com checkpoint — se a
execução travar no meio, retoma do lote correto, não do início.

## Dependências
- `plugin/coletas/candidatos_<execucao_id>.json` existente (já processado
  pelo `filtro_exclusao.py`)
- `plugin/coletas/qualificacao_<execucao_id>.json` existente (necessário
  para saber quais domínios já têm métrica do top3)
- Acesso ao MCP do Ubersuggest
- Acesso ao MCP do Semrush (para fallback)

## Entrada
```
execucao_id : string  — ex: "20260803_advogado_campinas"
```

## Saída
Arquivos gravados em:
- `plugin/coletas/metricas_<execucao_id>_lote_<N>.json` — um por lote
- `plugin/checkpoints/<execucao_id>.json` — atualizado após cada lote

---

## Passo a passo

### Passo 1 — Ler parâmetros
1. Abrir `qualificacao_<execucao_id>.json` e extrair a lista de domínios
   que já têm métrica (`top3_organicos[*].dominio`). Esses não serão
   rebuscados.
2. Abrir `candidatos_<execucao_id>.json` e extrair todos os candidatos
   com `status_tecnico = "ok"` que **tenham domínio** e cujo domínio
   **não esteja** na lista do passo anterior.
3. Ler `config.yaml` para `tamanho_lote` e `max_chamadas_mcp`.

### Passo 2 — Verificar checkpoint
Abrir `plugin/checkpoints/<execucao_id>.json` se existir.
Campo relevante: `metricas.lotes_completos` (lista de inteiros).
Calcular quantos lotes serão necessários e pular os já concluídos.

Se o arquivo de checkpoint não existir, começar do lote 1.

### Passo 3 — Processar cada lote
Para cada lote pendente:

**3a. Chamar Ubersuggest para cada domínio do lote**

Ferramenta: `mcp__claude_ai_Ubersuggest__domain_overview`
Parâmetro: domínio sem protocolo e sem "www."

Campos extraídos da resposta:
```
trafego            ← campo "traffic" na resposta
keywords_organicas ← campo "organic" na resposta
autoridade         ← campo "domainAuthority" na resposta
```

Resultado válido (ubersuggest_ok = true) quando a resposta contém os
campos acima sem retornar `{"noData":true}`. **Trafego = 0 é resultado
válido** — não é ausência de dado, é dado confirmado de tráfego zero.
Nesses casos, não chamar Semrush.

Usar Semrush (3b) quando o Ubersuggest:
- Retornar `{"noData":true}`
- Lançar erro / timeout
- Retornar `null` para todos os campos ao mesmo tempo

**3b. Fallback para Semrush — fluxo em três passos**

O Semrush não aceita parâmetros diretos de domínio no primeiro tool call.
O fluxo obrigatório é:

1. Chamar `mcp__claude_ai_Semrush__domain_overview` **sem parâmetros** —
   retorna a lista de relatórios disponíveis (passo de descoberta).

2. Chamar `mcp__claude_ai_Semrush__get_report_schema` com
   `report = "domain_rank"` — retorna o schema dos campos.

3. Chamar `mcp__claude_ai_Semrush__execute_report` com:
   ```
   report   = "domain_rank"
   params   = { "target": "<dominio>", "database": "br" }
   ```
   Campos extraídos do resultado:
   ```
   trafego            ← coluna de tráfego orgânico estimado
   keywords_organicas ← coluna de keywords orgânicas
   autoridade         ← coluna de authority score
   ```

Se Semrush retornar dados válidos: `fonte_metrica = "semrush"`,
`semrush_ok = true`.

Se Semrush também falhar: `fonte_metrica = "nenhuma"`, `semrush_ok =
false`, todos os campos numéricos ficam `null`.

**3c. Gravar o lote**

Escrever `plugin/coletas/metricas_<execucao_id>_lote_<N>.json`.

**3d. Atualizar o checkpoint**

Adicionar N à lista `metricas.lotes_completos` em
`plugin/checkpoints/<execucao_id>.json`. Se o arquivo já existir com
outras chaves (de outras etapas), mesclar — nunca sobrescrever o arquivo
inteiro.

---

## Formato exato dos arquivos de saída

### `metricas_<execucao_id>_lote_<N>.json`
```json
{
  "execucao_id": "<execucao_id>",
  "lote": 1,
  "tamanho_lote": 10,
  "candidatos": [
    {
      "dominio": "exemplo.adv.br",
      "trafego": 1200,
      "keywords_organicas": 85,
      "autoridade": 18,
      "fonte_metrica": "ubersuggest",
      "ubersuggest_ok": true,
      "semrush_ok": null
    },
    {
      "dominio": "outro.com.br",
      "trafego": 0,
      "keywords_organicas": 2,
      "autoridade": 1,
      "fonte_metrica": "ubersuggest",
      "ubersuggest_ok": true,
      "semrush_ok": null
    },
    {
      "dominio": "semtrafego.com.br",
      "trafego": 820,
      "keywords_organicas": 310,
      "autoridade": 22,
      "fonte_metrica": "semrush",
      "ubersuggest_ok": false,
      "ubersuggest_erro": "noData",
      "semrush_ok": true
    },
    {
      "dominio": "dominiofalso.xyz",
      "trafego": null,
      "keywords_organicas": null,
      "autoridade": null,
      "fonte_metrica": "nenhuma",
      "ubersuggest_ok": false,
      "ubersuggest_erro": "noData",
      "semrush_ok": false,
      "semrush_erro": "no_data"
    }
  ]
}
```

### `checkpoints/<execucao_id>.json`
```json
{
  "metricas": {
    "lotes_completos": [1, 2],
    "total_lotes": 3,
    "total_candidatos": 22
  }
}
```

---

## O que esta skill nunca faz
- Não busca métrica de domínio que já consta no top3 da qualificação
- Não inventa tráfego nem autoridade — dado ausente fica `null`
- Não registra métrica sem anotar a fonte
- Não usa a busca nativa (Google, DuckDuckGo) como fonte de tráfego ou
  autoridade
- Não trata trafego = 0 como ausência de dado — chama Semrush só quando
  Ubersuggest retorna `{"noData":true}` ou lança erro, nunca por trafego
  zero
- Não chama Semrush com parâmetro de domínio diretamente no primeiro
  tool call — o fluxo sempre começa com `domain_overview` sem parâmetros
- Não segue para o próximo lote antes de gravar o lote atual
- Não marca `semrush_ok: false` se o Semrush nunca foi chamado
  (campo fica `null` quando não foi necessário)

## Se um MCP falhar no meio de um lote
Parar o lote no ponto da falha. Gravar o que já foi coletado até ali
com os domínios restantes do lote marcados como `fonte_metrica =
"nenhuma"` e `ubersuggest_ok = false`. Atualizar o checkpoint com o lote
marcado como completo (mesmo que parcial). Reportar:
```json
{ "ok": false, "erro": "mcp_indisponivel", "lote": 2, "dominio": "exemplo.com.br" }
```
