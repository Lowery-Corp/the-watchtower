FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/

RUN pip install --no-cache-dir .

FROM base AS test
RUN pip install --no-cache-dir ".[dev]"
COPY Dockerfile compose.yaml .env.example README.md AGENTS.md ./
COPY docs/ ./docs/
COPY watchtowersHouse/Dockerfile watchtowersHouse/server.mjs watchtowersHouse/vite.config.js ./watchtowersHouse/
COPY tests/ ./tests/
CMD ["pytest", "-v"]

FROM base AS runtime
RUN groupadd --system watchtower \
    && useradd --system --gid watchtower --home-dir /app watchtower \
    && chown -R watchtower:watchtower /app
USER watchtower
EXPOSE 8000
CMD ["uvicorn", "watchtower.main:app", "--host", "0.0.0.0", "--port", "8000"]
