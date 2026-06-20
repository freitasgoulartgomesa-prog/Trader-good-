#!/bin/bash
# Instala dependências necessárias para a skill video-analyze
set -e

echo "[1/2] Instalando yt-dlp..."
pip install yt-dlp --upgrade -q

echo "[2/2] Instalando imageio com ffmpeg embutido..."
pip install "imageio[ffmpeg]" -q

echo ""
echo "Dependências instaladas com sucesso!"
echo "Use /video-analyze <URL> para analisar vídeos."
