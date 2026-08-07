# Skill: coletar-perfis

## Para que serve
Para cada candidato de origem `search` ou `pago` com `status_tecnico = "ok"`,
busca o perfil individual no Google Maps para confirmar presença física na
cidade buscada. Candidatos com `origem = "gmn"`, `"ambos"` ou `"pago_maps"`
já têm card coletado pelo `coletar-maps` — são ignorados aqui.

A obrigação mínima desta skill é extrair `endereco` e `site` (necessários para
o `filtro_setor.py sinal3`) e `tem_whatsapp_botao` (obrigatório para definir
`canal_preferencial`). Os outros campos são coletados quando disponíveis.

Roda em lotes de `tamanho_lote` (padrão: 10), com checkpoint.

## Dependências
- `plugin/coletas/candidatos_<execucao_id>.json` — já processado pelo
  `filtro_exclusao.py`
- Extensão Claude in Chrome ativa (necessária para navegar no Maps)

## Entrada
```
execucao_id : string  — ex: "20260803_advogado_campinas"
```

## Saída
Arquivos gravados em:
- `plugin/coletas/perfis_<execucao_id>_lote_<N>.json` — um por lote
- `plugin/checkpoints/<execucao_id>.json` — atualizado após cada lote

---

## Passo a passo

### Passo 1 — Identificar candidatos elegíveis
Abrir `candidatos_<execucao_id>.json`.

Candidatos elegíveis: `status_tecnico = "ok"` **e** `origem` em
`["search", "pago"]`.

Candidatos com `origem` em `["gmn", "ambos", "pago_maps"]` são ignorados —
já têm card do Maps; o `filtro_setor.py sinal3` lerá esses cards diretamente
de `maps_<execucao_id>.json`.

### Passo 2 — Verificar checkpoint
Abrir `plugin/checkpoints/<execucao_id>.json` se existir.
Campo relevante: `perfis.lotes_completos`.
Pular lotes já concluídos.

### Passo 3 — Processar cada lote

Para cada candidato elegível do lote:

#### 3a. Formular o termo de busca

Usar o campo `nome` do candidato como ponto de partida. Se o `nome` parecer
título de SERP genérico (contiver pipe `|`, dois-pontos `:` ou mais de 5
palavras sem nome próprio identificável), derivar o termo a partir do
domínio: extrair a parte antes do primeiro ponto e substituir hifens por
espaços (ex.: `ztorreselucarelli.com.br` → `ztorreselucarelli`).

Acrescentar o campo `cidade` ao termo de busca.

Exemplos:
- `nome = "Sartori Advogados"` → busca `"Sartori Advogados Campinas"`
- `nome = "Advogado de Família Campinas | Especializado..."` →
  domínio `ztorreselucarelli.com.br` → busca `"ztorreselucarelli Campinas"`

#### 3b. Navegar para a busca no Maps

URL de busca:
```
https://www.google.com/maps/search/<TERMO_URL_ENCODED>?hl=pt-BR
```

Aguardar o carregamento da lista de resultados (botões de perfil aparecem
como links `a[href*="/maps/place/"]`).

#### 3c. Extrair URLs de perfil

Usar `javascript_tool`:
```javascript
Array.from(document.querySelectorAll('a[href*="/maps/place/"]'))
  .map(a => a.href)
  .filter((v, i, arr) => arr.indexOf(v) === i)
  .slice(0, 5)
```

Retorna até 5 URLs únicas de perfil. Se nenhuma URL retornar, registrar
o candidato em `sem_perfil_maps` e avançar para o próximo.

#### 3d. Identificar o perfil correto

Para cada URL de perfil retornada (de cima para baixo):
1. Navegar até a URL.
2. Chamar `get_page_text` para capturar o texto do perfil.
3. Extrair `site` (domínio do website, sem protocolo e sem `www.`).
4. Aplicar as regras de casamento abaixo em ordem. Se qualquer uma bater,
   este é o perfil correto — parar a iteração.

**Regras de casamento por domínio (quando o candidato tem domínio):**

| Regra | Condição | Exemplo |
|---|---|---|
| 1. Exato | `site == dominio` | `sartoriadvogados.com.br == sartoriadvogados.com.br` |
| 2. Mesma raiz | `site.split(".")[0] == dominio.split(".")[0]` (ambos não-vazios) | `memdesa.adv.br ↔ memdesa.com.br` → raiz "memdesa" |
| 3. Edição ≤ 1 | Distância de Levenshtein entre `site` e `dominio` ≤ 1 | `msadvogado.com.br ↔ msadvogados.com.br` |

Estas mesmas três regras são implementadas mecanicamente em
`filtro_setor.py → _tem_presenca_local`. O Python aplica as regras de
forma idêntica ao confirmar presença local no sinal 3.

**Se nenhum dos 5 perfis bater pelo domínio:**
- Tentar casar por `telefone` (comparar dígitos apenas, ignorar formatação).
- Se ainda assim nenhum bater: registrar em `sem_perfil_maps` e avançar.

**Nunca casar por nome** — a grafia varia demais entre SERP e Maps.

#### 3e. Extrair campos do perfil

A partir do texto do `get_page_text` do perfil correto:

**nome**
Título principal do perfil — primeira linha identificável como nome do
estabelecimento.

**endereco**
Texto do endereço completo. Geralmente aparece próximo ao ícone de pin ou
ao rótulo "Endereço" / "Localização". Incluir logradouro, número, bairro,
cidade e UF quando disponíveis (ex.: `"Rua das Flores, 123 - Centro,
Campinas - SP, 13010-000"`). Não encontrado → `null`.

**telefone**
Número de telefone. Aparece como "(XX) XXXXX-XXXX" ou similar. Não
encontrado → `null`.

**site**
Domínio do website, sem protocolo e sem `www.`. Buscar texto que pareça
domínio (`.com.br`, `.adv.br`, etc.) próximo de rótulo "Site" no texto.
Não encontrado → `null`.

**tem_whatsapp_botao**
`true` se qualquer dos seguintes aparecer no texto do perfil:
- A palavra "WhatsApp" como link ou ação clicável
- Domínio `wa.me` ou `w.app` no campo Site ou em links visíveis

`false` se nenhum dos anteriores estiver presente.

**Campos opcionais** (coletar quando identificáveis no texto):
- `instagram`: handle `@...` próximo de "Instagram", ou `instagram.com/handle`
- `avaliacoes`: número inteiro de avaliações
- `nota`: número decimal 0.0–5.0

#### 3f. Gravar o lote

Escrever `plugin/coletas/perfis_<execucao_id>_lote_<N>.json`.

#### 3g. Atualizar o checkpoint

Adicionar N à lista `perfis.lotes_completos` em
`plugin/checkpoints/<execucao_id>.json`. Mesclar com chaves existentes —
nunca sobrescrever o arquivo inteiro.

---

## Formato exato dos arquivos de saída

### `perfis_<execucao_id>_lote_<N>.json`
```json
{
  "execucao_id": "20260803_advogado_campinas",
  "lote": 1,
  "tamanho_lote": 10,
  "cards": [
    {
      "dominio_candidato": "sartoriadvogados.com.br",
      "nome": "Sartori Advogados",
      "endereco": "Av. Brasil, 456 - Cambuí, Campinas - SP",
      "telefone": "(19) 99888-7766",
      "site": "sartoriadvogados.com.br",
      "instagram": null,
      "avaliacoes": 23,
      "nota": 4.5,
      "tem_whatsapp_botao": true
    },
    {
      "dominio_candidato": "minatel.adv.br",
      "nome": "Minatel Advogados",
      "endereco": "Rua Conceição, 77 - Centro, Campinas - SP",
      "telefone": "(19) 3234-5678",
      "site": "minatel.adv.br",
      "instagram": null,
      "avaliacoes": 11,
      "nota": 4.8,
      "tem_whatsapp_botao": false
    }
  ],
  "sem_perfil_maps": [
    {
      "dominio_candidato": "advlaboral.com.br",
      "motivo": "nenhum dos 5 perfis bateu por domínio ou telefone"
    }
  ]
}
```

**Notas sobre o formato:**
- `cards`: perfis encontrados e casados com um candidato. Um card por candidato.
- `sem_perfil_maps`: candidatos para os quais nenhum perfil Maps correspondente
  foi encontrado. Esses candidatos serão descartados pelo `filtro_setor.py sinal3`.
- `dominio_candidato`: domínio do candidato em `candidatos.json` — campo de
  rastreamento para o `sinal3` cruzar corretamente.
- `tem_whatsapp_botao` é obrigatório — nunca deixar `null`.

### `checkpoints/<execucao_id>.json` (seção perfis)
```json
{
  "perfis": {
    "lotes_completos": [1],
    "total_lotes": 1,
    "total_candidatos": 9
  }
}
```

---

## O que esta skill nunca faz
- Não processa candidatos com `origem` em `["gmn", "ambos", "pago_maps"]`
- Não casa perfil por nome — somente por domínio (site) ou telefone
- Não inventa dados: campo não encontrado fica `null`
- Não deixa `tem_whatsapp_botao` sem valor
- Não sobrescreve o checkpoint inteiro — sempre mescla
- Não avança para o próximo lote antes de gravar o atual

## Se o Maps pedir verificação antirrobô
Parar imediatamente. Gravar o lote parcial (candidatos já coletados com
os restantes registrados em `sem_perfil_maps`). Atualizar o checkpoint.
Retornar relatório com o ponto de parada.
