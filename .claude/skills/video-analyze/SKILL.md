# Skill: video-analyze

Analisa qualquer vídeo do YouTube — metadados, transcrição e frames visuais.
Funciona tanto no **iPhone via browser** quanto no **PC local**.

---

## Como funciona por ambiente

### iPhone / browser (claude.ai/code)
Claude detecta que está no sandbox e **dispara um GitHub Action automaticamente**.
O Action roda num servidor com internet completa, processa o vídeo e commita
os resultados no repositório. Claude lê os arquivos e faz a análise.

### PC local
Claude processa tudo diretamente no seu computador.

---

## Setup (única vez)

### 1. Instalar dependências (PC)
```bash
bash scripts/setup_video_skill.sh
```

### 2. Configurar o arquivo `.env` (PC local)
```
YOUTUBE_API_KEY=...     # obrigatório — console.cloud.google.com
GROQ_API_KEY=...        # recomendado — console.groq.com (grátis)
```

### 3. Configurar secrets no repositório GitHub (para iPhone via Actions)
Acesse pelo browser: github.com/freitasgoulartgomesa-prog/Trader-good-/settings/secrets/actions

Adicione dois secrets:
- `YOUTUBE_API_KEY` — a mesma chave do `.env`
- `GROQ_API_KEY` — a mesma chave do `.env`

> **Nota:** Não precisa de GITHUB_TOKEN. No iPhone, Claude usa sua
> própria conexão GitHub (MCP) para disparar e monitorar o Action.

---

## Como usar

```
/video-analyze <URL_DO_YOUTUBE>
```

---

## Fluxo no iPhone (sandbox) — usa MCP GitHub diretamente

### Passo 1 — Detectar ambiente
Roda o script para ver o que está disponível:
```bash
python3 scripts/video_processor.py "<URL>" --frames 8
```

Se reportar `is_sandbox: true`, seguir os passos abaixo em vez de esperar o script.

### Passo 2 — Disparar o GitHub Action via MCP
Use a ferramenta `mcp__github__actions_run_trigger` com:
- `owner`: `freitasgoulartgomesa-prog`
- `repo`: `Trader-good-`
- `workflow_id`: `video_analyze.yml`
- `ref`: `claude/oi-gk0t6s`
- `inputs`: `{"video_url": "<URL>", "frames": "8", "ref_branch": "claude/oi-gk0t6s"}`

### Passo 3 — Aguardar conclusão
Espere 60 segundos e verifique o status com `mcp__github__actions_list`:
- `owner`: `freitasgoulartgomesa-prog`
- `repo`: `Trader-good-`

Fique verificando a cada 30s até `status: completed` e `conclusion: success`.

### Passo 4 — Ler os resultados via MCP
Use `mcp__github__get_file_contents` para ler cada arquivo:
- `owner`: `freitasgoulartgomesa-prog`
- `repo`: `Trader-good-`
- `path`: `video_results/<VIDEO_ID>/summary.json`
- `branch`: `claude/oi-gk0t6s`

Depois leia `info.json`, `transcript.txt` e cada frame listado no summary.

Para imagens (frames, thumbnail): o conteúdo vem em base64 — decodifique,
salve em `/tmp/` e leia com o Read tool para análise visual.

### Passo 5 — Sintetizar e responder
Com base em tudo que foi lido:
- **Contexto** — título, canal, duração, views, likes
- **Resumo** — baseado na transcrição
- **Análise visual** — o que aparece nos frames (gráficos, texto, padrões)
- **Insights** — relevantes ao objetivo do usuário

---

## Fluxo no PC local

### Passo 1 — Rodar o processador
```bash
python3 scripts/video_processor.py "<URL>" --frames 8
```

### Passo 2 — Parsear JSON_RESULT
A última linha contém `JSON_RESULT:{...}` com os caminhos locais.

### Passo 3 — Ler arquivos
Use o Read tool para ler `info_json`, `transcript`, cada frame e `thumbnail`.

---

## Parâmetros

| Parâmetro | Padrão | Quando usar |
|---|---|---|
| `--frames 3` | — | Shorts (<3 min) |
| `--frames 8` | ✅ | Tutoriais, análises, podcasts |
| `--frames 12` | — | Vídeos muito visuais (gráficos) |
| `--frames 20` | — | Análise profunda (documentários) |

---

## Limitações (Fase 1)

- Somente YouTube (outras plataformas chegam na Fase 2)
- Vídeos privados ou com restrição de idade não funcionam
- No iPhone, o processamento leva 2-5 minutos (aguarda o GitHub Action)
