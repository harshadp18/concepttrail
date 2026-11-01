"""HTTP hardening: CORS, security headers, body limit, docs exposure, error envelope, probes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.api.v1 import health
from app.core.config import get_settings
from app.core.rate_limit import RateLimiterUnavailable


def build(monkeypatch, **overrides):
    settings = get_settings().model_copy(update=overrides)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    application = main.create_app()

    @application.get("/boom")
    def boom():
        raise RuntimeError("SELECT secret_column FROM private_table")

    return TestClient(application, raise_server_exceptions=False)


ORIGIN = "https://app.school.example"


def test_cors_preflight_allows_only_configured_origins(monkeypatch) -> None:
    client = build(monkeypatch, cors_allowed_origins=ORIGIN)
    ok = client.options(
        "/api/v1/me",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert "authorization" in ok.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in ok.headers
    bad = client.options(
        "/api/v1/me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert bad.status_code == 400 and "access-control-allow-origin" not in bad.headers
    simple = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


def test_no_cors_headers_when_no_origin_is_configured(monkeypatch) -> None:
    client = build(monkeypatch, cors_allowed_origins="")
    r = client.options(
        "/api/v1/me", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in r.headers


def test_security_headers_and_request_id(monkeypatch) -> None:
    r = build(monkeypatch).get("/api/v1/me")
    assert r.status_code == 401
    for header in ("x-request-id", "x-content-type-options", "x-frame-options", "referrer-policy"):
        assert header in r.headers
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


def test_request_body_limit(monkeypatch) -> None:
    client = build(monkeypatch, max_request_body_bytes=2048)
    r = client.post(
        "/api/v1/auth/login",
        content=b'{"login_identifier": "' + b"a" * 4000 + b'"}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"


def test_docs_can_be_disabled(monkeypatch) -> None:
    client = build(monkeypatch, api_docs_enabled=False)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert build(monkeypatch, api_docs_enabled=True).get("/openapi.json").status_code == 200


def test_trusted_hosts(monkeypatch) -> None:
    client = build(monkeypatch, trusted_hosts="api.school.example")
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/health", headers={"Host": "api.school.example"}).status_code == 200


def test_unhandled_errors_do_not_leak_internals(monkeypatch) -> None:
    r = build(monkeypatch).get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret_column" not in r.text and "Traceback" not in r.text


def test_readiness_reports_required_dependencies(monkeypatch) -> None:
    client = build(monkeypatch)
    monkeypatch.setattr(health, "_database_ok", lambda: True)
    monkeypatch.setattr(health, "_model_state", lambda: "unavailable")
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json()["checks"]["rate_limiter"] == "ok"
    assert ready.json()["optional"]["local_model"] == "unavailable"  # does not fail readiness

    class Down:
        def healthy(self):
            raise RateLimiterUnavailable("down")

    monkeypatch.setattr(health, "get_store", lambda: Down())
    down = client.get("/ready")
    assert down.status_code == 503 and down.json()["checks"]["rate_limiter"] == "failed"
    assert client.get("/health").status_code == 200  # liveness is independent


@pytest.mark.live_db
def test_readiness_against_the_real_database(monkeypatch) -> None:
    client = build(monkeypatch)
    monkeypatch.setattr(health, "_model_state", lambda: "unavailable")
    assert client.get("/ready").json()["checks"]["database"] == "ok"
