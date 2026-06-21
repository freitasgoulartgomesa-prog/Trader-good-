#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extrator_setups.py
Extrai setups de trade de um vídeo do YouTube usando Gemini API.

Uso:
    from extrator_setups import processar_video
    setups = processar_video('https://www.youtube.com/watch?v=...')
    print(setups)

Requer:
    GEMINI_API_KEY  — variável de ambiente com a chave da API Gemini
    pip install youtube-transcript-api yt-dlp requests
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse

# ------------------------------------------------------------------ helpers

def _video_id(url: str) -> str:
    """Extrai o ID do vídeo de qualquer formato de URL do YouTube."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    raise ValueError("Não foi possível extrair o ID do vídeo de: %s" % url)


def _obter_transcricao(video_id: str) -> str:
    """
    Tenta obter a transcrição do YouTube via youtube-transcript-api.
    Retorna o texto concatenado ou string vazia se não disponível.
    Compatível com youtube-transcript-api >= 1.0 (API baseada em instância).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        # tenta buscar diretamente nas línguas preferidas
        try:
            segmentos = api.fetch(video_id, languages=["pt-BR", "pt", "en"])
            return " ".join(s["text"] for s in segmentos)
        except Exception:
            pass
        # fallback: itera todas as transcrições disponíveis
        try:
            lista = api.list(video_id)
            for t in lista:
                try:
                    segmentos = t.fetch()
                    return " ".join(s["text"] for s in segmentos)
                except Exception:
                    continue
        except Exception:
            pass
        return ""
    except ImportError:
        return ""


def _obter_info_ytdlp(url: str) -> dict:
    """
    Usa yt-dlp para obter título, descrição e duração do vídeo.
    Retorna dict com 'titulo', 'descricao', 'duracao_seg'.
    """
    vazio = {"titulo": "", "descricao": "", "duracao_seg": 0, "canal": "", "chapters": []}
    try:
        import yt_dlp
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "no_warnings": True,
            "nocheckcertificate": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return vazio
            return {
                "titulo": info.get("title", ""),
                "descricao": (info.get("description") or "")[:3000],
                "duracao_seg": info.get("duration", 0),
                "canal": info.get("uploader", ""),
                "chapters": info.get("chapters") or [],
            }
    except Exception:
        return vazio


def _gemini_request(api_key: str, prompt: str, model: str = "gemini-1.5-flash") -> str:
    """Faz chamada à Gemini API via REST e retorna o texto gerado."""
    import ssl
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "%s:generateContent?key=%s" % (model, api_key)
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # cria contexto SSL permissivo para ambientes com proxy/cert corporativo
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        resultado = json.loads(resp.read().decode("utf-8"))
    return resultado["candidates"][0]["content"]["parts"][0]["text"]


_PROMPT_TEMPLATE = """
Você é um analista de mercado financeiro especializado em extração estruturada de informações.

Abaixo está o conteúdo de um vídeo de análise técnica / trade:

TÍTULO: {titulo}
CANAL: {canal}
CAPÍTULOS: {chapters}

TRANSCRIÇÃO:
{transcricao}

DESCRIÇÃO DO VÍDEO:
{descricao}

---

Com base nesse conteúdo, extraia TODOS os setups de trade mencionados (oportunidades de compra ou venda).

Para cada setup, retorne um objeto JSON com os campos:
- "ativo": ticker ou nome do ativo (ex: "BTC", "PETR4", "EUR/USD")
- "direcao": "LONG" ou "SHORT" ou "INDEFINIDO"
- "tipo_setup": tipo de padrão gráfico ou setup (ex: "Rompimento", "Pullback", "Bandeira", "Cunha", "Pivô", etc.)
- "timeframe": timeframe principal mencionado (ex: "M5", "M15", "H1", "D1")
- "entrada": preço ou região de entrada (string, ex: "50.000" ou "50.000–51.000" ou "no rompimento de 50.000")
- "stop": preço ou região de stop loss
- "alvo": preço ou região alvo (take profit); se múltiplos alvos, separe por " / "
- "risco_retorno": relação risco/retorno se mencionada (ex: "1:3")
- "contexto": resumo de 1-2 frases explicando o setup e o raciocínio do trader
- "confianca": "ALTA", "MEDIA" ou "BAIXA" — quão claramente o setup foi descrito

Retorne SOMENTE um array JSON válido (sem markdown, sem explicações, apenas o JSON).
Exemplo de formato esperado:
[
  {{
    "ativo": "BTC",
    "direcao": "LONG",
    "tipo_setup": "Rompimento de resistência",
    "timeframe": "H4",
    "entrada": "65.000",
    "stop": "63.000",
    "alvo": "70.000 / 75.000",
    "risco_retorno": "1:2.5",
    "contexto": "BTC testou resistência em 65k por 3 vezes; rompimento com volume acima da média sinaliza continuação de alta.",
    "confianca": "ALTA"
  }}
]

Se não houver nenhum setup identificável, retorne um array vazio: []
""".strip()


# ------------------------------------------------------------------ público

def processar_video(url: str, verbose: bool = True) -> list:
    """
    Processa um vídeo do YouTube e retorna lista de setups de trade extraídos.

    Parâmetros:
        url     — URL do vídeo no YouTube
        verbose — imprime progresso no terminal (padrão: True)

    Retorna:
        Lista de dicts, cada um representando um setup de trade.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "SUA_CHAVE_AQUI":
        raise EnvironmentError(
            "Defina a variável de ambiente GEMINI_API_KEY antes de chamar processar_video()."
        )

    vid_id = _video_id(url)
    if verbose:
        print("[extrator] Vídeo ID: %s" % vid_id)

    if verbose:
        print("[extrator] Obtendo transcrição...")
    transcricao = _obter_transcricao(vid_id)
    if verbose:
        print("[extrator] Transcrição: %d caracteres" % len(transcricao))

    if verbose:
        print("[extrator] Obtendo metadados via yt-dlp...")
    info = _obter_info_ytdlp(url)
    if verbose:
        print("[extrator] Título: %s" % (info["titulo"] or "(sem título)"))

    if not transcricao and not info["titulo"] and not info["descricao"]:
        raise RuntimeError(
            "Não foi possível obter conteúdo do vídeo %s. "
            "Verifique se a URL é válida e se o vídeo está público." % url
        )

    chapters_str = ""
    if info["chapters"]:
        chapters_str = "; ".join(
            "%s (%ds)" % (c.get("title", ""), int(c.get("start_time", 0)))
            for c in info["chapters"]
        )

    transcricao_truncada = transcricao[:12000] if transcricao else "(transcrição indisponível)"

    prompt = _PROMPT_TEMPLATE.format(
        titulo=info["titulo"],
        canal=info["canal"],
        chapters=chapters_str or "(sem capítulos)",
        transcricao=transcricao_truncada,
        descricao=info["descricao"] or "(sem descrição)",
    )

    if verbose:
        print("[extrator] Enviando para Gemini API...")

    for tentativa in range(3):
        try:
            resposta = _gemini_request(api_key, prompt)
            break
        except Exception as e:
            if tentativa == 2:
                raise
            espera = 2 ** (tentativa + 1)
            if verbose:
                print("[extrator] Erro na tentativa %d: %s. Aguardando %ds..." % (tentativa + 1, e, espera))
            time.sleep(espera)

    # limpa possível markdown residual
    texto = resposta.strip()
    texto = re.sub(r"^```(?:json)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)

    try:
        setups = json.loads(texto)
        if not isinstance(setups, list):
            setups = [setups]
    except json.JSONDecodeError:
        # tenta extrair array JSON embutido no texto
        m = re.search(r"\[.*\]", texto, re.DOTALL)
        if m:
            setups = json.loads(m.group())
        else:
            if verbose:
                print("[extrator] Aviso: resposta não é JSON válido.\n%s" % texto[:500])
            setups = []

    if verbose:
        print("[extrator] %d setup(s) extraído(s)." % len(setups))

    return setups


# ------------------------------------------------------------------ CLI rápida

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python extrator_setups.py <url_youtube>")
        sys.exit(1)

    resultado = processar_video(sys.argv[1])
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
