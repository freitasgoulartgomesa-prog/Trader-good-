"""
video_processor.py — orquestrador da skill video-analyze.

Detecta o ambiente e escolhe a estratégia:
  - Sandbox/iPhone com Gemini → Gemini API direta (~30s), sem GitHub Actions
  - Sandbox/iPhone sem Gemini → sinaliza para Claude usar MCP+GitHub Actions
  - PC local (internet completa) → processa tudo localmente

Uso:
  python3 scripts/video_processor.py <URL> [--frames N]

Variáveis de ambiente (.env):
  YOUTUBE_API_KEY  — obrigatório (metadados)
  GEMINI_API_KEY   — recomendado (análise rápida no iPhone via Gemini)
  GROQ_API_KEY     — opcional (Whisper, só usado no PC local)
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
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GITHUB_REPO     = os.getenv("GITHUB_REPO", "freitasgoulartgomesa-prog/Trader-good-")
GITHUB_BRANCH   = os.getenv("GITHUB_BRANCH", "claude/oi-gk0t6s")
GH_API          = "https://api.github.com"


# ─── Detecção de ambiente ─────────────────────────────────────────────────────

def detect_environment():
    results = {}

    # YouTube Data API (googleapis.com) — acessível no sandbox
    try:
        r = requests.get("https://www.googleapis.com/youtube/v3/videos",
            params={"part":"id","id":"x","key":"x"}, timeout=5)
        results["youtube_api"] = r.status_code in (200, 400)
    except Exception: results["youtube_api"] = False

    # youtube.com direto — bloqueado no sandbox (403 proxy)
    try:
        r = requests.get("https://www.youtube.com", timeout=5)
        results["youtube_web"] = r.status_code == 200
    except Exception: results["youtube_web"] = False

    # Gemini API — acessível no sandbox! (generativelanguage.googleapis.com)
    try:
        r = requests.get("https://generativelanguage.googleapis.com/", timeout=5)
        results["gemini_api"] = r.status_code in (200, 400, 404)
    except Exception: results["gemini_api"] = False

    # Groq — bloqueado no sandbox
    try:
        r = requests.get("https://api.groq.com", timeout=5)
        results["groq"] = r.status_code in (200, 401, 404)
    except Exception: results["groq"] = False

    is_sandbox = results["youtube_api"] and not results["youtube_web"]

    return {
        "is_sandbox":     is_sandbox,
        "metadata":       results["youtube_api"],
        "youtube_web":    results["youtube_web"],
        "gemini_api":     results["gemini_api"],
        "groq":           results["groq"],
        "can_use_gemini": results["gemini_api"] and bool(GEMINI_API_KEY),
        "can_use_action": is_sandbox,
    }


def report_environment(env):
    mode = "☁️  Sandbox (iPhone/browser)" if env["is_sandbox"] else "💻 PC local"
    print(f"\n  Modo: {mode}")
    if env["is_sandbox"]:
        if env["can_use_gemini"]:
            print("  ✅ Gemini API disponível → análise rápida direta (~30s)")
        else:
            print("  ✅ GitHub Actions via MCP → análise completa (~3 min)")
            if not GEMINI_API_KEY:
                print("     Dica: adicione GEMINI_API_KEY para análise em ~30s sem Actions")
    else:
        print("  ✅ Internet completa → processamento local")


# ─── Modo Gemini: processa diretamente no sandbox ────────────────────────────

def run_gemini(video_url):
    script = os.path.join(os.path.dirname(__file__), "video_gemini.py")
    cmd = [sys.executable, script, video_url]
    env = os.environ.copy()
    env.update({"GEMINI_API_KEY": GEMINI_API_KEY, "YOUTUBE_API_KEY": YOUTUBE_API_KEY})

    result = subprocess.run(cmd, env=env, capture_output=False)
    if result.returncode != 0:
        return None

    return True  # output already printed by subprocess


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

    print("[0/3] Detectando ambiente...")
    env = detect_environment()
    report_environment(env)

    # Imprime JSON do ambiente para que o SKILL.md possa decidir o fluxo
    print(f"\nJSON_ENV:{json.dumps(env)}")

    if env["is_sandbox"]:
        if env["can_use_gemini"]:
            # ── Modo sandbox + Gemini (iPhone rápido ~30s) ─────────────────
            print("\n  Iniciando análise via Gemini...")
            run_gemini(args.url)
            # JSON_RESULT já foi impresso por video_gemini.py
        else:
            # ── Modo sandbox sem Gemini → Claude usa MCP Actions ───────────
            print("\nUSE_MCP_ACTIONS")
            print("  Use mcp__github__actions_run_trigger para disparar o workflow")
            print(f"  Workflow: video_analyze.yml | Branch: {GITHUB_BRANCH}")
    else:
        # ── Modo PC local ──────────────────────────────────────────────────
        print("\n  Processando localmente...")
        result = run_local(args.url, args.frames)
        print(f"\n✅ Concluído!")
        print(f"\nJSON_RESULT:{json.dumps(result)}")


if __name__ == "__main__":
    main()
