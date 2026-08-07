# Agente de Prospecção SEO + GEO + GMN

Encontra empresas que estão perdendo busca para concorrentes bem posicionados — e entrega, para cada uma, um diagnóstico nas três frentes (SEO, posição orgânica; GEO, presença no AI Overview; GMN, perfil no Google Meu Negócio) mais um link de WhatsApp com mensagem pronta para você clicar e enviar.

Você faz a busca digitando uma palavra-chave e uma cidade. O agente cuida do resto: navega no Google e no Maps, coleta os candidatos, aplica os critérios de qualificação e grava tudo numa planilha (`leads.csv`) na mesma pasta.

---

## O que você precisa ter

| O quê | Por quê |
|---|---|
| **Claude Pro ou Max** | O agente roda dentro do Claude Code, que exige assinatura paga |
| **Claude Code instalado** | A ferramenta de agentes da Anthropic — funciona tanto pelo terminal quanto pelo aplicativo com janela. **Atenção:** não confundir com o "Claude Desktop" (produto diferente, sem "Code" no nome) — o Claude Desktop **não** funciona com este plugin |
| **Extensão Claude in Chrome** | Permite que o agente navegue no Google e no Maps pelo seu Chrome |
| **Ubersuggest conectado ao Claude** | Fonte principal de tráfego e autoridade de domínio |
| **Semrush conectado ao Claude** | Fonte de backup quando o Ubersuggest não tem o dado |
| **Python 3.11 ou mais novo** | Para rodar os scripts de processamento — veja a pergunta frequente abaixo |

Se você já tem Claude Pro ou Max e o Claude Code instalado, a extensão do Chrome é instalada em um clique direto dentro do aplicativo.

---

## Como baixar

1. Clique no botão verde **"Code"** no canto superior direito desta página
2. Clique em **"Download ZIP"**
3. Quando o download terminar, extraia o ZIP numa pasta onde você vai trabalhar — por exemplo, `Documentos/agente-prospeccao`
4. Abra essa pasta pelo Claude Code

---

## Como abrir no Claude Code

1. Abra o Claude Code (o ícone fica na barra de tarefas ou no menu de aplicativos)
2. Clique em **"Open Folder"** (ou Arquivo → Abrir pasta)
3. Selecione a pasta onde você extraiu o ZIP — a que contém `config.yaml`, `CLAUDE.md` e a pasta `scripts/`
4. Pronto. O agente já lê as instruções do `CLAUDE.md` automaticamente — e o comando `/prospeccao-de-leads` já aparece no autocomplete assim que a pasta é aberta, sem nenhuma instalação adicional

---

## Como usar

Digite o comando abaixo na caixa de mensagem do Claude Code:

```
/prospeccao-de-leads
```

O agente vai perguntar a keyword e a cidade. Você também pode passar os dois direto:

```
/prospeccao-de-leads contador em São Paulo
/prospeccao-de-leads advogado em Campinas
/prospeccao-de-leads encanador em Recife
```

Aguarde enquanto ele navega no Google e no Maps. Quando terminar, os leads estarão gravados no arquivo `leads.csv` dentro da sua pasta — abre no Excel ou no Google Sheets.

### Antes da primeira rodada

Abra o arquivo `config.yaml` num editor de texto simples (Bloco de Notas funciona) e preencha os campos `remetente` e `ancoras`:

```yaml
remetente:
  nome: "Maria Silva"        # seu nome, como vai aparecer na mensagem
  agencia: "Agência Visível" # nome da sua agência

ancoras:
  SEO: "auditoria de SEO gratuita"   # o serviço que você oferece pra quem está mal no Google orgânico
  GEO: "análise de presença no AI"   # o serviço para quem não aparece no AI Overview
  GMN: "otimização do Google Meu Negócio" # o serviço para quem tem perfil fraco no Maps
```

A **âncora** é o serviço da sua agência que abre a conversa — o agente escolhe qual das três usar dependendo de onde o lead tem mais a ganhar. Sem preencher esses campos, as mensagens de WhatsApp saem com espaço em branco no lugar do nome e da oferta.

---

## Perguntas frequentes

**Preciso instalar Python?**
Sim. O agente usa scripts Python para processar os dados coletados. Baixe o Python em python.org — escolha a versão 3.11 ou mais nova e marque a opção "Add Python to PATH" durante a instalação. Se o agente avisar que o Python não foi encontrado, é só instalar e tentar de novo.

**Preciso configurar as chaves do Ubersuggest e do Semrush?**
Sim — e os dois exigem **conta paga nesses serviços, contratada diretamente com eles** (fora do Claude). A conexão com o Claude só funciona depois de você já ter a conta ativa. Uma vez com a conta, a conexão é feita dentro do Claude Code em Configurações → MCP Servers — não é uma chave colada em arquivo. O agente avisa no pré-voo se alguma das duas não estiver respondendo.

**Funciona no celular?**
Não. O agente precisa navegar no Chrome do seu computador — a extensão Claude in Chrome não existe em celular. Windows e Mac são suportados.

**O que fazer se der erro?**
O agente sempre explica o que deu errado em português — sem mensagem de erro crua em inglês. Se ele parar no meio de uma rodada (bloqueio de verificação do Google, por exemplo), ele salva o que já coletou e avisa. Você pode rodar de novo que ele continua de onde parou.

**Os leads do piloto ficam misturados com os meus?**
Não. A pasta `coletas/` e o arquivo `leads.csv` ficam na sua pasta local — nunca são enviados para nenhum lugar. Cada agência que baixar o ZIP tem a própria cópia, completamente separada.

**Posso compartilhar a pasta com outra pessoa da equipe?**
Pode, mas tome cuidado com o `leads.csv` — ele contém telefone, e-mail e nome de empresas reais. Não sobe isso para um repositório público nem envia por canais não seguros.

---

## Estrutura da pasta

```
agente-prospeccao/
├── config.yaml          ← preencha remetente e ancoras antes de usar
├── lista_exclusao.yaml  ← sites para ignorar (diretórios, redes sociais)
├── CLAUDE.md            ← instruções completas do agente (não apague)
├── scripts/             ← scripts Python — não precisa abrir ou editar
├── skills/              ← skills do agente — não precisa abrir ou editar
└── leads.csv            ← criado automaticamente na primeira rodada
```

---

Dúvidas ou sugestões: abra uma issue neste repositório.
