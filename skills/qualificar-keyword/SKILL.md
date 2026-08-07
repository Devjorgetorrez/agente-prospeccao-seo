# Skill: qualificar-keyword

## Para que serve
Abre o Google, lê somente a primeira página de resultados para a keyword +
cidade da rodada, separa anúncios de resultados orgânicos, captura o AI
Overview se existir, coleta o tráfego mensal dos três primeiros resultados
orgânicos via Ubersuggest (Semrush como fallback) e grava tudo num arquivo
JSON bruto. Quem calcula a média e decide se a keyword vale a pena é o
`portoes.py`, não esta skill.

## Dependências obrigatórias antes de começar
- Extensão Claude in Chrome instalada e com permissão para google.com.br
- MCP Ubersuggest conectado (e MCP Semrush como fallback)
- `execucao_id` gerado pelo pré-voo
- `keyword` e `cidade` da rodada corrente

## Entrada
```
execucao_id : string  — ex: "20260731_143022"
keyword     : string  — ex: "advogado trabalhista"
cidade      : string  — ex: "São Paulo"
```

## Saída
Arquivo gravado em: `plugin/coletas/qualificacao_<execucao_id>.json`

---

## Passo a passo

### Passo 1 — Montar o termo de busca
Concatenar `keyword` + `" "` + `cidade`.
Exemplo: `"advogado trabalhista São Paulo"`

### Passo 2 — Abrir o Google
1. Usar `tabs_create_mcp` para criar uma nova aba.
2. Usar `navigate` com a URL abaixo, incluindo **sempre** o parâmetro `&near=<CIDADE_URL_ENCODED>`:
   `https://www.google.com.br/search?q=<TERMO_URL_ENCODED>&hl=pt-BR&gl=BR&num=10&near=<CIDADE_URL_ENCODED>`
   Codificar espaços como `+`. Exemplo para "advogado trabalhista" em São Paulo:
   `https://www.google.com.br/search?q=advogado+trabalhista+S%C3%A3o+Paulo&hl=pt-BR&gl=BR&num=10&near=S%C3%A3o+Paulo`
3. Aguardar carregamento completo antes de ler a página.

**Por que o `&near=` é obrigatório:** o Google usa a localização física da máquina para personalizar resultados locais. Sem esse parâmetro, uma máquina em Sorocaba retorna resultados de Sorocaba mesmo quando a keyword diz "Campinas". Isso afeta principalmente o pacote de Locais (mapa) e pode alterar a ordem dos resultados orgânicos.

O parâmetro `&near=` força a região e elimina esse viés sem precisar de etapa extra de verificação. A linha "Escolher região" que aparece no rodapé da página do Google **não é capturada** pelo `get_page_text` (vive em parte do DOM fora do conteúdo principal), por isso a abordagem preventiva é mais confiável do que checar-e-corrigir.

### Passo 3 — Ler o conteúdo da página

Usar `get_page_text` para capturar o texto completo da página de uma vez só.

**Verificação de região:**
A região é garantida pelo parâmetro `&near=<cidade>` na URL — não há
verificação via texto de rótulo da página. Tanto o texto no topo (como
"Votorantim, SP") quanto o rótulo "Escolher região" no rodapé mostram a
localização física da máquina, não a região aplicada à busca. Usá-los como
indicador causaria falso alarme toda vez.
Se houver dúvida, comparar endereços ou menções de cidade nos snippets dos
resultados com `cidade` da rodada — nunca os rótulos da página.

Não usar screenshot como fonte de dado — `get_page_text` é a fonte primária.

### Passo 4 — Capturar o AI Overview (se existir)
Procurar por um bloco no topo da página que contenha qualquer uma destas
marcações em português: "Visão geral da IA", "Visão geral", "AI Overview".
Ele costuma aparecer antes dos resultados orgânicos normais.

- **Se encontrar:**
  - `presente: true`
  - `dominios_citados`: lista de domínios (só o host, sem www) que aparecem
    dentro do bloco como fontes ou links citados
  - `texto_parcial`: os primeiros 500 caracteres do texto do bloco

- **Se não encontrar:**
  - `presente: false`
  - `dominios_citados: []`
  - `texto_parcial: ""`

### Passo 5 — Capturar os resultados da primeira página
Percorrer todos os itens de resultado na ordem em que aparecem, de cima
para baixo. Para cada item:

**Como identificar se é PAGO:**
Anúncios contêm a palavra "Patrocinado" ou "Anúncio" próximo ao título ou
URL. No HTML, costumam ter um rótulo "Patrocinado" visível.

**Como identificar se é ORGÂNICO:**
Todo resultado com título clicável e snippet que NÃO tenha rótulo de
anúncio.

**O que IGNORAR (não conta como resultado):**
- Bloco de AI Overview (já capturado no Passo 4)
- Bloco "As pessoas também perguntam"
- Bloco de resultados de Imagens
- Bloco de resultados de Vídeos
- Pacote local (mapa com três empresas) — esses serão coletados separado
- "Pesquisas relacionadas"
- Qualquer coisa que não seja um link para uma página externa

**Para cada resultado (pago ou orgânico), registrar:**
```
ordem_na_pagina  : número sequencial contando pagos + orgânicos juntos,
                   começando em 1 — NÃO pular, NÃO reiniciar ao mudar de tipo
tipo             : "pago" ou "organico"
dominio          : host da URL, sem "www." e sem protocolo
                   ex: de "https://www.exemplo.com.br/pagina" → "exemplo.com.br"
titulo           : texto do link principal
url              : URL completa do resultado
snippet          : texto descritivo abaixo do título, ou "" se não tiver
```

**Regra importante:** não atribuir posição orgânica dentro da lista —
registrar só `ordem_na_pagina` e `tipo`. Quem numerará as posições
orgânicas é o Python.

### Passo 6 — Selecionar o top3 e coletar tráfego

Percorrer `resultados` em ordem crescente de `ordem_na_pagina`, avaliando
só entradas com `tipo == "organico"`. Para cada candidato, aplicar três
filtros em sequência:

**Filtro A — lista de exclusão por domínio literal:**
Verificar contra todas as entradas de `lista_exclusao.yaml`
(`diretorios_e_guias`, `redes_sociais`, `marketplaces`).
Se o domínio estiver em qualquer uma dessas listas → pular para o próximo
orgânico. O candidato ainda entra em `resultados` (dado bruto), mas não
no `top3_organicos`.

**Filtro B — sufixo institucional:**
Verificar se o domínio termina com qualquer entrada de `sufixos_institucionais`
(`.gov.br`, `.gov`, `.leg.br`, `.jus.br`, `.mil.br`, `.org.br`).
Se terminar → pular. Mesma regra: entra em `resultados`, não no `top3_organicos`.

Candidatos que passaram nos filtros A e B entram na fila de coleta de tráfego.

**Para cada candidato da fila, em ordem:**
1. Chamar `domain_overview` do MCP Ubersuggest passando o domínio.
2. Extrair dois valores:
   - `trafego_mensal`: visitas orgânicas mensais (campo `traffic` ou equivalente)
   - `keywords_organicas`: total de keywords orgânicas indexadas
   - Registrar `fonte_trafego: "ubersuggest"`
3. **Filtro C — portal de keywords:**
   Se `keywords_organicas` > `max_keywords_portal` do `config.yaml`
   (padrão: 5.000) → pular. É portal ou agregador, não empresa local.
4. Se passou no filtro C → adicionar ao top3. Parar quando o top3 tiver
   3 entradas, ou quando não houver mais orgânicos na página para tentar.

Se houver menos de 3 orgânicos que passem nos três filtros, usar os que
existirem (pode ser 2, 1 ou nenhum).

**Se o Ubersuggest falhar ou retornar null/zero:**
1. Tentar o MCP Semrush como fallback para `trafego_mensal` e
   `keywords_organicas`.
2. Se Semrush também falhar: registrar `trafego_mensal: 0`,
   `keywords_organicas: null`, `fonte_trafego: "nao_encontrado"`.
   Com `keywords_organicas: null`, o filtro C não pode ser avaliado —
   incluir no top3 provisoriamente.

**Regra:** nunca usar um número de tráfego sem registrar de qual fonte veio.

### Passo 7 — (integrado ao Passo 6)
A coleta de tráfego acontece dentro do Passo 6, intercalada com a
seleção, pois cada candidato precisa passar pelo filtro C antes de ser
confirmado no top3. Nenhuma ação adicional neste passo.

### Passo 8 — Montar o objeto top3_organicos
Para cada domínio confirmado no top3, montar:
```
ordem_na_pagina    : o mesmo valor do Passo 5 (vínculo com a lista de resultados)
dominio            : string
trafego_mensal     : número inteiro (0 se não encontrado)
keywords_organicas : número inteiro, ou null se não disponível
fonte_trafego      : "ubersuggest" | "semrush" | "nao_encontrado"
```

### Passo 9 — Gravar o arquivo de saída
Escrever o arquivo em `plugin/coletas/qualificacao_<execucao_id>.json`
com a estrutura exata abaixo. Usar `ensure_ascii=False` e indentação de 2
espaços.

---

## Formato exato do arquivo de saída

```json
{
  "execucao_id": "<execucao_id>",
  "keyword": "<keyword>",
  "cidade": "<cidade>",
  "termo_busca": "<keyword> <cidade>",
  "timestamp": "<ISO 8601, ex: 2026-07-31T14:30:22>",
  "ai_overview": {
    "presente": false,
    "dominios_citados": [],
    "texto_parcial": ""
  },
  "resultados": [
    {
      "ordem_na_pagina": 1,
      "tipo": "pago",
      "dominio": "anuncio.com.br",
      "titulo": "Título do anúncio",
      "url": "https://anuncio.com.br/pagina",
      "snippet": "Descrição"
    },
    {
      "ordem_na_pagina": 2,
      "tipo": "organico",
      "dominio": "organico1.com.br",
      "titulo": "Título orgânico",
      "url": "https://organico1.com.br/pagina",
      "snippet": "Descrição"
    }
  ],
  "top3_organicos": [
    {
      "ordem_na_pagina": 2,
      "dominio": "organico1.com.br",
      "trafego_mensal": 5400,
      "keywords_organicas": 234,
      "fonte_trafego": "ubersuggest"
    }
  ]
}
```

---

## O que esta skill nunca faz
- Não decide se a keyword vale a pena — isso é o portão 0 do `portoes.py`
- Não numera posições orgânicas — o Python conta
- Não vai para a segunda ou terceira página — só a primeira
- Não coleta o pacote local do Maps — isso é a skill `coletar-maps`
- Não inventa tráfego — se não achou, registra 0 e `nao_encontrado`
- Não segue em frente se a navegação falhar — para e reporta o erro
- Não usa screenshot como fonte de dado — `get_page_text` é a fonte primária
- Não navega sem o parâmetro `&near=<cidade>` na URL — a região é garantida por este
  parâmetro, não por verificação de rótulo da página
- Não seleciona domínios da lista de exclusão para o top3, mesmo que sejam orgânicos
- Não seleciona domínios com sufixo institucional (`.gov.br`, `.gov`, `.leg.br`, `.jus.br`, `.mil.br`, `.org.br`) para o top3
- Não seleciona candidatos com `keywords_organicas` acima de `max_keywords_portal` para o top3

## Se a extensão do Chrome pedir verificação "não sou um robô"
Parar imediatamente. Não tentar contornar. Reportar com:
```json
{ "ok": false, "erro": "bloqueio_captcha", "etapa": "qualificacao" }
```
e aguardar instrução.
