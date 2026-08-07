# Skill: coletar-maps

## Para que serve
Busca no Google Maps pela keyword + cidade da rodada, coleta até
`meta_resultados_maps` (padrão: 20) cards orgânicos, e para cada card
captura os dados crus necessários para o checklist de 9 sinais do GMN.
Roda em paralelo às Fases 3–5, antes de qualquer filtro de candidatos —
não existem "sobreviventes" neste ponto do pipeline.

## Dependências obrigatórias antes de começar
- Extensão Claude in Chrome instalada e com permissão para google.com
- `plugin/coletas/qualificacao_<execucao_id>.json` existente
- `execucao_id` gerado pelo pré-voo

## Entrada
```
execucao_id : string  — ex: "20260803_advogado_campinas"
```

## Saída
Arquivo gravado em: `plugin/coletas/maps_<execucao_id>.json`

---

## Passo a passo

### Passo 1 — Ler parâmetros da qualificação
Abrir `plugin/coletas/qualificacao_<execucao_id>.json` e extrair:
- `keyword`
- `cidade`
- `meta_resultados_maps` do `config.yaml` (padrão: 20)

### Passo 2 — Navegar para a busca no Maps

URL de busca:
```
https://www.google.com/maps/search/<KEYWORD>+<CIDADE>?hl=pt-BR
```

Codificar espaços como `+`. Exemplo para "advogado" em Campinas:
```
https://www.google.com/maps/search/advogado+Campinas?hl=pt-BR
```

**Por que não usa `&near=`:** o `&near=` é um parâmetro da busca regular do
Google (`google.com/search?...`), não do Maps. No Maps, incluir a cidade
no próprio termo de busca é o que ancora a localização — o mapa centra
automaticamente na cidade mencionada. Não há verificação de rótulo de página
para a localização (pela mesma razão da `qualificar-keyword`: rótulos de
página refletem a máquina, não a busca).

Aguardar carregamento completo antes de continuar.

### Passo 3 — Capturar a lista de resultados

Usar `get_page_text` para capturar o painel esquerdo com a lista de cards.

**Identificar patrocinados:**
Cards com o rótulo "Patrocinado" próximo ao nome são anúncios pagos.
Ignorar completamente — não entram no arquivo de saída, não são contados
na posição.

**Se a contagem de cards orgânicos visíveis for menor que `meta_resultados_maps`:**
Usar `javascript_tool` para rolar o painel de resultados e carregar mais:
```javascript
const seletores = ['[role="feed"]', '.m6QErb', '[aria-label*="Resultado"]'];
let painel = null;
for (const s of seletores) {
  painel = document.querySelector(s);
  if (painel) break;
}
if (painel) { painel.scrollTop += 3000; return 'rolou_painel'; }
window.scrollBy(0, 3000);
return 'rolou_janela';
```
Repetir `get_page_text` após a rolagem. Se ainda faltar, rolar mais uma vez e
ler novamente. Aceitar o total que aparecer — resultado abaixo de 20 não é
erro, é dado (keyword com poucos resultados no Maps).

### Passo 4 — Extrair URLs dos perfis

Usar `javascript_tool` para coletar as URLs de todos os cards orgânicos
visíveis:
```javascript
const links = Array.from(document.querySelectorAll('a[href*="/maps/place/"]'));
const urls = [...new Set(links.map(a => a.href))].filter(u => u.includes('/maps/place/'));
return urls.slice(0, 20);
```

Se `javascript_tool` não retornar URLs (mudança de DOM do Google), fallback:
para cada negócio identificado pelo nome no `get_page_text`, montar URL de
busca direta: `https://www.google.com/maps/search/<NOME>+<CIDADE>?hl=pt-BR`
e navegar para ela. Esse fallback é mais lento mas funciona.

### Passo 5 — Coletar cada perfil

Para cada URL de perfil (até `meta_resultados_maps`, em ordem de posição):

1. Navegar para a URL do perfil.
2. Usar `get_page_text` para capturar o texto completo do perfil.
3. Extrair os campos listados na seção "Campos de cada card" abaixo.
4. Registrar `posicao_maps` = sequência começando em 1 para o primeiro
   orgânico, incrementando a cada card (os patrocinados do Passo 3 não
   contam).

Processar um card de cada vez. Não navegar para o próximo antes de registrar
o atual.

---

## Campos de cada card

Para cada campo, a instrução indica o que buscar no texto do `get_page_text`
e o que registrar quando não encontrar.

### nome
O nome do negócio aparece como o texto principal no topo do perfil (geralmente
o maior título).

### endereco
Buscar texto de endereço: rua, número, bairro, cidade. Aparece próximo a
ícone de localização ou rótulo "Endereço" no texto capturado.
- Não encontrado → `null`

### telefone
Buscar número no formato `(XX) XXXXX-XXXX` ou `(XX) XXXX-XXXX`.
- Não encontrado → `null`

### site
Buscar texto que pareça domínio (`.com.br`, `.adv.br`, etc.) próximo de
rótulo "Site" no texto. Registrar apenas o host sem `www.` e sem protocolo.
- Não encontrado → `null`

### instagram
Buscar `instagram.com/` seguido de handle, ou `@handle` próximo de
"Instagram" no texto.
- Não encontrado → `null`

### avaliacoes
Número inteiro de avaliações. Aparece como "(123 avaliações)" ou "123"
próximo à nota em estrelas.
- Não encontrado → `null`

### nota
Número decimal entre 0.0 e 5.0. Aparece próximo às estrelas de avaliação.
- Não encontrado → `null`

### tem_whatsapp
`true` se o texto "WhatsApp" aparecer como link/botão no perfil.
`false` se não aparecer.

### data_ultimo_post
Buscar texto relativo de tempo próximo de seções como "Atualização",
"Novidade", "Postagem", "há X". Exemplo: "há 3 meses".
- Se encontrado → gravar o texto relativo exato (ex: `"há 3 meses"`)
- Não encontrado → `null`

### tem_produtos
Buscar seção "Produtos" ou "Serviços" no texto do perfil.
- `true`: seção existe e há nomes de itens listados abaixo dela
- `false`: seção existe mas aparece vazia, ou texto indica explicitamente
  ausência ("Sem produtos", "Nenhum produto")
- `null`: seção não aparece no texto capturado

### descricao
Buscar seção "Sobre" ou "Descrição" no perfil.
- Registrar o texto completo encontrado ali
- Não encontrado → `null`

### foto_data_mais_recente e foto_data_confirmada

Buscar qualquer texto de data/tempo relativo próximo de "foto", "imagem",
"galeria" ou seção visual no texto capturado.
Exemplos de texto que confirmam data: "há 8 meses", "há 2 anos", "há 3 semanas".

- Data encontrada próxima de seção de fotos:
  `foto_data_mais_recente: "há 8 meses"`, `foto_data_confirmada: true`
- Seção de fotos existe no texto mas sem data legível:
  `foto_data_mais_recente: null`, `foto_data_confirmada: false`
- Seção de fotos não aparece no texto:
  `foto_data_mais_recente: null`, `foto_data_confirmada: false`

**Importante:** `foto_data_confirmada: false` é o caso mais comum — a maioria
dos perfis não expõe a data da foto em texto. Isso é esperado e não deve ser
tratado como falha de coleta.

### avaliacoes_respondidas_5 e avaliacoes_ordem

Contar ocorrências de "Resposta do proprietário" (ou "Resposta da empresa",
"Resposta do dono") nas primeiras 5 avaliações visíveis no texto do perfil.

- `avaliacoes_respondidas_5`: número de 0 a 5 (ou 0 ao `total_avaliacoes_visiveis`
  se menos de 5 estiverem visíveis)
- `total_avaliacoes_visiveis`: quantas avaliações apareceram no texto (para
  saber se eram 5 ou menos)
- `avaliacoes_ordem`: **sempre `"relevantes"`** nesta skill — nunca reordenar
  para "Mais recentes". (Ver nota no CLAUDE.md sobre a assimetria de custo entre
  esta fase e o `coletar-perfis`.)

Se nenhuma avaliação aparecer no texto do perfil:
`avaliacoes_respondidas_5: null`, `total_avaliacoes_visiveis: 0`

---

## Formato exato do arquivo de saída

```json
{
  "execucao_id": "<execucao_id>",
  "keyword": "<keyword>",
  "cidade": "<cidade>",
  "timestamp": "<ISO 8601, ex: 2026-08-04T10:00:00>",
  "url_busca": "https://www.google.com/maps/search/advogado+Campinas?hl=pt-BR",
  "total_cards_organicos": 18,
  "cards": [
    {
      "posicao_maps": 1,
      "nome": "Escritório Exemplo Advogados",
      "endereco": "Rua das Flores, 123 - Centro, Campinas - SP",
      "telefone": "(19) 99999-9999",
      "site": "exemploadvogados.com.br",
      "instagram": "@exemploadvogados",
      "avaliacoes": 47,
      "nota": 4.7,
      "tem_whatsapp": true,
      "data_ultimo_post": "há 3 meses",
      "tem_produtos": true,
      "descricao": "Escritório especializado em direito trabalhista e previdenciário.",
      "foto_data_mais_recente": "há 8 meses",
      "foto_data_confirmada": true,
      "avaliacoes_respondidas_5": 3,
      "total_avaliacoes_visiveis": 5,
      "avaliacoes_ordem": "relevantes",
      "url_perfil_maps": "https://www.google.com/maps/place/Escritório+Exemplo/@..."
    }
  ]
}
```

---

## O que esta skill nunca faz
- Não classifica nenhum dos 9 sinais do GMN — o Python compara com os
  limites do `config.yaml` e decide
- Não reordena avaliações para "Mais recentes" — `avaliacoes_ordem` é sempre
  `"relevantes"` (ver assimetria documentada no CLAUDE.md)
- Não usa `&near=` na URL do Maps — a cidade fica no termo de busca
- Não usa screenshot como fonte de dado — `get_page_text` é a fonte primária
- Não inclui cards patrocinados na contagem de posição nem no arquivo de saída
- Não inventa dado: campo não encontrado fica `null`, nunca estimado
- Não segue em frente se a navegação falhar — para e reporta o erro

## Se a extensão do Chrome pedir verificação "não sou um robô"
Parar imediatamente. Não tentar contornar. Gravar o que já foi coletado
até aquele ponto (cards com dados completos) como rodada parcial e reportar:
```json
{ "ok": false, "erro": "bloqueio_captcha", "etapa": "coleta_maps",
  "cards_coletados_ate_aqui": N }
```
e aguardar instrução.
