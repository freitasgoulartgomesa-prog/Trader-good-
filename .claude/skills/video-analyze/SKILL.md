# Skill: video-analyze

Analisa qualquer vídeo do YouTube — metadados, transcrição e análise visual.
Funciona no **iPhone via browser** e no **PC local**.

---

## Como funciona por ambiente

| Ambiente | Modo | Tempo | O que precisa |
|---|---|---|---|
| iPhone + Gemini | Análise direta via API | ~30s | `GEMINI_API_KEY` |
| iPhone sem Gemini | GitHub Actions via MCP | ~3 min | secrets no repo |
| PC local | Processamento completo | ~2 min | `.env` configurado |

---

## Setup (única vez)

### 1. Dependências no PC
```bash
bash scripts/setup_video_skill.sh
```

### 2. Arquivo `.env` (PC local)
```
YOUTUBE_API_KEY=...   # console.cloud.google.com — YouTube Data API v3
GEMINI_API_KEY=...    # aistudio.google.com — grátis, análise rápida no iPhone
GROQ_API_KEY=...      # console.groq.com — grátis, Whisper (só PC local)
```

### 3. Secrets no GitHub (para iPhone via Actions ou Gemini)
Acesse: `github.com/freitasgoulartgomesa-prog/Trader-good-/settings/secrets/actions`

Adicione:
- `YOUTUBE_API_KEY`
- `GEMINI_API_KEY` ← principal, habilita modo rápido no iPhone
- `GROQ_API_KEY` ← opcional, só usado no GitHub Actions

---

## Como usar

```
/video-analyze <URL_DO_YOUTUBE>
```

---

## Fluxo completo

### Passo 1 — Detectar ambiente
```bash
python3 scripts/video_processor.py "<URL>" --frames 8
```

O script imprime `JSON_ENV:{...}` com o ambiente detectado.

---

### Caminho A: iPhone + Gemini (`can_use_gemini: true`) ← MAIS RÁPIDO

O script já rodou `video_gemini.py` internamente e imprimiu `JSON_RESULT:{...}`.

Parse o JSON_RESULT. Leia os arquivos:
- `info_json` → metadados (título, canal, duração, views)
- `analysis` → `gemini_analysis.json` com transcript, visual_summary, key_topics

```bash
# O script já faz tudo, apenas leia os resultados:
# JSON_RESULT impresso pelo próprio video_processor.py
```

Após ler os arquivos, sintetize:
- **Contexto** — título, canal, duração, views
- **Conteúdo** — resumo da transcrição (`transcript`)
- **Visual** — o que aparece na tela (`visual_summary`)
- **Tópicos-chave** — `key_topics`
- **Insights** — relevantes ao objetivo do usuário

---

### Caminho B: iPhone sem Gemini (`USE_MCP_ACTIONS` impresso)

#### Passo B1 — Disparar GitHub Action via MCP
Use `mcp__github__actions_run_trigger`:
- `owner`: `freitasgoulartgomesa-prog`
- `repo`: `Trader-good-`
- `workflow_id`: `video_analyze.yml`
- `ref`: `claude/oi-gk0t6s`
- `inputs`: `{"video_url": "<URL>", "frames": "8", "ref_branch": "claude/oi-gk0t6s"}`

#### Passo B2 — Aguardar conclusão
Espere 60s e verifique com `mcp__github__actions_list`:
- `owner`: `freitasgoulartgomesa-prog`
- `repo`: `Trader-good-`

Repita a cada 30s até `status: completed` e `conclusion: success`.

#### Passo B3 — Ler resultados via MCP
Use `mcp__github__get_file_contents`:
- `owner`: `freitasgoulartgomesa-prog`
- `repo`: `Trader-good-`
- `path`: `video_results/<VIDEO_ID>/summary.json`
- `branch`: `claude/oi-gk0t6s`

Leia também `info.json`, `transcript.txt` e cada frame listado no summary.

Para imagens (frames, thumbnail): conteúdo em base64 — decodifique, salve em `/tmp/` e leia com o Read tool para análise visual.

#### Passo B4 — Sintetizar
Mesmo formato do Caminho A.

---

### Caminho C: PC local (`is_sandbox: false`)

O script processa tudo localmente e imprime `JSON_RESULT:{...}`.

Leia os arquivos locais: `info_json`, `transcript`, `frames` (lista de paths), `thumbnail`.

---

## Parâmetros

| Parâmetro | Quando usar |
|---|---|
| `--frames 3` | Shorts (<3 min) |
| `--frames 8` | Padrão — tutoriais, podcasts, análises |
| `--frames 12` | Vídeos muito visuais (gráficos, demos) |
| `--frames 20` | Análise profunda (documentários) |

*Nota: frames são usados apenas nos Caminhos B e C. O Gemini (Caminho A) analisa o vídeo inteiro de forma contínua.*

---

## Limitações (Fase 1)

- Somente YouTube (outras plataformas chegam na Fase 2)
- Vídeos privados ou com restrição de idade não funcionam
- Gemini: suporta vídeos de até ~1 hora
- GitHub Actions: processamento leva 2-5 minutos
