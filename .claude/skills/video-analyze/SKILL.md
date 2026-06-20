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

### 2. Configurar o arquivo `.env`
```
YOUTUBE_API_KEY=...     # obrigatório — console.cloud.google.com
GROQ_API_KEY=...        # recomendado — console.groq.com (grátis)
GITHUB_TOKEN=...        # obrigatório para iPhone — github.com/settings/tokens
GITHUB_REPO=freitasgoulartgomesa-prog/Trader-good-
GITHUB_BRANCH=claude/oi-gk0t6s
```

**Como criar o GITHUB_TOKEN:**
1. Acesse github.com/settings/tokens → "Generate new token (classic)"
2. Marque os escopos: `repo` e `workflow`
3. Cole no `.env`

### 3. Configurar secrets no repositório GitHub (para o Action)
Acesse: github.com/freitasgoulartgomesa-prog/Trader-good-/settings/secrets/actions

Adicione dois secrets:
- `YOUTUBE_API_KEY` — a mesma chave do `.env`
- `GROQ_API_KEY` — a mesma chave do `.env`

---

## Como usar

```
/video-analyze <URL_DO_YOUTUBE>
```

Exemplos:
```
/video-analyze https://youtu.be/JR1xPUCTr4w
/video-analyze https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

---

## O que fazer após o script completar

### Passo 1 — Parsear o JSON_RESULT
A última linha da saída contém `JSON_RESULT:{...}` com os caminhos:
- `info_json`  — metadados
- `transcript` — transcrição (null se indisponível)
- `frames`     — lista de caminhos de imagens
- `thumbnail`  — capa do vídeo

### Passo 2 — Ler os arquivos
1. Leia `info_json` com o Read tool
2. Se `transcript` não for null, leia o arquivo de transcrição
3. Leia cada frame da lista `frames` com o Read tool (Claude vê imagens)
4. Se `thumbnail` não for null, leia a capa

### Passo 3 — Sintetizar
Responda com:
- **Contexto** — título, canal, duração, views, likes
- **Resumo** — baseado na transcrição
- **Análise visual** — o que aparece nos frames
- **Insights** — relevantes ao objetivo do usuário

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
