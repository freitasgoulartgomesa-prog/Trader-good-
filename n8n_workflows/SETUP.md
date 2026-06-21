# Setup n8n + Claude Code

## Passo 1 — Criar conta n8n

Acesse: https://n8n.io  
→ "Start for free" (14 dias grátis, sem cartão)
→ Crie sua instância cloud

## Passo 2 — Obter URL do MCP

Dentro do n8n:
→ Settings (ícone engrenagem) → API → Instance-level MCP
→ Copie a URL do servidor MCP (formato: https://SUA-INSTANCIA.n8n.cloud/mcp)
→ Gere um token de API se pedido

## Passo 3 — Conectar ao Claude Code

Crie (ou edite) o arquivo `.claude/settings.json` na raiz do projeto:

```json
{
  "mcpServers": {
    "n8n": {
      "type": "sse",
      "url": "https://SUA-INSTANCIA.n8n.cloud/mcp/sse",
      "headers": {
        "Authorization": "Bearer SEU-TOKEN-AQUI"
      }
    }
  }
}
```

## Passo 4 — Importar os workflows de trading

No n8n → Workflows → Import from file
→ Importe os arquivos desta pasta:
   - `alerta_sinal_telegram.json` — alertas de sinal via Telegram
   - `relatorio_diario.json` — relatório diário de P&L às 18h
   - `monitor_posicao.json` — monitor de posição com limite de gain/stop

## Passo 5 — Configurar credenciais e variáveis no n8n

### Credenciais (Settings → Credentials)
- **Telegram:** crie um bot em @BotFather, copie o token

### Variáveis de ambiente (Settings → Variables)
| Variável | Valor |
|----------|-------|
| `TELEGRAM_CHAT_ID` | ID do seu chat (use @userinfobot para obter) |
| `TRADER_API_URL` | URL da API do trader (se tiver endpoint HTTP) |
| `ALERTA_GAIN_PCT` | % de gain para alertar (ex: 3) |
| `ALERTA_LOSS_PCT` | % de perda para alertar (ex: -2) |

## Após configurar

Com o MCP conectado, você pode usar no Claude Code:
- `/prd-generator` — planejar uma nova automação
- `/n8n-builder` — construir o workflow conversando
