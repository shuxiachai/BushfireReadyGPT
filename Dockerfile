# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 POETRY_VIRTUALENVS_CREATE=false
WORKDIR /app
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN python -m pip install poetry==2.3.4
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main,cloud --no-root && python -m pip check \
    && python -c "import dotenv, streamlit, fastembed, qdrant_client"

FROM dependencies AS assets
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY src ./src
COPY scripts ./scripts
COPY data_australia ./data_australia
ENV BUSHFIRE_RAG_EMBED_PROVIDER=fastembed \
    BUSHFIRE_RAG_EMBED_MODEL=BAAI/bge-small-en-v1.5 \
    BUSHFIRE_RAG_EMBED_CACHE_DIR=/opt/bushfire/models \
    BUSHFIRE_RAG_EMBED_THREADS=2 \
    BUSHFIRE_RAG_DIR=/opt/bushfire/seed/rag \
    BUSHFIRE_RAG_SOURCES_PATH=/app/data_australia/rag/sources.yml
RUN BUSHFIRE_RAG_EMBED_LOCAL_FILES_ONLY=false python scripts/build_rag_index.py --prepare-embedding-only
RUN python scripts/build_rag_index.py --download
# The national map is optional locally but included in the complete cloud demo.
# Raw downloads stay in this build stage; only processed data reaches the app image.
ARG BUSHFIRE_INCLUDE_NATIONAL_MAP=true
RUN if [ "$BUSHFIRE_INCLUDE_NATIONAL_MAP" = "true" ]; then python scripts/download_abs_sa2_all.py; fi
RUN chmod -R a+rX /opt/bushfire /app/data_australia

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PATH="/opt/venv/bin:$PATH" \
    BUSHFIRE_DEPLOYMENT_MODE=cloud BUSHFIRE_RUNTIME_DIR=/data \
    BUSHFIRE_RAG_ENABLED=true BUSHFIRE_RAG_EMBED_PROVIDER=fastembed \
    BUSHFIRE_RAG_EMBED_MODEL=BAAI/bge-small-en-v1.5 \
    BUSHFIRE_RAG_EMBED_CACHE_DIR=/opt/bushfire/models \
    BUSHFIRE_RAG_EMBED_THREADS=2 BUSHFIRE_RAG_EMBED_LOCAL_FILES_ONLY=true \
    BUSHFIRE_RAG_SEED_DIR=/opt/bushfire/seed/rag \
    BUSHFIRE_PDF_FONT_PATH=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc \
    LLM_PROVIDER=deepseek DEEPSEEK_MODEL=deepseek-v4-flash \
    BUSHFIRE_MODEL_MAX_RETRIES=0 BUSHFIRE_MODEL_TIMEOUT_SECONDS=120 \
    BUSHFIRE_ALLOW_EXTERNAL_MODEL=true
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates libgomp1 fonts-wqy-zenhei fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 bushfire \
    && useradd --uid 10001 --gid 10001 --create-home bushfire \
    && mkdir /data && chown bushfire:bushfire /data
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=assets /opt/bushfire /opt/bushfire
COPY --from=assets /app/data_australia/processed ./data_australia/processed
COPY data_australia ./data_australia
COPY src ./src
COPY scripts ./scripts
COPY docs ./docs
COPY examples ./examples
COPY .streamlit ./.streamlit
COPY pyproject.toml README.md LICENSE UPSTREAM.md ./
USER bushfire
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8501') + '/_stcore/health', timeout=4)"
ENTRYPOINT ["python", "scripts/start_container.py"]
