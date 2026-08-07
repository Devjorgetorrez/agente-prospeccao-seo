# Skill: coletar-serp

## Para que serve
Navega a segunda e terceira página do Google para a keyword + cidade da
rodada e coleta todos os resultados (pagos e orgânicos). Só roda depois
que o portão 0 passou. Quem atribui posições orgânicas globais e filtra
a faixa 6–30 é o `guardiao_coleta.py`, não esta skill.

## Dependências obrigatórias antes de começar
- Extensão Claude in Chrome instalada e com permissão para google.com.br
- `plugin/coletas/qualificacao_<execucao_id>.json` existente e com portão
  0 aprovado

## Entrada
```
execucao_id : string  — ex: "20260803_advogado_campinas"
```

## Saída
Arquivo gravado em: `plugin/coletas/serp_<execucao_id>.json`

---

## Passo a passo

### Passo 1 — Ler parâmetros da qualificação
Abrir `plugin/coletas/qualificacao_<execucao_id>.json` e extrair:
- `keyword`
- `cidade`

### Passo 2 — Montar a URL base
Mesma fórmula da `qualificar-keyword`, com `&near=<CIDADE_URL_ENCODED>`
obrigatório e com o parâmetro de offset para paginação:

`https://www.google.com.br/search?q=<TERMO_URL_ENCODED>&hl=pt-BR&gl=BR&num=10&near=<CIDADE_URL_ENCODED>&start=<OFFSET>`

Offsets:
- Página 2: `&start=10`
- Página 3: `&start=20`

**Por que URL e não clique no botão:** o Google às vezes usa rolagem
contínua em vez de paginação numerada — o botão "Próxima página" pode
não existir ou não ser capturável pelo `get_page_text`. A URL com
`&start=` é sempre confiável.

### Passo 3 — Navegar e capturar página 2
1. Usar `navigate` com a URL de `&start=10`.
2. Usar `get_page_text` para capturar o texto completo — não usar screenshot.
3. Registrar `url_navegada` (URL completa, incluindo `&start=10`).
4. **Verificação de região:**
   A região é garantida pelo parâmetro `&near=<cidade>` na URL — não há
   verificação via texto do rótulo "Escolher região", porque esse rótulo
   mostra a localização física da máquina, não a região aplicada à busca.
   Usá-lo causaria falso alarme toda vez (mostraria a cidade da máquina
   mesmo quando a busca está corretamente aplicada à cidade pedida).
   Se houver dúvida, comparar endereços ou menções de cidade nos snippets
   dos resultados com `cidade` da rodada — nunca o texto do rótulo.

### Passo 4 — Parsear resultados da página 2
Mesmas regras de identificação da `qualificar-keyword`:

**Como identificar PAGO:** contém "Patrocinado" ou "Anúncio" próximo ao
título ou URL.

**Como identificar ORGÂNICO:** título clicável sem rótulo de anúncio.

**O que IGNORAR:**
- Bloco "As pessoas também perguntam"
- Bloco de Imagens
- Bloco de Vídeos
- Pacote local (mapa com três empresas)
- "Pesquisas relacionadas"
- Qualquer elemento que não seja link para página externa

**Para cada resultado, registrar:**
```
ordem_na_pagina              : sequencial dentro desta página, começando em 1
                               NÃO reinicia entre pago e orgânico
tipo                         : "pago" | "organico"
dominio                      : host sem "www." e sem protocolo
titulo                       : texto do link principal
url                          : URL completa
snippet                      : texto descritivo abaixo do título, ou "" se não tiver
cidade_mencionada_diferente  : se o título ou snippet menciona explicitamente um
                               município ou estado DIFERENTE da cidade da rodada,
                               registrar qual (ex.: "Itu, SP", "Aracaju, SE");
                               null caso contrário.
                               Registrar mesmo em resultados que serão descartados
                               por outros motivos (lista_exclusao, sufixo
                               institucional) — é dado de auditoria.
                               Não registrar menções à própria cidade da rodada.
```

Registrar `total_resultados_pagina` = quantidade total de itens coletados
nesta página (pagos + orgânicos).

### Passo 5 — Navegar e capturar página 3
Repetir os Passos 3 e 4 com `&start=20`.

Se a página 3 retornar zero resultados (keyword com poucos resultados
indexados), registrar `total_resultados_pagina: 0` e `resultados: []` —
não é erro, é dado.

### Passo 6 — Gravar o arquivo de saída
Escrever `plugin/coletas/serp_<execucao_id>.json` com a estrutura exata
abaixo. Usar `ensure_ascii=False` e indentação de 2 espaços.

---

## Formato exato do arquivo de saída

```json
{
  "execucao_id": "<execucao_id>",
  "keyword": "<keyword>",
  "cidade": "<cidade>",
  "timestamp": "<ISO 8601, ex: 2026-08-03T14:30:22>",
  "paginas": {
    "pagina_2": {
      "url_navegada": "https://www.google.com.br/search?q=...&start=10",
      "total_resultados_pagina": 9,
      "resultados": [
        {
          "ordem_na_pagina": 1,
          "tipo": "organico",
          "dominio": "exemplo.com.br",
          "titulo": "Título do resultado",
          "url": "https://exemplo.com.br/pagina",
          "snippet": "Texto descritivo...",
          "cidade_mencionada_diferente": null
        }
      ]
    },
    "pagina_3": {
      "url_navegada": "https://www.google.com.br/search?q=...&start=20",
      "total_resultados_pagina": 8,
      "resultados": [...]
    }
  }
}
```

---

## O que esta skill nunca faz
- Não atribui posição orgânica global — o Python conta
- Não filtra a faixa 6–30 — o Python decide
- Não compara contra `lista_exclusao.yaml` — isso é feito no guardião
- Não navega clicando em "Próxima página" — sempre via `&start=` na URL
- Não navega sem `&near=<cidade>` na URL
- Não usa screenshot como fonte de dado — `get_page_text` é a fonte primária
- Não segue em frente se a navegação falhar — para e reporta o erro
- Não roda se o arquivo de qualificação não existir

## Se a extensão do Chrome pedir verificação "não sou um robô"
Parar imediatamente. Não tentar contornar. Reportar com:
```json
{ "ok": false, "erro": "bloqueio_captcha", "etapa": "coleta_serp" }
```
e aguardar instrução.
