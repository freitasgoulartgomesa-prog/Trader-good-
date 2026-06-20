"""
video_processor_actions.py — roda no GitHub Actions (internet completa).

Chamado pelo workflow video_analyze.yml. Salva tudo em video_results/VIDEO_ID/
para que Claude possa ler via GitHub API mesmo do sandbox do iPhone.

Uso:
  python scripts/video_processor_actions.py <URL> [--frames N] [--out DIR]
"""

import argparse, json, math, os, re, subprocess, sys

# ─── Dependências ─────────────────────────────────────────────────────────────
def ensure(pkgs):
    for imp, pkg in pkgs.items():
        try: __import__(imp)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

ensure({
    "requests": "requests", "yt_dlp": "yt-dlp",
    "youtube_transcript_api": "youtube-transcript-api",
    "groq": "groq", "isodate": "isodate",
    "imageio_ffmpeg": "imageio[ffmpeg]",
})

import requests

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "")
YT_API_BASE     = "https://www.googleapis.com/youtube/v3"

from imageio_ffmpeg import get_ffmpeg_exe
FFMPEG  = get_ffmpeg_exe()
FFPROBE = "/usr/bin/ffprobe" if os.path.exists("/usr/bin/ffprobe") else FFMPEG


# ─── Utilitários ──────────────────────────────────────────────────────────────

def extract_video_id(url):
    for p in [r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", r"^([A-Za-z0-9_-]{11})$"]:
        m = re.search(p, url)
        if m: return m.group(1)
    raise ValueError(f"ID não encontrado em: {url}")


def parse_iso(iso):
    try:
        import isodate
        return isodate.parse_duration(iso).total_seconds()
    except Exception:
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
        if not m: return 0.0
        return int(m.group(1) or 0)*3600 + int(m.group(2) or 0)*60 + int(m.group(3) or 0)


# ─── Metadados ────────────────────────────────────────────────────────────────

def get_metadata(video_id):
    r = requests.get(f"{YT_API_BASE}/videos",
        params={"part":"snippet,statistics,contentDetails","id":video_id,"key":YOUTUBE_API_KEY},
        timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items: raise ValueError(f"Vídeo não encontrado: {video_id}")
    item = items[0]
    s = item.get("snippet", {}); st = item.get("statistics", {}); d = item.get("contentDetails", {})
    th = s.get("thumbnails", {}); t = th.get("maxres") or th.get("high") or th.get("medium") or {}
    return {
        "video_id": video_id, "title": s.get("title",""), "channel": s.get("channelTitle",""),
        "description": (s.get("description") or "")[:3000],
        "published_at": s.get("publishedAt",""), "duration_iso": d.get("duration",""),
        "duration_sec": parse_iso(d.get("duration","")),
        "tags": (s.get("tags") or [])[:20],
        "view_count": st.get("viewCount"), "like_count": st.get("likeCount"),
        "comment_count": st.get("commentCount"), "thumbnail_url": t.get("url",""),
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


# ─── Thumbnail ────────────────────────────────────────────────────────────────

def download_thumbnail(url, path):
    if not url: return False
    try:
        r = requests.get(url, timeout=15); r.raise_for_status()
        with open(path, "wb") as f: f.write(r.content)
        return True
    except Exception as e:
        print(f"  [AVISO] Thumbnail: {e}", file=sys.stderr); return False


# ─── Download de vídeo ────────────────────────────────────────────────────────

def download_video(video_id, path):
    import yt_dlp
    opts = {
        "quiet": True, "no_warnings": True,
        "format": "best[height<=360][ext=mp4]/best[height<=480][ext=mp4]/best[ext=mp4]/best",
        "outtmpl": path, "merge_output_format": "mp4",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        return os.path.exists(path)
    except Exception as e:
        print(f"  [ERRO] Download: {e}", file=sys.stderr); return False


# ─── Frames ───────────────────────────────────────────────────────────────────

def extract_frames(video_path, frames_dir, n, duration_sec):
    os.makedirs(frames_dir, exist_ok=True)
    if duration_sec <= 0: duration_sec = 60.0
    margin  = min(duration_sec * 0.03, 5.0)
    usable  = duration_sec - 2 * margin
    if n == 1: timestamps = [duration_sec / 2]
    else: timestamps = [margin + usable * i / (n - 1) for i in range(n)]

    frames = []
    for i, ts in enumerate(timestamps):
        out = os.path.join(frames_dir, f"frame_{i+1:03d}.jpg")
        cmd = [FFMPEG, "-ss", f"{ts:.2f}", "-i", video_path,
               "-vframes", "1", "-q:v", "3", "-vf", "scale=960:-1",
               out, "-y", "-loglevel", "error"]
        if subprocess.run(cmd, capture_output=True).returncode == 0 and os.path.exists(out):
            frames.append(out)
    return frames


# ─── Áudio e transcrição ──────────────────────────────────────────────────────

def extract_audio(video_path, audio_path):
    cmd = [FFMPEG, "-i", video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "5",
           audio_path, "-y", "-loglevel", "error"]
    return subprocess.run(cmd, capture_output=True).returncode == 0 and os.path.exists(audio_path)


def get_audio_duration(audio_path):
    cmd = [FFPROBE, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(r.stdout.strip())
    except Exception: return None


def transcribe_single(audio_path):
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    try:
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f),
                model="whisper-large-v3-turbo", response_format="text")
        return str(result).strip() if result else None
    except Exception as e:
        print(f"  [ERRO] Whisper: {e}", file=sys.stderr); return None


def transcribe_chunked(audio_path, tmp_dir, duration_sec=None):
    if not GROQ_API_KEY: return None
    MAX_MB = 20.0
    size_mb = os.path.getsize(audio_path) / (1024*1024)
    if size_mb <= MAX_MB:
        print(f"  Transcrevendo {size_mb:.1f}MB...")
        return transcribe_single(audio_path)

    duration = duration_sec or get_audio_duration(audio_path)
    if not duration: return None
    n = math.ceil(size_mb / MAX_MB)
    chunk_sec = duration / n
    print(f"  {size_mb:.1f}MB → {n} partes de {chunk_sec/60:.1f}min...")

    parts = []
    for i in range(n):
        start = max(0, i * chunk_sec - 2)
        chunk = os.path.join(tmp_dir, f"chunk_{i:03d}.mp3")
        cmd = [FFMPEG, "-ss", f"{start:.2f}", "-t", f"{chunk_sec+2:.2f}",
               "-i", audio_path, "-q:a", "9", chunk, "-y", "-loglevel", "error"]
        if subprocess.run(cmd, capture_output=True).returncode == 0 and os.path.exists(chunk):
            print(f"  [{i+1}/{n}] Parte {i+1}...")
            t = transcribe_single(chunk)
            if t: parts.append(t)
            os.remove(chunk)
    return "\n".join(parts) if parts else None


def get_transcript_yt(video_id):
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    for langs in [["pt","pt-BR"], ["en","en-US"], None]:
        try:
            entries = api.fetch(video_id, languages=langs) if langs else next(iter(api.list(video_id))).fetch()
            seen, lines = set(), []
            for e in entries:
                t = (e.get("text") if isinstance(e, dict) else getattr(e,"text","")).strip()
                if t and t not in seen: seen.add(t); lines.append(t)
            return "\n".join(lines)
        except Exception: pass
    return None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--frames", "-f", type=int, default=8)
    parser.add_argument("--out", default="video_results")
    args = parser.parse_args()

    if not YOUTUBE_API_KEY:
        print("ERRO: YOUTUBE_API_KEY não configurada como secret do repositório.", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"VIDEO ANALYZE — GitHub Actions")
    print(f"URL: {args.url}")
    print(f"{'='*60}\n")

    print("[1/5] Extraindo ID e metadados...")
    video_id = extract_video_id(args.url)
    info = get_metadata(video_id)
    print(f"  Título:  {info['title']}")
    print(f"  Canal:   {info['channel']}")
    print(f"  Duração: {info['duration_sec']/60:.1f} min")

    out_dir    = os.path.join(args.out, video_id)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print("\n[2/5] Thumbnail...")
    thumb_path = os.path.join(out_dir, "thumbnail.jpg")
    has_thumb = download_thumbnail(info["thumbnail_url"], thumb_path)
    if has_thumb: print(f"  ✅ Salva.")
    else: thumb_path = None

    print("\n[3/5] Transcrição (legendas YouTube)...")
    transcript = get_transcript_yt(video_id)
    if transcript:
        print(f"  ✅ {len(transcript.splitlines())} linhas via legendas.")

    print("\n[4/5] Download de vídeo (360p)...")
    video_path = os.path.join(out_dir, "_video.mp4")
    downloaded = download_video(video_id, video_path)
    if downloaded: print(f"  ✅ Download concluído.")
    else: print(f"  ❌ Falha no download.")

    print(f"\n[5/5] Frames{' e Whisper' if not transcript else ''}...")
    frames = []
    if downloaded and args.frames > 0:
        frames = extract_frames(video_path, frames_dir, args.frames, info["duration_sec"])
        print(f"  ✅ {len(frames)} frames extraídos.")

    if not transcript and downloaded and GROQ_API_KEY:
        audio_path = os.path.join(out_dir, "_audio.mp3")
        if extract_audio(video_path, audio_path):
            transcript = transcribe_chunked(audio_path, out_dir, info["duration_sec"])
            if transcript: print(f"  ✅ {len(transcript.splitlines())} linhas via Whisper.")
            if os.path.exists(audio_path): os.remove(audio_path)

    if downloaded and os.path.exists(video_path):
        os.remove(video_path)

    transcript_path = None
    if transcript:
        transcript_path = os.path.join(out_dir, "transcript.txt")
        with open(transcript_path, "w", encoding="utf-8") as f: f.write(transcript)

    # summary.json — Claude lê isso primeiro para saber o que existe
    summary = {
        "video_id":         video_id,
        "url":              args.url,
        "processed_at":     __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "has_thumbnail":    has_thumb,
        "has_transcript":   transcript is not None,
        "transcript_lines": len(transcript.splitlines()) if transcript else 0,
        "frames_count":     len(frames),
        "frames":           [os.path.relpath(f, args.out) for f in frames],
        "files": {
            "info":       f"{video_id}/info.json",
            "thumbnail":  f"{video_id}/thumbnail.jpg" if has_thumb else None,
            "transcript": f"{video_id}/transcript.txt" if transcript else None,
            "frames":     [os.path.relpath(f, args.out) for f in frames],
        }
    }
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ CONCLUÍDO — {out_dir}")
    print(f"   Frames:      {len(frames)}")
    print(f"   Transcrição: {'sim' if transcript else 'não'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
