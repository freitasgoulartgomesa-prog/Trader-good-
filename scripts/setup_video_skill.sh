#!/bin/bash
# Instala dependências necessárias para a skill video-analyze
set -e

echo "[1/3] Instalando yt-dlp..."
pip install yt-dlp --upgrade -q

echo "[2/3] Instalando imageio com ffmpeg embutido..."
pip install "imageio[ffmpeg]" -q

echo "[3/3] Instalando pacotes Python..."
pip install requests python-dotenv youtube-transcript-api groq -q

echo ""
echo "Dependências instaladas com sucesso!"
echo ""
echo "CONFIGURAÇÃO NECESSÁRIA:"
echo "  Edite o arquivo .env na raiz do projeto e preencha:"
echo "    YOUTUBE_API_KEY=sua_chave_aqui  (obrigatório)"
echo "    GROQ_API_KEY=sua_chave_aqui     (opcional - habilita transcrição de qualquer vídeo)"
echo ""
echo "  Obtenha sua chave Groq GRATUITA em: https://console.groq.com"
echo ""
echo "Use /video-analyze <URL> para analisar vídeos."
