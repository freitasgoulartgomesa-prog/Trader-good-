"""
video_processor.py — Fase 1: fundação completa da skill video-analyze.

Fase 1 implementa:
  - Detecção de ambiente (sandbox vs PC, com relatório claro)
  - Extração de frames visuais distribuídos uniformemente
  - Chunking automático de áudio para vídeos longos (>25MB no Groq)
  - Transcrição em cascata: legendas YT → Whisper chunked

Uso:
  python3 scripts/video_processor.py <URL_ou_VIDEO_ID> [--frames N]

Variáveis de ambiente (.env):
  YOUTUBE_API_KEY  — obrigatório
  GROQ_API_KEY     — opcional, habilita Whisper para qualquer vídeo

Saída em /tmp/video_analysis/<video_id>/
  info.json       — metadados completos
  transcript.txt  — transcrição
  thumbnail.jpg   — capa
  frames/         — frame_001.jpg ... frame_N.jpg
  summary.txt     — caminhos de todos os arquivos gerados
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys

# ─── Dependências ─────────────────────────────────────────────────────────────

def ensure_deps():
    pkgs = {
        "requests":               "requests",
        "dotenv":                 "python-dotenv",
        "youtube_transcript_api": "youtube-transcript-api",
        "groq":                   "groq",
        "yt_dlp":                 "yt-dlp",
        "isodate":                "isodate",
        "imageio_ffmpeg":         "imageio[ffmpeg]",
    }
    for imp, pkg in pkgs.items():
        try:
            __import__(imp)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

ensure_deps()

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")
YT_API_BASE     = "https://www.googleapis.com/youtube/v3"

# FFmpeg binaries
from imageio_ffmpeg import get_ffmpeg_exe
FFMPEG   = get_ffmpeg_exe()
FFPROBE  = "/usr/bin/ffprobe" if os.path.exists("/usr/bin/ffprobe") else FFMPEG


# ─── Detecção de ambiente ─────────────────────────────────────────────────────

def detect_environment() -> dict:
    """
    Testa conectividade real com cada serviço.
    403 = bloqueado pelo proxy; só 200 e 400 indicam acesso real.
    """
    results = {}

    # YouTube Data API: 400 (bad request com key dummy) = endpoint acessível
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "id", "id": "x", "key": "x"},
            timeout=5,
        )
        results["youtube_api"] = r.status_code in (200, 400)
    except Exception:
        results["youtube_api"] = False

    # YouTube web: 200 = acessível; 403 = bloqueado pelo proxy
    try:
        r = requests.get("https://www.youtube.com", timeout=5)
        results["youtube_web"] = r.status_code == 200
    except Exception:
        results["youtube_web"] = False

    # Groq: 200 ou 401 (sem auth) = endpoint acessível
    try:
        r = requests.get("https://api.groq.com", timeout=5)
        results["groq"] = r.status_code in (200, 401, 404)
    except Exception:
        results["groq"] = False

    # Thumbnail CDN: 200 = acessível
    try:
        r = requests.get("https://i.ytimg.com/favicon.ico", timeout=5)
        results["thumbnail"] = r.status_code == 200
    except Exception:
        results["thumbnail"] = False

    env = {
        "metadata":      results["youtube_api"],
        "thumbnail":     results["thumbnail"],
        "transcript_yt": results["youtube_web"],
        "whisper":       results["youtube_web"] and results["groq"] and bool(GROQ_API_KEY),
        "frames":        results["youtube_web"],
        "raw":           results,
    }

    return env


def report_environment(env: dict):
    lines = ["\n  Ambiente detectado:"]
    icons = {True: "✅", False: "❌"}
    lines.append(f"    {icons[env['metadata']]}  Metadados YouTube API")
    lines.append(f"    {icons[env['thumbnail']]}  Thumbnail")
    lines.append(f"    {icons[env['transcript_yt']]}  Transcrição via legendas")
    lines.append(f"    {icons[env['whisper']]}  Transcrição via Whisper (Groq)")
    lines.append(f"    {icons[env['frames']]}  Extração de frames visuais")

    if not env["transcript_yt"] and not env["whisper"]:
        lines.append("\n  ⚠️  Transcrição indisponível neste ambiente.")
        lines.append("     Execute localmente no PC para transcrição e frames.")

    print("\n".join(lines))


# ─── Utilitários ──────────────────────────────────────────────────────────────

def extract_video_id(url_or_id: str) -> str:
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for p in patterns:
        m = re.search(p, url_or_id)
        if m:
            return m.group(1)
    raise ValueError(f"Não foi possível extrair o ID do vídeo: {url_or_id}")


def parse_iso_duration(duration_iso: str) -> float:
    """PT35M41S → 2141.0 segundos"""
    try:
        import isodate
        return isodate.parse_duration(duration_iso).total_seconds()
    except Exception:
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_iso or "")
        if not m:
            return 0.0
        h = int(m.group(1) or 0)
        mn = int(m.group(2) or 0)
        s = int(m.group(3) or 0)
        return h * 3600 + mn * 60 + s


# ─── Metadados ────────────────────────────────────────────────────────────────

def get_video_metadata(video_id: str) -> dict:
    r = requests.get(
        f"{YT_API_BASE}/videos",
        params={"part": "snippet,statistics,contentDetails", "id": video_id, "key": YOUTUBE_API_KEY},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    if not data.get("items"):
        raise ValueError(f"Vídeo não encontrado ou privado: {video_id}")

    item    = data["items"][0]
    snippet = item.get("snippet", {})
    stats   = item.get("statistics", {})
    details = item.get("contentDetails", {})
    thumbs  = snippet.get("thumbnails", {})
    thumb   = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("medium") or {})

    return {
        "video_id":      video_id,
        "title":         snippet.get("title", ""),
        "description":   (snippet.get("description") or "")[:3000],
        "channel":       snippet.get("channelTitle", ""),
        "published_at":  snippet.get("publishedAt", ""),
        "duration_iso":  details.get("duration", ""),
        "duration_sec":  parse_iso_duration(details.get("duration", "")),
        "tags":          (snippet.get("tags") or [])[:20],
        "category_id":   snippet.get("categoryId", ""),
        "view_count":    stats.get("viewCount"),
        "like_count":    stats.get("likeCount"),
        "comment_count": stats.get("commentCount"),
        "thumbnail_url": thumb.get("url", ""),
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


# ─── Download de vídeo ────────────────────────────────────────────────────────

def download_video(video_id: str, out_path: str) -> bool:
    """
    Baixa vídeo em qualidade baixa (360p) para extração de frames e áudio.
    Um único download serve para ambos os propósitos.
    """
    import yt_dlp
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "quiet":            True,
        "no_warnings":      True,
        "format":           "best[height<=360][ext=mp4]/best[height<=480][ext=mp4]/best[ext=mp4]/best",
        "outtmpl":          out_path,
        "nocheckcertificate": True,
        "merge_output_format": "mp4",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return os.path.exists(out_path)
    except Exception as e:
        print(f"  [ERRO] Download falhou: {e}", file=sys.stderr)
        return False


# ─── Extração de frames ───────────────────────────────────────────────────────

def extract_frames(video_path: str, frames_dir: str, n_frames: int, duration_sec: float) -> list[str]:
    """
    Extrai N frames distribuídos uniformemente ao longo do vídeo.
    Usa ffmpeg do imageio-ffmpeg (sem dependência externa).
    """
    os.makedirs(frames_dir, exist_ok=True)

    if duration_sec <= 0:
        duration_sec = 60.0  # fallback

    # Distribui os timestamps evitando os extremos (início e fim do vídeo)
    margin = min(duration_sec * 0.03, 5.0)
    usable = duration_sec - 2 * margin
    if n_frames == 1:
        timestamps = [duration_sec / 2]
    else:
        timestamps = [margin + usable * i / (n_frames - 1) for i in range(n_frames)]

    frames = []
    for i, ts in enumerate(timestamps):
        out = os.path.join(frames_dir, f"frame_{i+1:03d}.jpg")
        cmd = [
            FFMPEG, "-ss", f"{ts:.2f}", "-i", video_path,
            "-vframes", "1", "-q:v", "2",
            "-vf", "scale=1280:-1",          # máx 1280px de largura
            out, "-y", "-loglevel", "error",
        ]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and os.path.exists(out):
            frames.append(out)

    return frames


# ─── Extração de áudio ────────────────────────────────────────────────────────

def extract_audio(video_path: str, audio_path: str) -> bool:
    """Extrai stream de áudio do vídeo como MP3."""
    cmd = [
        FFMPEG, "-i", video_path,
        "-vn",                    # sem vídeo
        "-acodec", "libmp3lame",
        "-q:a", "5",              # qualidade média (menor = maior qualidade)
        audio_path, "-y", "-loglevel", "error",
    ]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0 and os.path.exists(audio_path)


def get_audio_duration(audio_path: str) -> float | None:
    """Obtém duração do áudio via ffprobe."""
    cmd = [
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(r.stdout.strip())
    except Exception:
        return None


# ─── Transcrição ──────────────────────────────────────────────────────────────

def transcribe_single(audio_path: str) -> str | None:
    """Transcreve um único arquivo de áudio via Groq Whisper."""
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    try:
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f),
                model="whisper-large-v3-turbo",
                response_format="text",
            )
        return str(result).strip() if result else None
    except Exception as e:
        print(f"  [ERRO] Whisper: {e}", file=sys.stderr)
        return None


def transcribe_chunked(audio_path: str, tmp_dir: str, duration_sec: float | None = None) -> str | None:
    """
    Transcreve áudio com chunking automático para arquivos > 24MB.
    Cada chunk < 20MB com margem de sobreposição de 2s para continuidade.
    """
    if not GROQ_API_KEY:
        print("  [INFO] GROQ_API_KEY não configurada.", file=sys.stderr)
        return None

    MAX_MB       = 20.0
    OVERLAP_SEC  = 2.0
    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)

    # Arquivo pequeno — transcreve direto
    if file_size_mb <= MAX_MB:
        print(f"  Transcrevendo {file_size_mb:.1f}MB com Whisper...")
        return transcribe_single(audio_path)

    # Arquivo grande — divide em chunks
    duration = duration_sec or get_audio_duration(audio_path)
    if not duration:
        print("  [ERRO] Não foi possível determinar duração do áudio.", file=sys.stderr)
        return None

    n_chunks     = math.ceil(file_size_mb / MAX_MB)
    chunk_sec    = duration / n_chunks
    print(f"  Áudio de {file_size_mb:.1f}MB → dividindo em {n_chunks} partes de ~{chunk_sec/60:.1f} min...")

    transcripts = []
    for i in range(n_chunks):
        start = max(0, i * chunk_sec - OVERLAP_SEC)
        length = chunk_sec + OVERLAP_SEC
        chunk_path = os.path.join(tmp_dir, f"chunk_{i:03d}.mp3")

        cmd = [
            FFMPEG, "-ss", f"{start:.2f}", "-t", f"{length:.2f}",
            "-i", audio_path,
            "-q:a", "9",          # comprime mais para caber no limite
            chunk_path, "-y", "-loglevel", "error",
        ]
        r = subprocess.run(cmd, capture_output=True)

        if r.returncode != 0 or not os.path.exists(chunk_path):
            print(f"  [AVISO] Chunk {i+1} não gerado.", file=sys.stderr)
            continue

        chunk_mb = os.path.getsize(chunk_path) / (1024 * 1024)
        print(f"  [{i+1}/{n_chunks}] Transcrevendo parte {i+1} ({chunk_mb:.1f}MB)...")

        t = transcribe_single(chunk_path)
        if t:
            transcripts.append(t)
        os.remove(chunk_path)

    return "\n".join(transcripts) if transcripts else None


def get_transcript_yt(video_id: str) -> str | None:
    """Busca transcrição via legendas do YouTube (sem download)."""
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    for langs in [["pt", "pt-BR"], ["en", "en-US"], None]:
        try:
            if langs:
                entries = api.fetch(video_id, languages=langs)
            else:
                entries = next(iter(api.list(video_id))).fetch()
            return _fmt_entries(entries)
        except Exception:
            pass
    return None


def _fmt_entries(entries) -> str:
    seen, lines = set(), []
    for e in entries:
        text = (e.get("text") if isinstance(e, dict) else getattr(e, "text", "")).strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not YOUTUBE_API_KEY:
        print("ERRO: YOUTUBE_API_KEY não encontrada. Configure o arquivo .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Analisa vídeo do YouTube — Fase 1")
    parser.add_argument("url",           help="URL ou ID do vídeo")
    parser.add_argument("--frames", "-f", type=int, default=8,
                        help="Número de frames a extrair (default: 8)")
    parser.add_argument("--out",         default="/tmp/video_analysis", help="Diretório de saída")
    args = parser.parse_args()

    # 1. Detectar ambiente
    print("[0/5] Detectando ambiente...")
    env = detect_environment()
    report_environment(env)

    if not env["metadata"]:
        print("ERRO: YouTube Data API inacessível.", file=sys.stderr)
        sys.exit(1)

    # 2. Extrair ID e metadados
    print("\n[1/5] Buscando metadados...")
    video_id = extract_video_id(args.url)
    info     = get_video_metadata(video_id)
    print(f"      Título:  {info['title']}")
    print(f"      Canal:   {info['channel']}")
    print(f"      Duração: {info['duration_iso']} ({info['duration_sec']/60:.1f} min)")
    print(f"      Views:   {int(info['view_count'] or 0):,}")

    out_dir    = os.path.join(args.out, video_id)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(out_dir, exist_ok=True)

    info_path = os.path.join(out_dir, "info.json")
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    # 3. Thumbnail
    print("\n[2/5] Thumbnail...")
    thumbnail_path = None
    if env["thumbnail"]:
        tp = os.path.join(out_dir, "thumbnail.jpg")
        if download_thumbnail(info["thumbnail_url"], tp):
            thumbnail_path = tp
            print(f"      Salva.")
    else:
        print("      Indisponível neste ambiente.")

    # 4. Transcrição
    print("\n[3/5] Transcrição...")
    transcript      = None
    transcript_path = None

    # Método 1: legendas YT
    if env["transcript_yt"]:
        print("      Tentando legendas YouTube...")
        transcript = get_transcript_yt(video_id)
        if transcript:
            print(f"      ✅ Legendas obtidas.")

    # Método 2: Whisper via Groq (precisa baixar o vídeo)
    if not transcript and env["whisper"] and GROQ_API_KEY:
        print("      Legendas não encontradas — usando Whisper (Groq)...")
        # O download do vídeo acontece no passo 4, reutilizamos se já baixado
        # Por ora, marcamos para baixar no próximo passo e transcrever depois
        pass

    if transcript:
        transcript_path = os.path.join(out_dir, "transcript.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript)
        print(f"      {len(transcript.splitlines())} linhas salvas.")
    elif not (env["transcript_yt"] or env["whisper"]):
        print("      ⚠️  Indisponível neste ambiente.")

    # 5. Vídeo: frames + Whisper (se necessário)
    video_downloaded = False
    video_path       = os.path.join(out_dir, "video.mp4")
    frames           = []

    needs_download = (env["frames"] and args.frames > 0) or (not transcript and env["whisper"] and GROQ_API_KEY)

    if needs_download:
        print(f"\n[4/5] Baixando vídeo (baixa resolução)...")
        video_downloaded = download_video(video_id, video_path)
        if video_downloaded:
            print(f"      Download concluído.")
        else:
            print(f"      ⚠️  Download falhou.", file=sys.stderr)

    print(f"\n[5/5] Frames e transcrição Whisper...")

    # 5a. Frames visuais
    if video_downloaded and args.frames > 0:
        print(f"      Extraindo {args.frames} frames...")
        frames = extract_frames(video_path, frames_dir, args.frames, info["duration_sec"])
        print(f"      ✅ {len(frames)} frames extraídos em {frames_dir}")

    # 5b. Whisper (se transcrição ainda não obtida)
    if not transcript and video_downloaded and GROQ_API_KEY:
        print("      Extraindo áudio para Whisper...")
        audio_path = os.path.join(out_dir, "audio.mp3")
        if extract_audio(video_path, audio_path):
            transcript = transcribe_chunked(audio_path, out_dir, info["duration_sec"])
            if transcript:
                transcript_path = os.path.join(out_dir, "transcript.txt")
                with open(transcript_path, "w", encoding="utf-8") as f:
                    f.write(transcript)
                print(f"      ✅ Transcrição Whisper: {len(transcript.splitlines())} linhas.")
            if os.path.exists(audio_path):
                os.remove(audio_path)
        else:
            print("      ⚠️  Extração de áudio falhou.", file=sys.stderr)

    # Remove vídeo após extrair o que precisa
    if video_downloaded and os.path.exists(video_path):
        os.remove(video_path)

    # summary.txt
    summary_path = os.path.join(out_dir, "summary.txt")
    with open(summary_path, "w") as f:
        f.write(f"ANÁLISE DE VÍDEO — Fase 1\n")
        f.write(f"URL:       {args.url}\n")
        f.write(f"ID:        {video_id}\n")
        f.write(f"Título:    {info['title']}\n")
        f.write(f"Duração:   {info['duration_sec']/60:.1f} min\n\n")
        f.write(f"ARQUIVOS:\n")
        f.write(f"  info.json:    {info_path}\n")
        if thumbnail_path:
            f.write(f"  thumbnail:    {thumbnail_path}\n")
        if transcript_path:
            f.write(f"  transcript:   {transcript_path}\n")
        if frames:
            f.write(f"  frames ({len(frames)}):\n")
            for fp in frames:
                f.write(f"    {fp}\n")

    result = {
        "video_id":   video_id,
        "out_dir":    out_dir,
        "info_json":  info_path,
        "thumbnail":  thumbnail_path,
        "transcript": transcript_path,
        "frames":     frames,
        "summary":    summary_path,
        "env":        {k: v for k, v in env.items() if k != "raw"},
    }

    print(f"\n✅ Concluído! Diretório: {out_dir}")
    print(f"\nJSON_RESULT:{json.dumps(result)}")


if __name__ == "__main__":
    main()
