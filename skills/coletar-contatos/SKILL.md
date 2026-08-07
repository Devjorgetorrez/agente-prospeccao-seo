# Skill: coletar-contatos

## Para que serve
Para cada candidato com `status_tecnico = "ok"` após o sinal 3, visita o
site e extrai três canais de contato: WhatsApp/telefone, e-mail, Instagram.
Registra a origem exata de cada dado. Não classifica confiança — isso é
derivado pelo `portoes.py` a partir do campo `fonte_*`.

Roda em lotes de `tamanho_lote` (padrão: 10), com checkpoint.

## Dependências
- `plugin/coletas/candidatos_<execucao_id>.json` — lista de candidatos ok
- Extensão Claude in Chrome ativa (necessária para navegar nos sites)

## Entrada
```
execucao_id : string  — ex: "20260803_advogado_campinas"
```

## Saída
- `plugin/coletas/contatos_<execucao_id>_lote_<N>.json` — um por lote
- `plugin/checkpoints/<execucao_id>.json` — atualizado após cada lote

---

## Passo a passo

### Passo 1 — Identificar candidatos elegíveis
Abrir `candidatos_<execucao_id>.json`.
Selecionar todos com `status_tecnico = "ok"`, em ordem de aparição.

### Passo 2 — Verificar checkpoint
Abrir `plugin/checkpoints/<execucao_id>.json` se existir.
Campo relevante: `contatos.lotes_completos`.
Pular lotes já concluídos.

### Passo 3 — Processar cada lote

Para cada candidato do lote, visitar `https://<dominio>`.

#### 3a. Varredura da página — links no DOM (método primário para WhatsApp)

**Por que DOM e não texto:** botões flutuantes de WhatsApp são renderizados via
JavaScript e não aparecem no texto retornado por `get_page_text`. O único método
confiável é buscar atributos `href` no DOM via `javascript_tool`. Isso captura o
link mesmo quando ele não é visível como texto — confirmado em produção
(almeidaguimaraes.adv.br: wa.me/message encontrado 2× via DOM, texto visível zero).

**Dois formatos de link de WhatsApp — tratamento diferente:**

- `wa.me/<numero>` — número direto na URL. Extrair o número da própria URL.
  Gravar como `fonte_telefone: "wa_me_html"`.
- `wa.me/message/<código>` (WhatsApp Business API) — URL **não contém** o número.
  Seguir o redirect uma vez para confirmar a identidade da empresa. Extrair o
  número do **texto** da mesma página (via `get_page_text` no passo 3b), próximo
  ao link ou na seção de contatos. Gravar como `fonte_telefone: "wa_me_message_html"`.
  Se o número não estiver no texto da página, gravar `telefone: null` e
  `fonte_telefone: null` — nunca herdar o número do Maps como substituto.

Rodar `javascript_tool` para capturar todos os links de WhatsApp do DOM:

```javascript
const waLinks = Array.from(
  document.querySelectorAll('a[href*="wa.me/"], a[href*="api.whatsapp.com"]')
);
// wa.me/<numero> — número direto na URL
const waNum = waLinks.map(a => {
  const m = a.href.match(/wa\.me\/(\d+)/) || a.href.match(/phone=(\d+)/);
  return m ? m[1] : null;
}).filter(Boolean).filter((v,i,arr) => arr.indexOf(v)===i);
// wa.me/message/<codigo> — link curto Business API; número NÃO está na URL
const waMsgLinks = waLinks.map(a =>
  a.href.match(/wa\.me\/message\//) ? a.href : null
).filter(Boolean).filter((v,i,arr) => arr.indexOf(v)===i);

const emails = Array.from(
  document.querySelectorAll('a[href^="mailto:"]')
).map(a => a.href.replace(/^mailto:/i,'').split('?')[0].trim().toLowerCase())
 .filter(e => e && !e.startsWith('noreply') && !e.startsWith('no-reply'))
 .filter(e => !['wixpress.com','wordpress.com','godaddy.com']
              .some(d => e.includes('@' + d)));

const ig = Array.from(
  document.querySelectorAll('a[href*="instagram.com/"]')
).map(a => {
  const m = a.href.match(/instagram\.com\/([^/?#\s]+)/);
  return (m && !['explore','p','reel','accounts','stories','direct','sharer']
              .includes(m[1])) ? m[1] : null;
}).filter(Boolean).filter((v,i,arr) => arr.indexOf(v)===i);

JSON.stringify({waNum, emails, ig})
```

#### 3b. Varredura da página inicial — texto visível

Chamar `get_page_text` na mesma página para identificar:
- Telefone em texto: número no formato `(XX) XXXXX-XXXX` ou `(XX) XXXX-XXXX`
- E-mail em texto solto (quando não existe `mailto:`)

#### 3c. Página de contato — quando necessário

Se após 3a e 3b algum canal ainda não foi encontrado, tentar navegar para
`/contato` ou `/fale-conosco` e repetir os passos 3a e 3b nessa página.

Não tentar mais de duas páginas por candidato no total.

#### 3d. Registrar resultados

Campos a gravar por candidato:

| Campo | O que é | Quando null |
|---|---|---|
| `telefone` | Número extraído de wa.me URL ou de texto da página | Canal não encontrado |
| `fonte_telefone` | Como foi achado (ver tabela abaixo) | null quando telefone é null |
| `email` | Endereço de e-mail | Canal não encontrado |
| `fonte_email` | Como foi achado | null quando email é null |
| `instagram` | Handle sem `@` | Canal não encontrado |
| `fonte_instagram` | Como foi achado | null quando instagram é null |

**Valores de `fonte_*`:**

| Valor | Quando usar |
|---|---|
| `wa_me_html` | Link `wa.me/<numero>` ou `api.whatsapp.com` com número na URL — confirmação alta |
| `wa_me_message_html` | Link `wa.me/message/<código>` no HTML — número extraído do texto da mesma página, após redirect confirmar identidade da empresa — confirmação média |
| `mailto_html` | Link `mailto:<email>` encontrado no HTML |
| `texto_pagina_contato` | Dado encontrado como texto em `/contato` ou `/fale-conosco` |
| `rodape` | Dado encontrado no rodapé, fora da página de contato |
| `outra` | Qualquer outra localização (header, sidebar, home sem rodapé claro) |

**Regras de descarte automático de e-mail:**
- Começa com `noreply@` ou `no-reply@`
- Domínio de plataforma: `wixpress.com`, `wordpress.com`, `godaddy.com`

**Telefone extraído de wa.me:** gravar o número sem prefixo de país e com
a formatação local — ex.: wa.me/5519981178266 → `(19) 98117-8266`.

#### 3e. Gravar o lote

Escrever `plugin/coletas/contatos_<execucao_id>_lote_<N>.json`.

#### 3f. Atualizar o checkpoint

Adicionar N à lista `contatos.lotes_completos`. Mesclar — nunca
sobrescrever o arquivo inteiro.

---

## Formato exato dos arquivos de saída

### `contatos_<execucao_id>_lote_<N>.json`
```json
{
  "execucao_id": "20260803_advogado_campinas",
  "lote": 1,
  "tamanho_lote": 10,
  "contatos": [
    {
      "dominio": "sartoriadvogados.com.br",
      "telefone": "(19) 3251-0106",
      "fonte_telefone": "rodape",
      "email": "contato@sartoriadvogados.com.br",
      "fonte_email": "mailto_html",
      "instagram": "sartoriadvogados",
      "fonte_instagram": "rodape"
    },
    {
      "dominio": "minatel.adv.br",
      "telefone": "(19) 99888-7766",
      "fonte_telefone": "wa_me_html",
      "email": null,
      "fonte_email": null,
      "instagram": null,
      "fonte_instagram": null
    }
  ]
}
```

### `checkpoints/<execucao_id>.json` (seção contatos)
```json
{
  "contatos": {
    "lotes_completos": [1, 2],
    "total_lotes": 2,
    "total_candidatos": 15
  }
}
```

---

## O que esta skill nunca faz
- Não usa screenshot como fonte de dado
- Não inventa contato — campo não encontrado fica `null`
- Não classifica confiança — só registra origem
- Não usa `noreply@` nem e-mails de plataforma
- Não navega mais de duas páginas por candidato
- Não avança para o próximo lote antes de gravar o atual
- Não registra o handle `@` junto — só o texto após a `/` do instagram.com

## Se o site não carregar ou retornar 404
Registrar todos os campos como `null` com `fonte_telefone: "site_inacessivel"`.
Documentar no lote e seguir para o próximo candidato.
