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
        -exec chmod 0644 {} +

USER agenthire

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime AS smoke

COPY --chown=agenthire:agenthire scripts ./scripts

RUN find scripts \
        -type f \
        -name "*.py" \
        -exec chmod 0644 {} +

CMD ["python", "-m", "scripts.docker_smoke"]


FROM foundation AS test

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

RUN find app migrations tests scripts \
        -type f \
        -name "*.py" \
        -exec chmod 0644 {} +

USER agenthire

CMD ["pytest"]
