"""
video_gemini.py — analisa vídeos YouTube via Gemini API diretamente no sandbox.

Funciona no iPhone/browser porque só precisa de generativelanguage.googleapis.com
(confirmado acessível no sandbox Anthropic). O Gemini busca o vídeo nos servidores
do Google — o sandbox não precisa acessar youtube.com diretamente.

Uso:
  python3 scripts/video_gemini.py <URL> [--extra "contexto adicional"]
"""

import json, os, re, subprocess, sys

def ensure(pkgs):
    for imp, pkg in pkgs.items():
        try: __import__(imp)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

ensure({"requests": "requests", "dotenv": "python-dotenv"})

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
GEMINI_BASE     = "https://generativelanguage.googleapis.com/v1beta"
YT_API_BASE     = "https://www.googleapis.com/youtube/v3"
GEMINI_MODEL    = "gemini-2.0-flash"


def extract_video_id(url):
    for p in [r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", r"^([A-Za-z0-9_-]{11})$"]:
        m = re.search(p, url)
        if m: return m.group(1)
    raise ValueError(f"ID não encontrado em: {url}")


def get_metadata(video_id):
    if not YOUTUBE_API_KEY:
        return {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}

    r = requests.get(f"{YT_API_BASE}/videos",
        params={"part": "snippet,statistics,contentDetails", "id": video_id, "key": YOUTUBE_API_KEY},
        timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items: return {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}

    item = items[0]
    s = item.get("snippet", {}); st = item.get("statistics", {}); d = item.get("contentDetails", {})

    def parse_iso(iso):
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
        if not m: return 0.0
        return int(m.group(1) or 0)*3600 + int(m.group(2) or 0)*60 + int(m.group(3) or 0)

    th = s.get("thumbnails", {}); t = th.get("maxres") or th.get("high") or th.get("medium") or {}
    return {
        "video_id":     video_id,
        "title":        s.get("title", ""),
        "channel":      s.get("channelTitle", ""),
        "description":  (s.get("description") or "")[:2000],
        "published_at": s.get("publishedAt", ""),
        "duration_sec": parse_iso(d.get("duration", "")),
        "tags":         (s.get("tags") or [])[:10],
        "view_count":   st.get("viewCount"),
        "like_count":   st.get("likeCount"),
        "comment_count":st.get("commentCount"),
        "thumbnail_url":t.get("url", ""),
        "url":          f"https://www.youtube.com/watch?v={video_id}",
    }


def analyze_with_gemini(video_url, prompt_extra=""):
    prompt = f"""Analise este vídeo do YouTube completamente e retorne um JSON com esta estrutura exata:

{{
  "transcript": "transcrição completa do áudio. Inclua timestamps no formato [MM:SS] no início de cada parágrafo ou mudança de assunto.",
  "visual_summary": "descrição detalhada do conteúdo visual: o que aparece na tela (gráficos, textos, slides, ambiente, pessoas, expressões faciais, objetos mostrados, demonstrações)",
  "content_summary": "resumo do conteúdo em 3 a 5 parágrafos cobrindo os pontos principais",
  "key_topics": ["tópico principal 1", "tópico 2", "..."],
  "key_quotes": ["frase ou trecho importante 1", "frase 2"],
  "language": "pt-BR ou en ou outro código de idioma",
  "tone": "educacional / motivacional / técnico / informal / noticiário / etc",
  "target_audience": "descrição do público-alvo do vídeo"
}}

{prompt_extra}

Responda APENAS com o JSON válido, sem markdown, sem texto antes ou depois."""

    payload = {
        "contents": [{
            "parts": [
                {"fileData": {"fileUri": video_url}},
                {"text": prompt}
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 8192,
        }
    }

    print(f"  Enviando para Gemini {GEMINI_MODEL}...", flush=True)
    r = requests.post(
        f"{GEMINI_BASE}/models/{GEMINI_MODEL}:generateContent",
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=180
    )

    if r.status_code != 200:
        print(f"  [ERRO Gemini] HTTP {r.status_code}: {r.text[:500]}", file=sys.stderr)
        return None

    try:
        data = r.json()
        # Check for safety blocks or empty candidates
        candidates = data.get("candidates", [])
        if not candidates:
            print(f"  [ERRO Gemini] Sem candidatos: {json.dumps(data)[:300]}", file=sys.stderr)
            return None

        finish_reason = candidates[0].get("finishReason", "")
        if finish_reason not in ("STOP", "MAX_TOKENS", ""):
            print(f"  [AVISO Gemini] finishReason={finish_reason}", file=sys.stderr)

        text = candidates[0]["content"]["parts"][0]["text"].strip()
        # Remove markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        return json.loads(text)

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        raw = text if "text" in dir() else r.text[:1000]
        print(f"  [AVISO] JSON inválido do Gemini ({e}), retornando raw.", file=sys.stderr)
        return {"raw_response": raw, "parse_error": str(e)}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Video analyze via Gemini API")
    parser.add_argument("url")
    parser.add_argument("--extra", default="", help="Contexto adicional para o prompt Gemini")
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        print("ERRO: GEMINI_API_KEY não encontrada.", file=sys.stderr)
        sys.exit(1)

    print("\n[1/3] Extraindo metadados via YouTube Data API...")
    video_id = extract_video_id(args.url)
    info = get_metadata(video_id)
    print(f"  Título:  {info.get('title', video_id)}")
    print(f"  Canal:   {info.get('channel', '?')}")
    dur = info.get("duration_sec", 0)
    print(f"  Duração: {int(dur//60)}m{int(dur%60):02d}s")

    print("\n[2/3] Analisando vídeo com Gemini (transcrição + análise visual)...")
    analysis = analyze_with_gemini(args.url, args.extra)

    if not analysis:
        print("  ❌ Gemini não retornou resultado.", file=sys.stderr)
        sys.exit(1)

    transcript = analysis.get("transcript", "")
    print(f"  ✅ Análise concluída. Transcrição: {len(transcript.splitlines())} linhas.")

    print("\n[3/3] Salvando resultados...")
    out_dir = f"/tmp/video_analysis/{video_id}"
    os.makedirs(out_dir, exist_ok=True)

    info_path = os.path.join(out_dir, "info.json")
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    analysis_path = os.path.join(out_dir, "gemini_analysis.json")
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    transcript_path = None
    if transcript:
        transcript_path = os.path.join(out_dir, "transcript.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript)

    result = {
        "video_id":     video_id,
        "method":       "gemini",
        "out_dir":      out_dir,
        "info_json":    info_path,
        "analysis":     analysis_path,
        "transcript":   transcript_path,
        "info":         info,
        "summary": {
            "title":          info.get("title", ""),
            "channel":        info.get("channel", ""),
            "duration_sec":   info.get("duration_sec", 0),
            "view_count":     info.get("view_count"),
            "key_topics":     analysis.get("key_topics", []),
            "language":       analysis.get("language", ""),
            "tone":           analysis.get("tone", ""),
            "has_transcript": bool(transcript),
        }
    }

    print(f"\n✅ Concluído — {out_dir}")
    print(f"\nJSON_RESULT:{json.dumps(result, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
