"""
API-level tests for the Vercel FastAPI app.  Run with:  pytest -q

Covers /api/health, /api/analyze (happy path + edge cases), the 4 MB cap,
and JSON-safety (no NaN/inf leaking into the response).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generate_sample_log as gen  # noqa: E402
from api.index import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def sample_text() -> str:
    """Same 6,000-line seeded log the pipeline fixture uses."""
    return "\n".join(gen.generate(6000, 42, datetime(2026, 10, 9, 2, 30), 60, 22))


def _analyze(text: str, **overrides) -> dict:
    payload = {"text": text, **overrides}
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200, resp.text[:500]
    return resp.json()


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #


def test_health() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --------------------------------------------------------------------------- #
# happy path
# --------------------------------------------------------------------------- #


def test_sample_finds_payment_root_cause(sample_text: str) -> None:
    data = _analyze(sample_text)
    assert data["error"] is None
    incidents = data["incidents"]
    assert incidents, "expected ranked incidents"

    trigger = next(i for i in incidents if i["role"] == "trigger")
    assert trigger["services"] == ["payment-svc"]
    assert "Database connection timeout" in trigger["template"]
    assert trigger["first_seen"][11:16] == "02:52"

    knock_ons = [i for i in incidents if i["role"] == "knock-on"]
    assert len(knock_ons) >= 5

    # Trigger ranks first and the trigger id is exposed for the cascade strip.
    assert incidents[0]["role"] == "trigger"
    assert data["trigger_id"] == trigger["cluster_id"]


def test_response_shape(sample_text: str) -> None:
    data = _analyze(sample_text)
    for key in (
        "stats",
        "window",
        "notes",
        "trigger_id",
        "fallback_mode",
        "incidents",
        "timeline",
        "severity_counts",
        "service_counts",
    ):
        assert key in data

    stats = data["stats"]
    assert stats["total_lines"] == 6000
    assert stats["parsed"] > 0
    assert stats["n_services_total"] == 5
    assert stats["seconds"] >= 0

    window = data["window"]
    assert window["bucket_s"] in (10, 60, 300, 3600, 86400)
    assert window["t0"] and window["t1"] and window["span_s"] >= 0

    inc = data["incidents"][0]
    for key in (
        "rank",
        "cluster_id",
        "template",
        "count",
        "max_severity",
        "services",
        "n_services",
        "first_seen",
        "last_seen",
        "growth_ratio",
        "role",
        "role_detail",
        "lag_s",
        "score",
        "score_breakdown",
        "sample_raw",
        "sample_line_no",
        "onset",
        "sparkline",
        "raw_lines",
        "raw_lines_total",
    ):
        assert key in inc

    # Score breakdown has exactly the five factors and they add up.
    assert len(inc["score_breakdown"]) == 5
    points = sum(row["Points"] for row in inc["score_breakdown"])
    assert abs(points - inc["score"]) < 0.5

    # Raw lines are capped at 500 and sorted by timestamp.
    for i in data["incidents"]:
        assert len(i["raw_lines"]) <= 500
    stamps = [r["timestamp"] for r in inc["raw_lines"]]
    assert stamps == sorted(stamps)


def test_timeline_stacking(sample_text: str) -> None:
    data = _analyze(sample_text)
    rows = data["timeline"]
    assert rows
    by_bucket: dict = {}
    for row in rows:
        by_bucket.setdefault(row["bucket"], []).append(row)
        assert row["y1"] - row["y0"] == row["lines"]
    for rows_in_bucket in by_bucket.values():
        assert rows_in_bucket[0]["y0"] == 0
        for prev, cur in zip(rows_in_bucket, rows_in_bucket[1:]):
            assert cur["y0"] == prev["y1"]


def test_json_is_strictly_valid(sample_text: str) -> None:
    """allow_nan=False raises on NaN/inf, so this catches serialization leaks."""
    data = _analyze(sample_text)
    json.dumps(data, allow_nan=False)


def test_controls_are_respected(sample_text: str) -> None:
    data = _analyze(
        sample_text,
        min_severity="ERROR",
        similarity=0.7,
        knock_on_minutes=1,
        weights={"count": 0.5, "severity": 0.2, "services": 0.1, "growth": 0.1, "start": 0.1},
    )
    assert data["error"] is None
    assert all(i["max_severity"] in ("ERROR", "CRITICAL") for i in data["incidents"])
    top = data["incidents"][0]
    weights = [row["Weight"] for row in top["score_breakdown"]]
    assert weights == [0.5, 0.2, 0.1, 0.1, 0.1]


# --------------------------------------------------------------------------- #
# edge cases -> 200 with a reason, never a 500
# --------------------------------------------------------------------------- #


def test_empty_text() -> None:
    data = _analyze("")
    assert data["empty_reason"] == "empty_input"
    assert data["error"]
    assert data["incidents"] == []


def test_whitespace_only() -> None:
    data = _analyze("   \n\n  ")
    assert data["empty_reason"] == "empty_input"


def test_garbage_text() -> None:
    data = _analyze("not a log at all\nneither is this\nstill no timestamps")
    assert data["empty_reason"] == "no_timestamps"
    assert data["stats"]["skipped"] >= 1
    assert data["stats"]["skipped_samples"]


def test_severity_filter_with_no_candidates() -> None:
    text = "2026-10-09 03:00:00 INFO [web] everything is fine"
    data = _analyze(text, min_severity="ERROR")
    assert data["empty_reason"] == "no_severity_lines"
    assert data["stats"]["parsed"] == 1


def test_oversized_payload_returns_413() -> None:
    text = "x" * 4_000_001
    resp = client.post("/api/analyze", json={"text": text})
    assert resp.status_code == 413
    assert "4 MB" in resp.json()["detail"]


def test_payload_at_limit_is_accepted() -> None:
    text = "2026-10-09 03:00:00 ERROR [web] boom\n" * 1
    text = text + " " * (3_999_000 - len(text))
    resp = client.post("/api/analyze", json={"text": text})
    assert resp.status_code == 200


def test_tfidf_works_or_is_rejected_cleanly(sample_text: str) -> None:
    resp = client.post("/api/analyze", json={"text": sample_text[:120000], "method": "tfidf"})
    if resp.status_code == 400:
        assert "not available in this deployment" in resp.json()["detail"]
    else:
        assert resp.status_code == 200
        assert resp.json()["incidents"]


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "x", "min_severity": "TRACE"},
        {"text": "x", "method": "kmeans"},
        {"text": "x", "similarity": 0.95},
        {"text": "x", "similarity": 0.1},
        {"text": "x", "knock_on_minutes": 0},
        {"text": "x", "knock_on_minutes": 60},
        {"text": "x", "weights": {"count": 2.0}},
    ],
)
def test_invalid_payloads_are_422(payload: dict) -> None:
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 422


def test_defaults_are_applied() -> None:
    """No optional fields -> WARN/drain/0.5/5/default weights."""
    text = "2026-10-09 03:00:00 ERROR [web] boom\n2026-10-09 03:00:01 INFO [web] ok"
    data = _analyze(text)
    assert data["stats"]["candidate_count"] == 1
    top = data["incidents"][0]
    assert [row["Weight"] for row in top["score_breakdown"]] == [0.30, 0.25, 0.20, 0.15, 0.10]


# --------------------------------------------------------------------------- #
# Vercel rewrite compatibility
# --------------------------------------------------------------------------- #


def test_rewritten_paths_still_route() -> None:
    """Whether Vercel forwards /api/analyze or the rewritten /api/index[/...],
    both must reach the same handlers."""
    assert client.get("/api/index").status_code == 200
    assert client.get("/api/index").json() == {"status": "ok"}
    assert client.get("/api/index/health").json() == {"status": "ok"}

    text = "2026-10-09 03:00:00 ERROR [x] boom\n2026-10-09 03:00:01 ERROR [x] boom"
    for path in ("/api/analyze", "/api/index/analyze", "/api/index"):
        resp = client.post(path, json={"text": text})
        assert resp.status_code == 200, path
        assert resp.json()["incidents"], path
