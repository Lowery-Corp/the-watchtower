# Profile uptime API

The profile uptime API is a read-only machine integration for the current uptime state visible to one Watchtower profile. It adds exactly one route, `GET /api/v1/uptime`; key issue and reissue continue to use the existing API Keys page and `POST /api/v1/api-keys`.

## Credential boundaries

Watchtower has two deliberately separate managed-key classes:

| Credential | Token prefix | Binding | Sole scope | Accepted by |
| --- | --- | --- | --- | --- |
| Service ingestion key | `wtk_v1_` | service-bound | `events:write` | `POST /api/v1/webhooks/events` |
| Profile uptime key | `wtp_v1_` | profile-bound | `uptime:read` | `GET /api/v1/uptime` |

The formats, digest domains, database constraints, and authentication paths are distinct. A profile uptime key cannot submit events, and a service ingestion key cannot read profile uptime.

Raw credentials are one-time disclosures. Watchtower stores only the non-secret lookup prefix and a domain-separated digest. Never log, persist, or place a raw key in a URL.

## Issue and reissue

In the authenticated operator UI, open **API Keys** and use the **Profile Uptime API** panel:

1. **Issue key** creates the profile's singleton key and discloses the raw token once.
2. Store the token in the caller's secret manager before closing the dialog; it cannot be recovered later.
3. **Reissue key** rotates the same durable key row, immediately invalidates the previous token, and discloses the replacement once.

The API equivalent uses the existing browser-authenticated management route:

```http
POST /api/v1/api-keys
Content-Type: application/json

{"credential_kind":"profile_uptime"}
```

Initial issue returns `201 Created`; reissue returns `200 OK`. Both responses use `Cache-Control: no-store`. Profile uptime keys cannot be renamed, expired, rebound, or revoked through the generic PATCH/DELETE lifecycle; issue/reissue is their complete lifecycle.

## Request

Use TLS at or before a trusted ingress. The checked-in Compose API listener is loopback HTTP for local use and must not be exposed directly to an untrusted network.

```http
GET /api/v1/uptime
X-Watchtower-Profile-Key: wtp_v1_<16-character-prefix>.<43-character-secret>
```

Callers never send a profile ID or service selector. Watchtower derives the profile from the credential and applies the profile's current PostgreSQL `applications.read` grants.

## Response

A successful response returns `200 OK`, `Cache-Control: no-store`, and `X-Request-ID`:

```json
{
  "profile": {"id": "2b168a7d-46d8-44d8-a907-56c06f1cd497"},
  "generated_at": "2026-09-21T22:50:00Z",
  "services": [
    {
      "id": "64da9741-70ce-4108-9ae9-3908c1549948",
      "slug": "payments-api",
      "display_name": "Payments API",
      "environment": "production",
      "active": true,
      "monitors": [
        {
          "id": "dfb6a2e3-b56d-4f76-97be-a792036c59fc",
          "url": "https://payments.example.com/health",
          "status": "up",
          "last_checked_at": "2026-09-21T22:49:41Z",
          "status_code": 200,
          "response_time_ms": 84,
          "uptime_24h_percent": 99.93
        }
      ]
    }
  ]
}
```

Every readable service is present, including services with `monitors: []`. Only active monitors are nested. Monitor status is `pending`, `up`, or `down`. The uptime percentage uses checks in the fixed 24-hour rolling window; a monitor without checks in that window returns `null`.

Detailed history, custom windows, pagination, public status pages, alert delivery, and uptime writes are out of scope. The response also excludes event payloads, role assignments, API-key metadata, profile display names, and internal failure details.

## Errors and limits

- `401 Unauthorized`: missing, duplicate, malformed, unknown, or superseded credentials all return the same generic `{"detail":"Invalid profile uptime authentication"}` response. Do not use the response to infer key state.
- `403 Forbidden`: a valid key belongs to a suspended profile.
- `429 Too Many Requests`: the PostgreSQL-backed profile-key budget is exhausted. Honor the integer `Retry-After` response header before retrying.
- `503 Service Unavailable`: PostgreSQL/readiness failure under the API's existing failure policy.

The bounded request budget is configured with:

```text
WATCHTOWER_UPTIME_API_RATE_LIMIT_REQUESTS=60
WATCHTOWER_UPTIME_API_RATE_LIMIT_WINDOW_SECONDS=60
```

The defaults permit 60 successful authenticated requests per 60-second window. Invalid authentication does not consume a profile's budget, and a rate-limited request does not update key `last_used_at`.
