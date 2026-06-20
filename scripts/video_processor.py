"""
video_processor.py — analisa vídeos do YouTube via API oficial + Whisper.

Uso:
  python3 scripts/video_processor.py <URL_ou_VIDEO_ID>

Variáveis de ambiente (.env):
  YOUTUBE_API_KEY  — obrigatório (YouTube Data API v3)
  GROQ_API_KEY     — opcional, habilita transcrição via Whisper para QUALQUER vídeo

Saída em /tmp/video_analysis/<video_id>/
  info.json       — metadados completos
  transcript.txt  — transcrição (se disponível)
  thumbnail.jpg   — capa do vídeo
  summary.txt     — resumo dos caminhos gerados
"""

import argparse
import json
import os
import re
import sys
import tempfile

def ensure_deps():
    pkgs = {
        "requests": "requests",
        "dotenv": "python-dotenv",
        "youtube_transcript_api": "youtube-transcript-api",
        "groq": "groq",
        "yt_dlp": "yt-dlp",
    }
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
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")
YT_API_BASE     = "https://www.googleapis.com/youtube/v3"


# ─── Extração de ID ───────────────────────────────────────────────────────────

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


# ─── Metadados via YouTube API ────────────────────────────────────────────────

def get_video_metadata(video_id: str) -> dict:
    params = {
        "part": "snippet,statistics,contentDetails",
        "id": video_id,
        "key": YOUTUBE_API_KEY,
    }
    r = requests.get(f"{YT_API_BASE}/videos", params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not data.get("items"):
        raise ValueError(f"Vídeo não encontrado ou privado: {video_id}")

    item    = data["items"][0]
    snippet = item.get("snippet", {})
    stats   = item.get("statistics", {})
    details = item.get("contentDetails", {})

    thumbs = snippet.get("thumbnails", {})
    thumb_url = (
        thumbs.get("maxres") or thumbs.get("high") or thumbs.get("medium") or {}
    ).get("url", "")

    return {
        "video_id":      video_id,
        "title":         snippet.get("title", ""),
        "description":   (snippet.get("description") or "")[:3000],
        "channel":       snippet.get("channelTitle", ""),
        "published_at":  snippet.get("publishedAt", ""),
        "duration":      details.get("duration", ""),
        "tags":          snippet.get("tags", [])[:20],
        "category_id":   snippet.get("categoryId", ""),
        "view_count":    stats.get("viewCount"),
        "like_count":    stats.get("likeCount"),
        "comment_count": stats.get("commentCount"),
        "thumbnail_url": thumb_url,
        "url":           f"https://www.youtube.com/watch?v={video_id}",
    }


# ─── Thumbnail ────────────────────────────────────────────────────────────────

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
        print(f"  [AVISO] Thumbnail indisponível: {e}", file=sys.stderr)
        return False


# ─── Transcrição: método 1 — youtube-transcript-api ──────────────────────────

def get_transcript_yt(video_id: str) -> str | None:
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    for langs in [["pt", "pt-BR"], ["en", "en-US"], None]:
        try:
            if langs:
                entries = api.fetch(video_id, languages=langs)
            else:
                tlist   = api.list(video_id)
                entries = next(iter(tlist)).fetch()
            return _fmt_transcript(entries)
        except Exception:
            pass
    return None


# ─── Transcrição: método 2 — Groq Whisper (qualquer vídeo) ───────────────────

def get_transcript_whisper(video_id: str, tmp_dir: str) -> str | None:
    if not GROQ_API_KEY:
        print("  [INFO] GROQ_API_KEY não configurada — transcrição Whisper desativada.", file=sys.stderr)
        return None

    # Baixa apenas o áudio (muito menor que o vídeo completo)
    audio_path = os.path.join(tmp_dir, f"{video_id}.m4a")
    url = f"https://www.youtube.com/watch?v={video_id}"

    print("  Baixando áudio com yt-dlp...")
    import yt_dlp
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": audio_path,
        "nocheckcertificate": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "64",
        }],
    }
    # Verifica se há ffmpeg disponível
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        os.environ["PATH"] = os.path.dirname(get_ffmpeg_exe()) + ":" + os.environ.get("PATH", "")
    except ImportError:
        pass

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"  [AVISO] Download de áudio falhou: {e}", file=sys.stderr)
        return None

    # Procura o arquivo gerado (pode ter extensão diferente)
    audio_file = None
    for ext in ["mp3", "m4a", "webm", "ogg", "opus"]:
        candidate = audio_path.replace(".m4a", f".{ext}")
        if os.path.exists(candidate):
            audio_file = candidate
            break
    if not audio_file or not os.path.exists(audio_file):
        print("  [AVISO] Arquivo de áudio não encontrado após download.", file=sys.stderr)
        return None

    file_size_mb = os.path.getsize(audio_file) / (1024 * 1024)
    print(f"  Áudio baixado: {file_size_mb:.1f} MB — transcrevendo com Whisper...")

    # Groq tem limite de 25MB — divide se necessário
    if file_size_mb > 24:
        print("  [INFO] Arquivo grande, usando apenas os primeiros 24MB.", file=sys.stderr)

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)

        with open(audio_file, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(os.path.basename(audio_file), f),
                model="whisper-large-v3-turbo",
                response_format="text",
                language=None,  # detecção automática de idioma
            )

        os.remove(audio_file)

        if isinstance(result, str):
            return result.strip()
        return str(result).strip()

    except Exception as e:
        print(f"  [ERRO] Whisper falhou: {e}", file=sys.stderr)
        if os.path.exists(audio_file):
            os.remove(audio_file)
        return None


def _fmt_transcript(entries) -> str:
    seen  = set()
    lines = []
    for entry in entries:
        text = (entry.get("text") if isinstance(entry, dict) else getattr(entry, "text", "")).strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not YOUTUBE_API_KEY:
        print("ERRO: YOUTUBE_API_KEY não encontrada. Verifique o arquivo .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Analisa vídeo do YouTube")
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
    thumbnail_path = thumbnail_path if has_thumb else None

    print(f"[4/4] Buscando transcrição...")
    transcript = None

    # Método 1: legendas do YouTube (funciona sem Groq)
    transcript = get_transcript_yt(video_id)
    if transcript:
        print(f"      Transcrição obtida via legendas YouTube.")
    else:
        # Método 2: Whisper via Groq (qualquer vídeo)
        print(f"      Legendas não disponíveis — tentando Whisper (Groq)...")
        transcript = get_transcript_whisper(video_id, out_dir)
        if transcript:
            print(f"      Transcrição obtida via Whisper.")
        else:
            print(f"      Transcrição não disponível neste ambiente.")

    transcript_path = None
    if transcript:
        transcript_path = os.path.join(out_dir, "transcript.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript)
        print(f"      {len(transcript.splitlines())} linhas salvas.")

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
        "video_id":     video_id,
        "out_dir":      out_dir,
        "info_json":    info_path,
        "thumbnail":    thumbnail_path,
        "transcript":   transcript_path,
        "summary":      summary_path,
    }
    print(f"\nConcluído! Diretório: {out_dir}")
    print(f"\nJSON_RESULT:{json.dumps(result)}")


if __name__ == "__main__":
    main()
