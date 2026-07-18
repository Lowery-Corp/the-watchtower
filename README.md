# The Watchtower

Backend foundation for an event-driven logging and uptime monitoring service. The current milestone provides FastAPI operational endpoints, structured request correlation, async SQLAlchemy, PostgreSQL, and Alembic-managed database schema versioning. Event ingestion, transactional outbox records, and Kafka publishing are planned next.

## Runtime architecture

```text
client -> FastAPI :8010 -> async SQLAlchemy -> PostgreSQL
                         Alembic migrate ---^
```

Compose runs:

- `db`: PostgreSQL 17 with an internal-only port and persistent named volume.
- `migrate`: one-shot `alembic upgrade head` service.
- `api`: non-root FastAPI/uvicorn runtime exposed on host port `8010` by default.
- `test`: profile-gated image containing the test, lint, and type-check tools.

## Prerequisites

- Docker Engine
- Docker Compose v2
- Git over SSH for repository access

All development is performed on `vm-work-dev-db` in `/home/lowery/the-watchtower` on branch `dev`.

## Configuration

Copy `.env.example` to `.env` and replace the development password before shared or persistent use:

```bash
cp .env.example .env
```

The application reads `WATCHTOWER_`-prefixed settings. Never commit `.env`.

## Build and start

```bash
cd /home/lowery/the-watchtower
docker compose config -q
docker compose --profile test build
docker compose up -d db api
docker compose ps
```

The migration service must complete successfully before the API starts.

## Operational endpoints

```text
GET http://127.0.0.1:8010/api/v1/health
GET http://127.0.0.1:8010/api/v1/health/live
GET http://127.0.0.1:8010/api/v1/health/ready
GET http://127.0.0.1:8010/api/v1/openapi.json
```

- `health`: basic API status.
- `live`: process liveness; does not require PostgreSQL.
- `ready`: executes `SELECT 1` through an async SQLAlchemy session and returns 503 if PostgreSQL is unavailable.
- Every HTTP response includes `X-Request-ID`. Safe caller-provided IDs are preserved; invalid values are replaced.

## Tests and quality gates

Run everything inside the Compose test image:

```bash
docker compose run --rm test pytest -v
docker compose run --rm test ruff check src tests alembic
docker compose run --rm test mypy src tests
```

The integration suite uses real PostgreSQL rather than SQLite.

## Alembic

```bash
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic history
```

Migration downgrades can remove database objects. Obtain explicit authorization and verify backups/scope before running them outside an empty development database.

## Logs and shutdown

```bash
docker compose logs --tail 100 api
docker compose stop api db
```

Do not run `docker compose down -v` unless permanent deletion of the PostgreSQL volume is explicitly intended.

## Development rules

- Work and push only on `dev`; do not push implementation commits directly to `main`.
- Use tests first for behavior changes.
- Keep endpoint modules thin; service/use-case code owns transactions.
- Repositories never commit implicitly.
- Keep credentials, event payloads containing private data, and generated artifacts out of Git.
- Read `AGENTS.md` and the current plan under `.hermes/plans/` before changing architecture.
