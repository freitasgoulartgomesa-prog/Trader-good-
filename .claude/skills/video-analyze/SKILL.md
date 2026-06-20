# Skill: video-analyze

Analisa qualquer vídeo a partir de uma URL, extraindo metadados, transcrição e frames visuais.

## Setup (primeira vez)

Antes de usar, instale as dependências rodando:

```bash
bash scripts/setup_video_skill.sh
```

Ou manualmente:
```bash
pip install yt-dlp "imageio[ffmpeg]"
```

## Trigger

Invocada quando o usuário usa `/video-analyze <URL>` ou pede para "analisar", "assistir", "ver" ou "entender" um vídeo e fornece uma URL.

## Como executar

### Passo 1 — Rodar o processador

```bash
python3 scripts/video_processor.py "<URL>" --frames 8
```

- Substitua `<URL>` pela URL fornecida pelo usuário.
- O argumento `--frames` define quantos frames visuais capturar (padrão: 8). Aumente para vídeos muito visuais, diminua para podcasts/aulas.
- A saída vai para `/tmp/video_analysis/<hash>/`.

### Passo 2 — Coletar os caminhos

A última linha de saída do script começa com `JSON_RESULT:` e contém um JSON com os caminhos:
- `info_json` — metadados completos
- `transcript` — transcrição em texto (pode ser null)
- `frames` — lista de imagens extraídas

### Passo 3 — Ler os arquivos

1. Leia `info.json` com o Read tool para obter título, duração, descrição, etc.
2. Se `transcript` não for null, leia o arquivo de transcrição com o Read tool.
3. Leia cada frame com o Read tool (Claude processa imagens diretamente).

### Passo 4 — Sintetizar e responder

Com base no que foi lido, responda ao usuário com:

- **Título e contexto geral** do vídeo
- **Resumo do conteúdo** (via transcrição, se disponível)
- **Análise visual** dos frames (o que aparece em cena, texto na tela, gráficos, etc.)
- **Informações relevantes** ao objetivo do usuário (se ele pediu algo específico)

## Comportamento por tipo de conteúdo

| Tipo de vídeo | Foco principal |
|---|---|
| Tutorial / aula | Transcrição + frames de código/slides |
| Notícia / podcast | Transcrição (frames menos importantes) |
| Vídeo mudo / visual | Análise de frames (transcrição ausente) |
| Short / Reels | Poucos frames (3-5), foco visual |
| Documentário | Transcrição + frames de gráficos/mapas |

## Notas importantes

- Vídeos privados, com DRM (Netflix, Disney+) ou restrição regional podem não funcionar.
- Para vídeos muito longos (>1h), considere pedir ao usuário um trecho específico com `--frames 12`.
- O script remove o arquivo de vídeo após extrair os frames para economizar espaço em disco.
- Legendas automáticas do YouTube (mesmo sem legenda manual) geralmente estão disponíveis.

## Exemplo de uso

```
/video-analyze https://www.youtube.com/watch?v=XXXXXXXXXXX
```

Ou com mais frames para vídeo muito visual:
```bash
python3 scripts/video_processor.py "https://..." --frames 15
```
