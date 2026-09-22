"""Public route, configuration, and documentation contracts for profile uptime."""

from pathlib import Path

from watchtower.main import create_app

EXPECTED_API_ROUTES = {
    ("DELETE", "/api/v1/api-keys/{api_key_id}"),
    ("DELETE", "/api/v1/services/{service_id}"),
    ("DELETE", "/api/v1/services/{service_id}/memberships/{profile_id}"),
    ("DELETE", "/api/v1/uptime-monitors/{monitor_id}"),
    ("GET", "/api/v1/api-keys"),
    ("GET", "/api/v1/api-keys/{api_key_id}"),
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/live"),
    ("GET", "/api/v1/health/ready"),
    ("GET", "/api/v1/services"),
    ("GET", "/api/v1/services/{service_id}"),
    ("GET", "/api/v1/services/{service_id}/memberships"),
    ("GET", "/api/v1/uptime"),
    ("GET", "/api/v1/uptime-monitors"),
    ("PATCH", "/api/v1/api-keys/{api_key_id}"),
    ("PATCH", "/api/v1/services/{service_id}"),
    ("POST", "/api/v1/api-keys"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/services"),
    ("POST", "/api/v1/uptime-monitors"),
    ("POST", "/api/v1/webhooks/events"),
    ("PUT", "/api/v1/services/{service_id}/memberships/{profile_id}"),
}


def test_profile_uptime_adds_exactly_one_public_route_contract() -> None:
    paths = create_app().openapi()["paths"]
    routes = {
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
    }

    assert routes == EXPECTED_API_ROUTES
    assert {(method, path) for method, path in routes if path == "/api/v1/uptime"} == {
        ("GET", "/api/v1/uptime")
    }


def test_profile_uptime_openapi_declares_header_and_generic_errors() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/uptime"]["get"]
    parameters = operation["parameters"]

    assert parameters == [
        {
            "name": "X-Watchtower-Profile-Key",
            "in": "header",
            "required": True,
            "description": "Profile uptime machine credential",
            "schema": {
                "type": "string",
                "pattern": r"^wtp_v1_[A-Za-z0-9_-]{16}\.[A-Za-z0-9_-]{43}$",
            },
        }
    ]
    assert "example" not in parameters[0]
    assert operation["responses"]["401"]["description"] == (
        "Invalid profile uptime authentication"
    )
    assert operation["responses"]["403"]["description"] == "Profile is suspended"
    assert operation["responses"]["429"]["headers"]["Retry-After"]["schema"] == {
        "type": "integer",
        "minimum": 1,
    }


def test_compose_carries_bounded_uptime_api_rate_settings() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    api_section = compose.split("  api:", 1)[1].split("\n  uptime-worker:", 1)[0]

    assert sum(
        line.strip().startswith("WATCHTOWER_UPTIME_API_RATE_LIMIT_REQUESTS:")
        for line in api_section.splitlines()
    ) == 1
    assert (
        "WATCHTOWER_UPTIME_API_RATE_LIMIT_REQUESTS: "
        "${WATCHTOWER_UPTIME_API_RATE_LIMIT_REQUESTS:-60}"
    ) in api_section
    assert sum(
        line.strip().startswith("WATCHTOWER_UPTIME_API_RATE_LIMIT_WINDOW_SECONDS:")
        for line in api_section.splitlines()
    ) == 1
    assert (
        "WATCHTOWER_UPTIME_API_RATE_LIMIT_WINDOW_SECONDS: "
        "${WATCHTOWER_UPTIME_API_RATE_LIMIT_WINDOW_SECONDS:-60}"
    ) in api_section


def test_profile_uptime_documentation_freezes_security_and_scope_contract() -> None:
    guide = Path("docs/profile-uptime-api.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")

    for required in (
        "`wtk_v1_`",
        "`events:write`",
        "service-bound",
        "`wtp_v1_`",
        "`uptime:read`",
        "profile-bound",
        "GET /api/v1/uptime",
        "X-Watchtower-Profile-Key",
        "one-time",
        "reissue",
        "immediately invalidates",
        "TLS",
        "never send a profile ID",
        "fixed 24-hour",
        "custom windows",
        "history",
        "401",
        "403",
        "429",
        "Retry-After",
    ):
        assert required in guide
    assert "docs/profile-uptime-api.md" in readme
    assert "WATCHTOWER_UPTIME_API_RATE_LIMIT_REQUESTS" in readme
    assert "WATCHTOWER_UPTIME_API_RATE_LIMIT_WINDOW_SECONDS" in readme
    assert "# Profile uptime API request budget" in env_example
