FROM python:3.12-slim-bookworm AS foundation

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN addgroup --system agenthire \
    && adduser --system --ingroup agenthire agenthire

COPY pyproject.toml uv.lock ./


FROM foundation AS runtime

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --locked \
        --no-dev \
        --no-install-project

COPY --chown=agenthire:agenthire app ./app
COPY --chown=agenthire:agenthire migrations ./migrations
COPY --chown=agenthire:agenthire alembic.ini ./

RUN find app migrations \
        -type f \
        -name "*.py" \
        -exec chmod 0644 {} + \
    && mkdir -p /app/storage/candidate_documents \
    && chown -R agenthire:agenthire /app/storage \
    && chmod 0700 /app/storage/candidate_documents

USER agenthire

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]


FROM runtime AS extraction-worker

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils util-linux \
    && rm -rf /var/lib/apt/lists/*

USER agenthire

CMD ["python", "-m", "app.workers.document_extraction"]


FROM runtime AS embedding-worker

CMD ["python", "-m", "app.workers.document_embeddings"]


FROM runtime AS smoke

COPY --chown=agenthire:agenthire scripts ./scripts

RUN find scripts \
        -type f \
        -name "*.py" \
        -exec chmod 0644 {} +

CMD ["python", "-m", "scripts.docker_smoke"]


FROM public.ecr.aws/docker/library/node:24-bookworm-slim AS ui-test-runtime

FROM foundation AS test

COPY --from=ui-test-runtime /usr/local/bin/node /usr/local/bin/node

RUN apt-get update \
    && apt-get install -y --no-install-recommends git poppler-utils util-linux libstdc++6 libatomic1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTEST_ADDOPTS="-p no:cacheprovider" \
    RUFF_NO_CACHE=true

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --locked \
        --no-install-project

COPY --chown=agenthire:agenthire app ./app
COPY --chown=agenthire:agenthire migrations ./migrations
COPY --chown=agenthire:agenthire tests ./tests
COPY --chown=agenthire:agenthire scripts ./scripts
COPY --chown=agenthire:agenthire alembic.ini ./
COPY --chown=agenthire:agenthire README.md Dockerfile compose.yaml compose.ci.yaml compose.quality.yaml ./
COPY --chown=agenthire:agenthire docs ./docs
COPY --chown=agenthire:agenthire .github ./.github

RUN find app migrations tests scripts \
        -type f \
        -name "*.py" \
        -exec chmod 0644 {} +

USER agenthire

CMD ["pytest"]
