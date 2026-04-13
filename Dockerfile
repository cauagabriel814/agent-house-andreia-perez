# ============================================================
# Dockerfile — Andreia / Residere Agent
# Usado tanto pelo serviço API quanto pelo Worker
# ============================================================
FROM python:3.13-slim

# ---- Dependências de sistema --------------------------------
# ffmpeg    → openai-whisper (transcrição de áudio)
# libmagic1 → python-magic (detecção de tipo de arquivo)
# curl      → healthcheck da API
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Dependências Python (cache de layer) -------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Código-fonte ------------------------------------------
COPY . .

# ---- Diretório persistente para ChromaDB -------------------
RUN mkdir -p /app/data/chroma

EXPOSE 8000
