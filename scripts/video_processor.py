"""
video_processor.py — orquestrador da skill video-analyze.

Detecta o ambiente e escolhe a estratégia:
  - PC local (internet completa) → processa tudo aqui mesmo
  - Sandbox/iPhone (internet restrita) → dispara GitHub Action e aguarda resultado

Uso:
  python3 scripts/video_processor.py <URL> [--frames N]

Variáveis de ambiente (.env):
  YOUTUBE_API_KEY  — obrigatório
  GROQ_API_KEY     — opcional (Whisper para vídeos sem legenda)
  GITHUB_TOKEN     — obrigatório no sandbox (dispara Actions)
  GITHUB_REPO      — ex: freitasgoulartgomesa-prog/Trader-good-
  GITHUB_BRANCH    — branch atual (default: claude/oi-gk0t6s)
"""

import json, os, re, subprocess, sys, time

def ensure(pkgs):
    for imp, pkg in pkgs.items():
        try: __import__(imp)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

ensure({"requests": "requests", "dotenv": "python-dotenv"})

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GITHUB_TOKEN    = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO     = os.getenv("GITHUB_REPO", "freitasgoulartgomesa-prog/Trader-good-")
GITHUB_BRANCH   = os.getenv("GITHUB_BRANCH", "claude/oi-gk0t6s")
GH_API          = "https://api.github.com"


# ─── Detecção de ambiente ─────────────────────────────────────────────────────

def detect_environment():
    results = {}

    # YouTube Data API (googleapis.com)
    try:
        r = requests.get(f"https://www.googleapis.com/youtube/v3/videos",
            params={"part":"id","id":"x","key":"x"}, timeout=5)
        results["youtube_api"] = r.status_code in (200, 400)
    except Exception: results["youtube_api"] = False

    # youtube.com direto (yt-dlp)
    try:
        r = requests.get("https://www.youtube.com", timeout=5)
        results["youtube_web"] = r.status_code == 200
    except Exception: results["youtube_web"] = False

    # Groq
    try:
        r = requests.get("https://api.groq.com", timeout=5)
        results["groq"] = r.status_code in (200, 401, 404)
    except Exception: results["groq"] = False

    # GitHub API
    try:
        r = requests.get(f"{GH_API}/zen", timeout=5)
        results["github_api"] = r.status_code == 200
    except Exception: results["github_api"] = False

    is_sandbox = results["youtube_api"] and not results["youtube_web"]

    return {
        "is_sandbox":    is_sandbox,
        "metadata":      results["youtube_api"],
        "youtube_web":   results["youtube_web"],
        "groq":          results["groq"],
        "github_api":    results["github_api"],
        "can_use_action": is_sandbox and results["github_api"] and bool(GITHUB_TOKEN),
    }


def report_environment(env):
    mode = "☁️  Sandbox (iPhone/browser)" if env["is_sandbox"] else "💻 PC local"
    print(f"\n  Modo: {mode}")
    if env["is_sandbox"]:
        if env["can_use_action"]:
            print("  ✅ GitHub Actions disponível → processamento via Actions")
        else:
            print("  ⚠️  GitHub Actions indisponível → apenas metadados disponíveis")
            if not GITHUB_TOKEN:
                print("     Configure GITHUB_TOKEN no .env para habilitar Actions")
    else:
        print(f"  ✅ Internet completa → processamento local")


# ─── Modo sandbox: dispara GitHub Action e aguarda ───────────────────────────

def trigger_github_action(video_url, frames):
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "video_url":  video_url,
            "frames":     str(frames),
            "ref_branch": GITHUB_BRANCH,
        }
    }
    r = requests.post(
        f"{GH_API}/repos/{GITHUB_REPO}/actions/workflows/video_analyze.yml/dispatches",
        headers=headers, json=payload, timeout=15)

    if r.status_code == 204:
        print("  ✅ GitHub Action disparada com sucesso.")
        return True
    else:
        print(f"  ❌ Falha ao disparar Action: {r.status_code} — {r.text}", file=sys.stderr)
        return False


def wait_for_action(video_id, timeout_sec=300, poll_sec=10):
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    print(f"  Aguardando Action completar (máx {timeout_sec//60} min)...")
    start = time.time()

    while time.time() - start < timeout_sec:
        time.sleep(poll_sec)
        elapsed = int(time.time() - start)
        print(f"  ⏳ {elapsed}s — verificando...")

        r = requests.get(
            f"{GH_API}/repos/{GITHUB_REPO}/actions/runs",
            params={"workflow_file": "video_analyze.yml", "per_page": 5},
            headers=headers, timeout=10)
        if r.status_code != 200: continue

        runs = r.json().get("workflow_runs", [])
        if not runs: continue

        latest = runs[0]
        status     = latest.get("status")
        conclusion = latest.get("conclusion")

        if status == "completed":
            if conclusion == "success":
                print(f"  ✅ Action concluída com sucesso!")
                return True
            else:
                print(f"  ❌ Action falhou: {conclusion}", file=sys.stderr)
                return False

    print(f"  ⏰ Timeout após {timeout_sec}s.", file=sys.stderr)
    return False


def read_results_from_github(video_id):
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    base = f"video_results/{video_id}"

    def get_file(path):
        r = requests.get(
            f"{GH_API}/repos/{GITHUB_REPO}/contents/{path}",
            params={"ref": GITHUB_BRANCH},
            headers=headers, timeout=10)
        if r.status_code != 200: return None
        import base64
        data = r.json()
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    # Lê summary.json primeiro
    summary_raw = get_file(f"{base}/summary.json")
    if not summary_raw:
        print("  ⚠️  Resultado não encontrado no repositório.", file=sys.stderr)
        return None

    summary = json.loads(summary_raw)

    # Lê info.json
    info_raw = get_file(f"{base}/info.json")
    info = json.loads(info_raw) if info_raw else {}

    # Lê transcrição
    transcript = None
    if summary.get("has_transcript"):
        transcript = get_file(f"{base}/transcript.txt")

    # Baixa frames para /tmp para que Claude possa ler com Read tool
    frames_local = []
    tmp_frames = f"/tmp/video_analysis/{video_id}/frames"
    os.makedirs(tmp_frames, exist_ok=True)

    for frame_path in summary.get("frames", []):
        r = requests.get(
            f"{GH_API}/repos/{GITHUB_REPO}/contents/video_results/{frame_path}",
            params={"ref": GITHUB_BRANCH},
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                     "Accept": "application/vnd.github+json"},
            timeout=15)
        if r.status_code != 200: continue
        import base64
        img_bytes = base64.b64decode(r.json()["content"])
        local_path = os.path.join(tmp_frames, os.path.basename(frame_path))
        with open(local_path, "wb") as f: f.write(img_bytes)
        frames_local.append(local_path)

    if frames_local:
        print(f"  ✅ {len(frames_local)} frames baixados para análise.")

    # Thumbnail
    thumb_local = None
    if summary.get("has_thumbnail"):
        r = requests.get(
            f"{GH_API}/repos/{GITHUB_REPO}/contents/{base}/thumbnail.jpg",
            params={"ref": GITHUB_BRANCH},
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                     "Accept": "application/vnd.github+json"},
            timeout=15)
        if r.status_code == 200:
            import base64
            img_bytes = base64.b64decode(r.json()["content"])
            thumb_local = f"/tmp/video_analysis/{video_id}/thumbnail.jpg"
            os.makedirs(os.path.dirname(thumb_local), exist_ok=True)
            with open(thumb_local, "wb") as f: f.write(img_bytes)

    # Salva localmente para uso offline
    out_dir = f"/tmp/video_analysis/{video_id}"
    os.makedirs(out_dir, exist_ok=True)

    info_path = os.path.join(out_dir, "info.json")
    with open(info_path, "w") as f: json.dump(info, f, indent=2)

    transcript_path = None
    if transcript:
        transcript_path = os.path.join(out_dir, "transcript.txt")
        with open(transcript_path, "w") as f: f.write(transcript)

    return {
        "video_id":   video_id,
        "out_dir":    out_dir,
        "info_json":  info_path,
        "thumbnail":  thumb_local,
        "transcript": transcript_path,
        "frames":     frames_local,
        "summary":    os.path.join(out_dir, "summary.json"),
    }


# ─── Modo local: processa direto ──────────────────────────────────────────────

def run_local(video_url, frames, out_base="/tmp/video_analysis"):
    script = os.path.join(os.path.dirname(__file__), "video_processor_actions.py")
    cmd = [sys.executable, script, video_url, "--frames", str(frames), "--out", out_base]

    env = os.environ.copy()
    env.update({"YOUTUBE_API_KEY": YOUTUBE_API_KEY, "GROQ_API_KEY": GROQ_API_KEY})

    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print("❌ Processamento local falhou.", file=sys.stderr)
        sys.exit(1)

    # Descobre o video_id a partir da URL
    for p in [r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", r"^([A-Za-z0-9_-]{11})$"]:
        m = re.search(p, video_url)
        if m:
            video_id = m.group(1)
            break
    else:
        print("❌ Não conseguiu extrair video_id.", file=sys.stderr)
        sys.exit(1)

    out_dir = os.path.join(out_base, video_id)
    summary_path = os.path.join(out_dir, "summary.json")
    info_path = os.path.join(out_dir, "info.json")
    transcript_path = os.path.join(out_dir, "transcript.txt")
    frames_dir = os.path.join(out_dir, "frames")
    frames_list = sorted([
        os.path.join(frames_dir, f)
        for f in os.listdir(frames_dir)
        if f.endswith(".jpg")
    ]) if os.path.isdir(frames_dir) else []

    return {
        "video_id":   video_id,
        "out_dir":    out_dir,
        "info_json":  info_path if os.path.exists(info_path) else None,
        "thumbnail":  os.path.join(out_dir, "thumbnail.jpg") if os.path.exists(os.path.join(out_dir, "thumbnail.jpg")) else None,
        "transcript": transcript_path if os.path.exists(transcript_path) else None,
        "frames":     frames_list,
        "summary":    summary_path,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Orquestrador video-analyze")
    parser.add_argument("url")
    parser.add_argument("--frames", "-f", type=int, default=8)
    args = parser.parse_args()

    if not YOUTUBE_API_KEY:
        print("ERRO: YOUTUBE_API_KEY não encontrada.", file=sys.stderr)
        sys.exit(1)

    print("[0/5] Detectando ambiente...")
    env = detect_environment()
    report_environment(env)

    if env["is_sandbox"]:
        # ── Modo sandbox (iPhone) ──────────────────────────────────────────
        if not env["can_use_action"]:
            print("\n⚠️  Sem GitHub Token configurado. Apenas metadados disponíveis.")
            print("   Adicione GITHUB_TOKEN ao .env para habilitar análise completa.\n")
            # Fallback: roda só metadados
            run_local(args.url, frames=0)
            return

        print("\n  Modo iPhone: disparando GitHub Action...")
        ok = trigger_github_action(args.url, args.frames)
        if not ok: sys.exit(1)

        # Extrai video_id para monitorar
        for p in [r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})"]:
            m = re.search(p, args.url)
            if m: video_id = m.group(1); break

        success = wait_for_action(video_id)
        if not success: sys.exit(1)

        print("\n  Lendo resultados do repositório...")
        result = read_results_from_github(video_id)
        if not result: sys.exit(1)

    else:
        # ── Modo PC local ──────────────────────────────────────────────────
        print("\n  Processando localmente...")
        result = run_local(args.url, args.frames)

    print(f"\n✅ Concluído!")
    print(f"\nJSON_RESULT:{json.dumps(result)}")


if __name__ == "__main__":
    main()
