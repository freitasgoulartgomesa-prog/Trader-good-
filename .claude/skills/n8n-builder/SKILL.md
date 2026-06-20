# Skill: n8n-builder

Constrói automações no n8n usando o MCP oficial — nó a nó, testando cada etapa.
Requer que o MCP n8n esteja configurado no Claude Code (ver setup abaixo).

---

## Quando usar

```
/n8n-builder
```

Invoque depois de ter o PRD da automação (use `/prd-generator` primeiro).
Cole o PRD na mesma mensagem para iniciar a construção.

---

## Princípio fundamental (DO NOT SKIP)

**Nunca construir o workflow inteiro de uma vez.**

O processo correto é idêntico ao que um desenvolvedor faz manualmente:
1. Cria um nó
2. Testa esse nó isoladamente
3. Corrige se necessário
4. Avança para o próximo nó

Isso garante que cada parte funciona antes de adicionar complexidade.

---

## Ferramentas MCP disponíveis (25 ações)

Quando o MCP n8n estiver conectado, você terá acesso a:

**Workflows**
- `create_workflow` — cria workflow a partir de JSON
- `update_workflow` — atualiza workflow existente
- `activate_workflow` / `deactivate_workflow` — publica/desativa
- `delete_workflow` — remove
- `get_workflow` — lê estrutura de um workflow
- `list_workflows` — lista todos os workflows

**Execuções e debug**
- `execute_workflow` — roda manualmente
- `get_execution` — detalhes de uma execução (inclui logs de erro)
- `list_executions` — histórico de execuções

**Nós e credenciais**
- `list_nodes` — lista tipos de nós disponíveis
- `get_node_types` — detalhes de um tipo de nó
- `list_credentials` — lista credenciais cadastradas

---

## Processo de construção (siga sempre esta ordem)

### Passo 1 — Leia o PRD
Extraia: trigger, lista de nós necessários, credenciais, outputs esperados.

### Passo 2 — Liste as credenciais necessárias
Verifique com `list_credentials` quais já existem.
Se faltar alguma, informe o usuário antes de começar:
> "Você precisará configurar manualmente: [lista de credenciais]"

### Passo 3 — Construa nó a nó

Para cada nó:
1. Crie ou atualize o workflow com o novo nó
2. Execute o workflow (ou o nó isolado) com dados de teste
3. Verifique o resultado com `get_execution`
4. Se erro: leia o log, corrija, teste novamente
5. Só avance quando este nó funcionar

### Passo 4 — Ative o workflow
Quando todos os nós estiverem funcionando, use `activate_workflow`.

### Passo 5 — Informe o usuário
Liste:
- Link do workflow no n8n
- Passos de configuração manual pendentes (webhooks, IDs de campos, etc.)
- Como testar em produção

---

## Nós mais usados no contexto Trader-good

### Triggers
| Nó | Uso |
|----|-----|
| Schedule Trigger | Executar em horário fixo (ex: relatório diário 18h) |
| Webhook | Receber dados externos (ex: sinal do TradingView) |
| HTTP Request (poll) | Verificar API a cada X minutos |

### Agentes de IA
| Nó | Uso |
|----|-----|
| AI Agent | Agente autônomo com ferramentas |
| OpenAI / Anthropic | Chamada direta de LLM |
| Text Classifier | Classificar texto em categorias |

### Integrações de trading
| Nó | Uso |
|----|-----|
| HTTP Request | Binance, Bybit, qualquer REST API |
| Google Sheets | Salvar histórico de operações |
| Telegram | Enviar alertas ao trader |
| Slack | Notificações de equipe |

### Processamento
| Nó | Uso |
|----|-----|
| Code (JS/Python) | Cálculos customizados, indicadores |
| IF / Switch | Lógica condicional |
| Set | Preparar dados para o próximo nó |
| Merge | Combinar múltiplas branches |

---

## Regras de qualidade

- Sempre adicione um nó de tratamento de erro em workflows críticos
- Use variáveis de ambiente do n8n para tokens e senhas (nunca hardcode)
- Documente o objetivo de cada nó no campo "Notes" do n8n
- Para agentes de IA: escreva o system prompt completo, não use defaults

---

## Setup do MCP n8n no Claude Code

Para usar este skill com as ferramentas MCP reais, adicione ao `.claude/settings.json`:

```json
{
  "mcpServers": {
    "n8n": {
      "type": "sse",
      "url": "SEU-N8N-URL/mcp/sse",
      "headers": {
        "Authorization": "Bearer SEU-TOKEN"
      }
    }
  }
}
```

Para obter URL e token: no n8n → Settings → API → Instance-level MCP.

**Sem o MCP configurado:** este skill funciona no modo planejamento — gera o JSON
do workflow para você importar manualmente no n8n via Settings → Import.
