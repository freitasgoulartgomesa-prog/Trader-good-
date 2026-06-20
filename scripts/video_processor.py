"""
video_processor.py — analisa vídeos do YouTube via API oficial.

Uso:
  python3 scripts/video_processor.py <URL_ou_VIDEO_ID>

Requer:
  YOUTUBE_API_KEY no arquivo .env (raiz do projeto)

Saída em /tmp/video_analysis/<video_id>/
  info.json       — metadados completos
  transcript.txt  — transcrição (se disponível)
  thumbnail.jpg   — imagem de capa
  summary.txt     — resumo dos caminhos gerados
"""

import argparse
import json
import os
import re
import sys

# Instala dependências se necessário
def ensure_deps():
    pkgs = {"requests": "requests", "dotenv": "python-dotenv", "youtube_transcript_api": "youtube-transcript-api"}
    for imp, pkg in pkgs.items():
        try:
            __import__(imp)
        except ImportError:
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

ensure_deps()

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YT_API_BASE = "https://www.googleapis.com/youtube/v3"


def extract_video_id(url_or_id: str) -> str:
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for p in patterns:
        m = re.search(p, url_or_id)
        if m:
            return m.group(1)
    raise ValueError(f"Não foi possível extrair o ID do vídeo de: {url_or_id}")


def get_video_metadata(video_id: str) -> dict:
    url = f"{YT_API_BASE}/videos"
    params = {
        "part": "snippet,statistics,contentDetails",
        "id": video_id,
        "key": YOUTUBE_API_KEY,
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not data.get("items"):
        raise ValueError(f"Vídeo não encontrado ou privado: {video_id}")

    item = data["items"][0]
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    details = item.get("contentDetails", {})

    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", "")[:2000],
        "channel": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt", ""),
        "duration": details.get("duration", ""),
        "tags": snippet.get("tags", [])[:20],
        "category_id": snippet.get("categoryId", ""),
        "view_count": stats.get("viewCount"),
        "like_count": stats.get("likeCount"),
        "comment_count": stats.get("commentCount"),
        "thumbnail_url": (
            snippet.get("thumbnails", {}).get("maxres") or
            snippet.get("thumbnails", {}).get("high") or
            snippet.get("thumbnails", {}).get("medium") or
            {}
        ).get("url", ""),
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


def download_thumbnail(url: str, out_path: str) -> bool:
    if not url:
        return False
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        print(f"  [AVISO] Thumbnail não baixada: {e}", file=sys.stderr)
        return False


def get_transcript(video_id: str) -> str | None:
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()

    # Tenta PT primeiro, depois EN, depois qualquer idioma disponível
    for langs in [["pt", "pt-BR"], ["en", "en-US"], None]:
        try:
            if langs:
                entries = api.fetch(video_id, languages=langs)
            else:
                transcript_list = api.list(video_id)
                entries = next(iter(transcript_list)).fetch()
            return _format_transcript(entries)
        except Exception:
            pass

    return None


def _format_transcript(entries) -> str:
    seen = set()
    lines = []
    for entry in entries:
        text = entry.get("text", "").strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return "\n".join(lines)


def main():
    if not YOUTUBE_API_KEY:
        print("ERRO: YOUTUBE_API_KEY não encontrada. Verifique o arquivo .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Analisa vídeo do YouTube via API")
    parser.add_argument("url", help="URL ou ID do vídeo YouTube")
    parser.add_argument("--out", default="/tmp/video_analysis", help="Diretório de saída")
    args = parser.parse_args()

    print(f"[1/4] Extraindo ID do vídeo...")
    video_id = extract_video_id(args.url)
    print(f"      ID: {video_id}")

    out_dir = os.path.join(args.out, video_id)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[2/4] Buscando metadados via YouTube API...")
    info = get_video_metadata(video_id)
    print(f"      Título: {info['title']}")
    print(f"      Canal:  {info['channel']} | Duração: {info['duration']}")

    info_path = os.path.join(out_dir, "info.json")
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"[3/4] Baixando thumbnail...")
    thumbnail_path = os.path.join(out_dir, "thumbnail.jpg")
    has_thumb = download_thumbnail(info["thumbnail_url"], thumbnail_path)
    if has_thumb:
        print(f"      Thumbnail salva.")
    else:
        thumbnail_path = None

    print(f"[4/4] Buscando transcrição...")
    transcript = get_transcript(video_id)
    transcript_path = None
    if transcript:
        transcript_path = os.path.join(out_dir, "transcript.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript)
        print(f"      Transcrição salva ({len(transcript.splitlines())} linhas).")
    else:
        print(f"      Transcrição não disponível para este vídeo.")

    # summary.txt
    summary_path = os.path.join(out_dir, "summary.txt")
    with open(summary_path, "w") as f:
        f.write(f"ANÁLISE DE VÍDEO\n")
        f.write(f"URL: {args.url}\n")
        f.write(f"ID:  {video_id}\n\n")
        f.write(f"ARQUIVOS:\n")
        f.write(f"  info.json:   {info_path}\n")
        if thumbnail_path:
            f.write(f"  thumbnail:   {thumbnail_path}\n")
        if transcript_path:
            f.write(f"  transcript:  {transcript_path}\n")

    result = {
        "video_id": video_id,
        "out_dir": out_dir,
        "info_json": info_path,
        "thumbnail": thumbnail_path,
        "transcript": transcript_path,
        "summary": summary_path,
    }
    print(f"\nConcluído! Diretório: {out_dir}")
    print(f"\nJSON_RESULT:{json.dumps(result)}")


if __name__ == "__main__":
    main()
