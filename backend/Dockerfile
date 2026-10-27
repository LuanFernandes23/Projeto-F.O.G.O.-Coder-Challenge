# syntax=docker/dockerfile:1

# ---- build: instala as dependências fixadas em um venv isolado
FROM python:3.12-slim-bookworm AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --require-virtualenv -r requirements.txt
# Modelo de embeddings local (multilíngue, 384 dimensões, ~0,22 GB) baixado no build:
# o RAG funciona sem chave de API e sem internet em runtime.
ARG EMBEDDINGS_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDINGS_MODEL}', cache_dir='/opt/models')"

# ---- runtime: imagem enxuta, usuário sem privilégios
FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    EMBEDDINGS_CACHE_DIR=/opt/models \
    HF_HUB_OFFLINE=1
RUN groupadd --system fogo \
    && useradd --system --gid fogo --home /app fogo \
    && mkdir /app && chown fogo:fogo /app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=fogo:fogo /opt/models /opt/models
COPY --chown=fogo:fogo alembic.ini pyproject.toml ./
COPY --chown=fogo:fogo migrations ./migrations
COPY --chown=fogo:fogo knowledge ./knowledge
COPY --chown=fogo:fogo app ./app
USER fogo
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

# ---- test: runtime + ferramentas de qualidade e a suíte de testes
#      docker compose --profile test run --rm tests
FROM build AS build-dev
COPY requirements-dev.txt .
RUN pip install --require-virtualenv -r requirements-dev.txt

FROM runtime AS test
COPY --from=build-dev /opt/venv /opt/venv
COPY --chown=fogo:fogo tests ./tests
CMD ["sh", "-c", "ruff check app tests && mypy && pytest -q -p no:cacheprovider"]
