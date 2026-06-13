FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libgomp1 \
    ca-certificates \
    curl \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install torch CPU-only FIRST (saves ~1.8 GB vs full CUDA torch)
RUN pip install --no-cache-dir \
    "numpy<2" \
    torch==2.5.1+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu

# Python dependencies (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download HuggingFace embedding model during build (baked into image).
# Stored at /root/.cache/huggingface/ — no network access needed at runtime.
RUN python -c "\
from langchain_huggingface import HuggingFaceEmbeddings; \
HuggingFaceEmbeddings(model_name='intfloat/multilingual-e5-small', model_kwargs={'device': 'cpu'})"

# Source code + chroma_db/biblioteca/ (pre-indexed books) + books/
# .dockerignore excludes: venv/, .env, __pycache__/, .git/, outputs/
COPY . .

# Outputs directory for exported JSON reports
RUN mkdir -p /app/outputs

# Prevent any HuggingFace network calls at runtime (model already baked in)
ENV TRANSFORMERS_OFFLINE=1
ENV HF_DATASETS_OFFLINE=1

ENV PORT=8080
EXPOSE 8080

# Backend FastAPI — el frontend React vive en su propio servicio (web/)
# Un solo worker: el registro de documentos y el lock de runs viven en memoria del proceso.
# timeout-keep-alive alto para que Cloud Run no corte el stream SSE de progreso.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75"]
