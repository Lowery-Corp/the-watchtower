# The Watchtower

Full-stack tenant-aware event logging and uptime monitoring control plane. Its JavaScript React operator UI provides browser login, profile-aware Home metrics, monitored-service lifecycle management, and managed API-key operations over the existing external authentication, local profiles, authenticated event ingestion, immutable PostgreSQL history, transactional outbox, and Alembic-managed schema.

## Runtime architecture

```text
browser --> Nginx edge :8010 --> static React image :8080
   |               |
   |               +--> /api/* --> FastAPI :8000 --stable auth UUID--> local profile
   |                                      |
machine --managed API key----------------+--> profile-scoped transaction
legacy ----mapped HMAC--------------------+       |--> immutable PostgreSQL event
                                                 +--> Kafka-ready outbox row
```

The browser and API share one origin at the Nginx edge. FastAPI stores the external session only in an HttpOnly cookie, while React keeps sanitized current-user metadata in memory. Kafka publishing is deliberately decoupled from the request transaction and remains the next broker-integration milestone.

Compose runs:

- `db`: PostgreSQL 17 with a persistent named volume and host port `5433` by default; bind or firewall that development port appropriately.
- `migrate`: one-shot `alembic upgrade head` service.
- `api`: internal-only, non-root FastAPI/uvicorn runtime on Compose port `8000`.
- `frontend`: non-root Nginx runtime serving the prebuilt React bundle on internal Compose port `8080`.
- `frontend-tools`: profile-gated Node image containing frontend tests, lint, build, and audit tooling.
- `proxy`: non-root Nginx edge exposed on host port `8010` by default; it serves the frontend, routes `/api/*` to FastAPI, applies the webhook body cap, and enforces the per-IP webhook limit.
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

- `WATCHTOWER_AUTH_SERVICE_URL` points to the external DB Management Auth API. Browser tokens are held only in an HttpOnly cookie and are never persisted by Watchtower.
- `WATCHTOWER_BROWSER_ALLOWED_ORIGINS` is a JSON array of exact trusted origins. It must include every URL from which operators load the frontend, including the scheme and published edge port. Cookie-authenticated mutations fail closed unless the request supplies one of these origins.
- `WATCHTOWER_SESSION_COOKIE_SECURE` is `false` only for local HTTP development. Set it to `true` behind production HTTPS.
- The browser UI and API intentionally use the same origin. Separate-origin deployment is not supported without adding credentialed CORS policy to FastAPI.
- `WATCHTOWER_WEBHOOK_SECRETS` is a JSON object mapping legacy service slugs to HMAC secrets.
- `WATCHTOWER_LEGACY_WEBHOOK_PROFILES` is a JSON object mapping every enabled legacy slug to its owning profile UUID. A secret without an explicit profile mapping cannot authenticate.

Managed API keys are created through the authenticated API. Watchtower returns the raw key once with `Cache-Control: no-store`, then stores only a version, non-secret lookup prefix, and domain-separated SHA-256 verifier. Lost keys cannot be recovered; create a replacement and revoke the old metadata row. Service binding and scopes are immutable, revocation is permanent, and ordinary updates cannot extend or remove an expiry.

The default signature freshness window is 300 seconds and the default maximum raw webhook body is 262,144 bytes (256 KiB). The application allows 60 successfully authenticated requests per managed key or mapped legacy sender per 60-second process-local window. Nginx independently limits the webhook path to 60 requests per minute per client IP with a burst of 20; production ingress must preserve an authoritative client address rather than trusting caller-supplied forwarding headers. Managed bearer keys require TLS at or before the trusted edge; the Compose Nginx listener itself is HTTP and must not be exposed directly to an untrusted network.

## Build and start

```bash
cd /home/lowery/the-watchtower
docker compose config -q
docker compose --profile test build
docker compose up -d db proxy
docker compose ps
```

The migration service must complete successfully before the API starts. Open the operator UI at `http://127.0.0.1:8010/`; anonymous users are redirected to `/login`. The Home, Monitored Services, and API Keys routes require a valid external-auth browser session.

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

## Authentication and profile-owned resources

Browser session endpoints:

```text
POST /api/v1/auth/login
GET  /api/v1/auth/me
POST /api/v1/auth/logout
```

`POST /auth/login` validates credentials and returns an empty `204` while establishing the HttpOnly session cookie; it does not return identity data. `GET /auth/me` is protected and is the sole browser endpoint that returns the current external identity and local profile metadata. A successful `/auth/me` request provisions exactly one local profile for the external service's stable UUID. Email, username, and display name are not ownership keys. Auth-service transport failures return `503`, malformed successful responses return `502`, and invalid sessions return a generic `401`.

Authenticated resource endpoints:

```text
POST/GET       /api/v1/services
GET/PATCH/DELETE /api/v1/services/{service_id}
POST/GET       /api/v1/api-keys
GET/PATCH/DELETE /api/v1/api-keys/{api_key_id}
```

All identity, service, and API-key information routes require a validated session cookie or explicit bearer credential. All resource lookups and mutations are profile-scoped; anonymous requests return `401`, and cross-profile object probes return `404`. Cookie-authenticated POST, PATCH, and DELETE requests require one exact trusted `Origin`.

The protected React route `/services` provides create, list, edit, deactivate, and reactivate controls. Service slugs are immutable webhook identities; display name, environment, and active state are mutable. `DELETE` on a service deactivates it while retaining historical events. `DELETE` on an API key means irreversible soft revocation. A key creation response is the only response containing raw key material.

## Event ingestion

```text
POST http://127.0.0.1:8010/api/v1/webhooks/events
```

The endpoint always requires `X-Watchtower-Service` and accepts one of two authentication modes:

1. preferred managed mode: `X-Watchtower-API-Key`; or
2. temporary legacy mode: both `X-Watchtower-Timestamp` and `X-Watchtower-Signature`, with explicit secret and profile mappings.

A valid event and its `watchtower.events.raw.v1` outbox message commit in one profile transaction. Retrying the same profile/service/event ID returns `202` with `status: duplicate` and creates no additional rows.

See [`docs/event-contract.md`](docs/event-contract.md) for the exact envelope, signing algorithm, response contract, and sender example.

## Tests and quality gates

Run everything inside the Compose test image:

```bash
docker compose run --rm test pytest -v
docker compose run --rm test ruff check src tests alembic
docker compose run --rm test mypy src tests
docker compose run --rm --no-deps frontend-tools npm test
docker compose run --rm --no-deps frontend-tools npm run lint
docker compose run --rm --no-deps frontend-tools npm run build
docker compose run --rm --no-deps frontend-tools npm audit --audit-level=high
```

The integration suite uses real PostgreSQL rather than SQLite.

## Alembic

```bash
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic history
```

Migration downgrades can remove database objects. Obtain explicit authorization and verify backups/scope before running them outside an empty development database.

## Automated deployment

`.github/workflows/deploy.yml` follows the same single-job structure as Scrappy and runs on pushes to `main`. The `build and deploy` GitHub environment must provide:

```text
DOCKERHUB_USERNAME
DOCKERHUB_TOKEN
TS_OAUTH_CLIENT_ID
TS_OAUTH_SECRET
SERVER_HOST
SERVER_USER
SERVER_SSH_KEY
```

Before publishing, the job validates Compose, builds the backend/frontend test images, runs the backend and frontend tests, and lints the frontend. It then publishes both `latest` and commit-SHA tags:

```text
<dockerhub-user>/watchtower-frontend:latest
<dockerhub-user>/watchtower-frontend:<git-sha>
<dockerhub-user>/watchtower-api:latest
<dockerhub-user>/watchtower-api:<git-sha>
```

After connecting through Tailscale, the job pulls the latest images, changes to `/home/<server-user>/the-watchtower`, runs the same Compose shutdown/rebuild sequence used by Scrappy, and prunes unused images. The server's ignored `.env` continues to supply Watchtower runtime configuration.

## Logs and shutdown

```bash
docker compose logs --tail 100 proxy frontend api
docker compose stop proxy frontend api db
```

Do not run `docker compose down -v` unless permanent deletion of the PostgreSQL volume is explicitly intended.

## Development rules

- Work and push only on `dev`; do not push implementation commits directly to `main`.
- Use tests first for behavior changes.
- Keep endpoint modules thin; service/use-case code owns transactions.
- Repositories never commit implicitly.
- Keep credentials, event payloads containing private data, and generated artifacts out of Git.
- Read `AGENTS.md` and the current plan under `.hermes/plans/` before changing architecture.
