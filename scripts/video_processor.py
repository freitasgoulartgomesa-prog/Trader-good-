"""
video_processor.py — extrai frames e transcrição de qualquer URL de vídeo.

Uso:
  python3 scripts/video_processor.py <URL> [--frames N] [--out DIR]

Saída:
  /tmp/video_analysis/<hash>/
    info.json       — metadados (título, duração, descrição, etc.)
    transcript.txt  — legenda/transcrição (se disponível)
    frames/
      frame_001.jpg ... frame_N.jpg
    summary.txt     — caminho dos arquivos gerados (para leitura rápida)
"""

import argparse
import hashlib
import json
import os
import sys
import subprocess
import tempfile

# yt-dlp importado após garantir instalação
try:
    import yt_dlp
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp", "-q"])
    import yt_dlp

try:
    from imageio_ffmpeg import get_ffmpeg_exe
    FFMPEG = get_ffmpeg_exe()
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "imageio[ffmpeg]", "-q"])
    from imageio_ffmpeg import get_ffmpeg_exe
    FFMPEG = get_ffmpeg_exe()


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:8]


def extract_info_and_transcript(url: str, out_dir: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["pt", "pt-BR", "en"],
        "subtitlesformat": "vtt",
        "outtmpl": os.path.join(out_dir, "video"),
        "cookiesfrombrowser": None,
        "nocheckcertificate": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # Salvar info.json (campos principais)
    info_clean = {
        "title": info.get("title", ""),
        "description": (info.get("description") or "")[:2000],
        "duration": info.get("duration"),
        "duration_string": info.get("duration_string", ""),
        "uploader": info.get("uploader", ""),
        "upload_date": info.get("upload_date", ""),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "url": url,
        "webpage_url": info.get("webpage_url", url),
        "thumbnail": info.get("thumbnail", ""),
        "tags": info.get("tags", [])[:20],
        "categories": info.get("categories", []),
        "chapters": info.get("chapters", []),
    }
    with open(os.path.join(out_dir, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info_clean, f, ensure_ascii=False, indent=2)

    return info


def download_transcript(url: str, out_dir: str) -> str | None:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["pt", "pt-BR", "en"],
        "subtitlesformat": "vtt",
        "outtmpl": os.path.join(out_dir, "video"),
        "nocheckcertificate": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Procurar arquivo de legenda gerado
    for fname in os.listdir(out_dir):
        if fname.endswith(".vtt"):
            vtt_path = os.path.join(out_dir, fname)
            txt_path = os.path.join(out_dir, "transcript.txt")
            _vtt_to_txt(vtt_path, txt_path)
            return txt_path
    return None


def _vtt_to_txt(vtt_path: str, txt_path: str):
    """Converte VTT para texto limpo."""
    import re
    with open(vtt_path, encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines()
    seen = set()
    result = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue
        # Remove tags HTML
        line = re.sub(r"<[^>]+>", "", line)
        if line and line not in seen:
            seen.add(line)
            result.append(line)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(result))


def download_video_for_frames(url: str, out_dir: str) -> str | None:
    video_path = os.path.join(out_dir, "video.mp4")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/best[ext=mp4][height<=480]/best[height<=480]/best",
        "outtmpl": video_path,
        "merge_output_format": "mp4",
        "nocheckcertificate": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if os.path.exists(video_path):
            return video_path
    except Exception as e:
        print(f"[AVISO] Não foi possível baixar o vídeo para frames: {e}", file=sys.stderr)
    return None


def extract_frames(video_path: str, frames_dir: str, n_frames: int, duration: float | None):
    os.makedirs(frames_dir, exist_ok=True)

    if duration and duration > 0:
        interval = duration / (n_frames + 1)
        timestamps = [interval * (i + 1) for i in range(n_frames)]
    else:
        timestamps = list(range(10, 10 + n_frames * 30, 30))

    generated = []
    for i, ts in enumerate(timestamps):
        out_path = os.path.join(frames_dir, f"frame_{i+1:03d}.jpg")
        cmd = [
            FFMPEG, "-ss", str(ts), "-i", video_path,
            "-vframes", "1", "-q:v", "3", out_path, "-y", "-loglevel", "error"
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and os.path.exists(out_path):
            generated.append(out_path)

    return generated


def main():
    parser = argparse.ArgumentParser(description="Analisa vídeo de qualquer URL")
    parser.add_argument("url", help="URL do vídeo")
    parser.add_argument("--frames", type=int, default=8, help="Número de frames a extrair (default: 8)")
    parser.add_argument("--out", default="/tmp/video_analysis", help="Diretório de saída base")
    args = parser.parse_args()

    uid = url_hash(args.url)
    out_dir = os.path.join(args.out, uid)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[1/4] Extraindo metadados de: {args.url}")
    info = extract_info_and_transcript(args.url, out_dir)
    duration = info.get("duration")
    title = info.get("title", "")
    print(f"      Título: {title} | Duração: {info.get('duration_string', '?')}")

    print("[2/4] Baixando transcrição/legendas...")
    transcript_path = download_transcript(args.url, out_dir)
    if transcript_path:
        print(f"      Transcrição salva em: {transcript_path}")
    else:
        print("      Transcrição não disponível.")

    print("[3/4] Baixando vídeo para extração de frames...")
    video_path = download_video_for_frames(args.url, out_dir)

    frames = []
    if video_path:
        print(f"[4/4] Extraindo {args.frames} frames...")
        frames = extract_frames(video_path, frames_dir, args.frames, duration)
        print(f"      {len(frames)} frames extraídos.")
        # Remover vídeo para economizar espaço
        os.remove(video_path)
    else:
        print("[4/4] Pulando extração de frames (vídeo não disponível).")

    # Gerar summary.txt com todos os caminhos
    summary_path = os.path.join(out_dir, "summary.txt")
    with open(summary_path, "w") as f:
        f.write(f"ANÁLISE DE VÍDEO\n")
        f.write(f"URL: {args.url}\n")
        f.write(f"Diretório: {out_dir}\n\n")
        f.write(f"ARQUIVOS GERADOS:\n")
        f.write(f"  info.json:      {os.path.join(out_dir, 'info.json')}\n")
        if transcript_path:
            f.write(f"  transcript.txt: {transcript_path}\n")
        if frames:
            f.write(f"  frames ({len(frames)}):\n")
            for fp in frames:
                f.write(f"    {fp}\n")

    print(f"\nConcluído! Resumo em: {summary_path}")
    print(f"Diretório completo: {out_dir}")
    # Imprimir JSON para fácil parsing
    result = {
        "out_dir": out_dir,
        "info_json": os.path.join(out_dir, "info.json"),
        "transcript": transcript_path,
        "frames": frames,
        "summary": summary_path,
    }
    print(f"\nJSON_RESULT:{json.dumps(result)}")


if __name__ == "__main__":
    main()
