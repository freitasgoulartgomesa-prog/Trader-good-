# Skill: video-analyze — Fase 1

Analisa qualquer vídeo do YouTube extraindo metadados, transcrição e frames visuais.

## Setup (primeira vez)

```bash
bash scripts/setup_video_skill.sh
```

Preencha o arquivo `.env` na raiz do projeto:
```
YOUTUBE_API_KEY=...   # obrigatório — console.cloud.google.com
GROQ_API_KEY=...      # recomendado — console.groq.com (gratuito)
```

---

## Como executar

### Passo 1 — Rodar o processador

```bash
python3 scripts/video_processor.py "<URL>" --frames 8
```

Parâmetros de `--frames`:
| Valor | Quando usar |
|---|---|
| `3` | Shorts, clips curtos (<3 min) |
| `8` | Padrão — tutoriais, podcasts, análises |
| `12` | Vídeos muito visuais (gráficos, comparações) |
| `20` | Análise profunda (documentários, aulas longas) |

### Passo 2 — Ler o resultado

A última linha começa com `JSON_RESULT:` — parse o JSON para obter os caminhos:
- `info_json`  — metadados completos
- `transcript` — transcrição em texto (pode ser null)
- `frames`     — lista de imagens extraídas (pode ser lista vazia)
- `thumbnail`  — imagem da capa (pode ser null)
- `env`        — quais recursos estavam disponíveis

### Passo 3 — Ler os arquivos com Read tool

1. Leia `info.json` para título, canal, duração, views, likes, descrição, tags.
2. Se `transcript` não for null, leia o arquivo. Pode ser longo — leia em blocos se necessário.
3. Leia cada frame com o Read tool (Claude processa imagens diretamente).
4. Se `thumbnail` não for null, leia a imagem da capa.

### Passo 4 — Sintetizar e responder

Com base no que foi lido, responda com:

- **Contexto geral** — título, canal, data, estatísticas de engajamento
- **Resumo do conteúdo** — baseado na transcrição (se disponível)
- **Análise visual** — o que aparece nos frames (gráficos, texto, padrões)
- **Insights relevantes** — ao objetivo específico do usuário

---

## Compatibilidade por ambiente

| Recurso | PC local | Cloud sandbox (iPhone/browser) |
|---|---|---|
| Metadados | ✅ | ✅ |
| Thumbnail | ✅ | ❌ (bloqueado) |
| Transcrição (legendas) | ✅ | ❌ (bloqueado) |
| Transcrição (Whisper) | ✅ (requer GROQ_API_KEY) | ❌ (bloqueado) |
| Frames visuais | ✅ | ❌ (bloqueado) |

> No sandbox cloud, apenas metadados ficam disponíveis.
> Para análise completa, execute no PC local.

---

## Limitações conhecidas (Fase 1)

- **Somente YouTube** — outras plataformas chegam na Fase 2
- **Vídeos privados ou com restrição de idade** — não funcionam
- **Vídeos muito longos (>2h)** — áudio é dividido automaticamente em chunks; transcrição completa pode levar alguns minutos
- **DRM** (Netflix, Disney+, etc.) — impossível em qualquer ferramenta

---

## Exemplos de uso

```
/video-analyze https://www.youtube.com/watch?v=XXXXXXXXXXX
```

Com mais frames para vídeo de análise técnica:
```
/video-analyze https://youtu.be/XXXXXXXXXXX --frames 12
```
