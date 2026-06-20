# Skill: prd-generator

Gera um PRD (Product Requirements Document) completo para uma automação no n8n.
Faz perguntas estruturadas e produz um documento de requisitos pronto para o n8n Builder.

---

## Quando usar

Invoque antes de construir qualquer automação no n8n. Garante que o escopo, os
gatilhos, os agentes e os outputs estão bem definidos antes de começar a construir.

```
/prd-generator
```

---

## Fluxo obrigatório

### Rodada 1 — Coleta de contexto (faça todas de uma vez)

Pergunte em uma única mensagem:

1. **O que dispara a automação?** (ex: novo lead no CRM, horário fixo, evento de preço, webhook)
2. **Qual o objetivo final?** (ex: enriquecer dados, enviar alerta, gerar relatório)
3. **Quais sistemas externos?** (ex: Telegram, Slack, Binance, Pipedrive, Google Sheets)
4. **Precisa de agente de IA?** Se sim: qual modelo (GPT-4, Claude) e qual ferramenta de busca/dados

### Rodada 2 — Refinamento (somente se necessário)

Pergunte só o que ficou ambíguo na Rodada 1:
- Frequência (tempo real, a cada X minutos, diário)
- Tratamento de erros (silencioso, notificar, retry)
- Onde salvar resultados (planilha, banco, nota no CRM)

### Produção do PRD

Quando tiver todas as informações, gere o documento em Markdown com estas seções:

```markdown
# PRD — [Nome da Automação]

## Objetivo
[Uma frase clara descrevendo o que a automação resolve]

## Gatilho
[O que dispara o fluxo, com frequência e condições]

## Fluxo de dados
[Lista numerada de cada etapa, do trigger ao output final]

## Integrações
| Sistema | Papel | Credencial necessária |
|---------|-------|-----------------------|
| ...     | ...   | ...                   |

## Agentes de IA (se aplicável)
- **Agente 1 — [Nome]:** [objetivo, modelo, ferramentas]
- **Agente 2 — [Nome]:** [objetivo, modelo, ferramentas]

## Outputs
[O que é criado, enviado ou atualizado ao final]

## Tratamento de erros
[O que fazer em caso de falha em cada etapa crítica]

## Campos e variáveis críticas
[Campos de API, IDs, tokens que precisam ser configurados manualmente]

## Configuração manual necessária
[Passos que o Claude não pode fazer automaticamente]
```

### Após gerar o PRD

Diga ao usuário:
> "PRD pronto. Você pode agora usar `/n8n-builder` e colar este PRD para começar a construção no n8n."

---

## Contexto do projeto Trader-good

Este projeto é um sistema de trading automatizado. Automações comuns aqui incluem:
- Alertas de sinais de compra/venda por preço ou indicador
- Relatórios diários de P&L
- Monitoramento de posições abertas
- Enriquecimento de dados de ativos antes de operar
- Notificações via Telegram quando uma operação é executada
