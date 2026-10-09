"""
Lightweight tests for the LogLens pipeline.  Run with:  pytest -q
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generate_sample_log as gen  # noqa: E402
from cluster import DrainMiner, cluster_messages, normalise_message  # noqa: E402
from parser import parse_text  # noqa: E402
from rank import RankConfig, rank_incidents, score_breakdown  # noqa: E402


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "line, severity, service, message",
    [
        ("2026-10-09T03:00:01.123Z ERROR [payment-svc] DB timeout after 5000ms",
         "ERROR", "payment-svc", "DB timeout after 5000ms"),
        ("2026-10-09 03:00:01,123 WARN payment-svc: pool exhausted",
         "WARN", "payment-svc", "pool exhausted"),
        ("2026-10-09 03:00:02,456 - payment-svc - ERROR - Connection timeout",
         "ERROR", "payment-svc", "Connection timeout"),
        ("2026-10-09 03:00:03.001 ERROR [main] com.acme.payment.DbPool - Pool exhausted",
         "ERROR", "com.acme.payment.DbPool", "Pool exhausted"),
        ("ts=2026-10-09T03:00:07Z level=error service=notification-svc msg=\"failed to publish\" attempt=3",
         "ERROR", "notification-svc", "failed to publish attempt=3"),
        ("[2026-10-09T03:00:11Z] [WARN] [cache-svc] bracketed everything",
         "WARN", "cache-svc", "bracketed everything"),
        ("Oct  9 03:00:05 host01 nginx[1234]: upstream timed out",
         "INFO", "nginx", "upstream timed out"),
        ("api-gateway  | 2026-10-09T03:00:04Z error 502 Bad Gateway",
         "ERROR", "api-gateway", "502 Bad Gateway"),
        ("2026-10-09T03:00:08Z ERROR Timeout: upstream unreachable",
         "ERROR", "unknown", "Timeout: upstream unreachable"),
        ("2026-10-09T03:00:08Z INFO [auth-svc] Error handling request",
         "INFO", "auth-svc", "Error handling request"),
    ],
)
def test_parse_line_formats(line, severity, service, message):
    df = parse_text(line).df
    assert len(df) == 1
    row = df.iloc[0]
    assert row["severity"] == severity
    assert row["service"] == service
    assert row["message"] == message


def test_timezone_is_normalised_to_utc():
    df = parse_text("2026-10-09T03:00:03+05:30 [api-gateway] INFO hello").df
    assert df.iloc[0]["timestamp"] == pd.Timestamp("2026-10-08 21:30:03")


def test_garbage_is_skipped_and_stack_traces_attached():
    text = "\n".join([
        "2026-10-09T03:00:01Z ERROR [svc] boom",
        "java.lang.RuntimeException: boom",
        "    at com.acme.Foo.bar(Foo.java:42)",
        "===== banner without timestamp =====",
        "",
        "2026-10-09T03:00:02Z INFO [svc] fine",
    ])
    result = parse_text(text)
    assert result.stats.total_lines == 6
    assert result.stats.parsed == 2
    assert result.stats.continuation == 2
    assert result.stats.skipped == 1
    assert result.stats.blank == 1
    assert "Foo.java:42" in result.df.iloc[0]["raw"]


def test_empty_input_does_not_crash():
    result = parse_text("")
    assert result.df.empty
    assert result.stats.total_lines == 0


# --------------------------------------------------------------------------- #
# cluster
# --------------------------------------------------------------------------- #

def test_normalise_replaces_variable_parts():
    msg = ("id 550e8400-e29b-41d4-a716-446655440000 from 10.0.3.17:5432 took 5000ms "
           "at /var/log/app.log code 0x1F order=98765 attempt 2/3")
    out = normalise_message(msg)
    assert out == "id <UUID> from <IP> took <DUR> at <PATH> code <HEX> order=<NUM> attempt 2/3"


def test_drain_learns_wildcards_for_leftover_variables():
    miner = DrainMiner(sim_threshold=0.5)
    miner.add("Processed payment txn_abc for merchant m1 in <DUR>")
    tpl = miner.add("Processed payment txn_xyz for merchant m2 in <DUR>")
    assert tpl.text == "Processed payment <*> for merchant <*> in <DUR>"
    assert len(miner.templates) == 1


@pytest.mark.parametrize("method", ["drain", "tfidf"])
def test_cluster_messages_groups_families(method):
    msgs = ([f"Database connection timeout after {5000 + i}ms (host=10.0.3.{i}:5432)" for i in range(50)]
            + [f"Upstream timeout calling payment-svc (order={100000 + i}) after 10000ms" for i in range(30)]
            + ["Circuit breaker OPEN for db-primary"] * 5)
    result = cluster_messages(msgs, method=method, similarity=0.5)
    assert len(result.templates) == 3
    assert len(result.labels) == len(msgs)
    # clusters are renumbered by size: 0 = largest
    assert (result.labels == 0).sum() == 50


def test_cluster_edge_cases():
    assert cluster_messages([], method="drain").templates == {}
    assert cluster_messages(["only one"], method="tfidf").templates == {0: "only one"}


# --------------------------------------------------------------------------- #
# rank + end-to-end on the generated sample
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def sample_df():
    lines = gen.generate(6000, 42, datetime(2026, 10, 9, 2, 30), 60, 22)
    assert len(lines) == 6000
    df = parse_text("\n".join(lines)).df
    cand = df[df["sev_rank"] >= 3].copy()  # WARN and above
    result = cluster_messages(cand["message"], method="drain", similarity=0.5)
    cand["cluster_id"] = result.labels
    return cand, result.templates


def test_end_to_end_finds_root_cause(sample_df):
    cand, templates = sample_df
    ranked = rank_incidents(cand, templates, RankConfig())
    inc = ranked.incidents

    assert not ranked.fallback_mode
    trigger = inc[inc["role"] == "trigger"]
    assert len(trigger) == 1
    trigger = trigger.iloc[0]
    assert trigger["services"] == ["payment-svc"]
    assert "Database connection timeout" in trigger["template"]
    assert trigger["first_seen"].floor("min") == pd.Timestamp("2026-10-09 02:52:00")

    knock_ons = inc[inc["role"] == "knock-on"]
    assert len(knock_ons) >= 5
    assert knock_ons["lag_s"].between(0, 300).all()
    affected = set(knock_ons["services"].explode())
    assert {"checkout-svc", "api-gateway", "notification-svc", "inventory-svc"} <= affected

    background = inc[inc["role"] == "background"]
    assert len(background) >= 3                       # the steady noise families
    assert not any("Database connection timeout" in t for t in background["template"])

    # scores are 0-100 and sorted descending; ranks are 1..n
    assert inc["score"].between(0, 100).all()
    assert inc["score"].is_monotonic_decreasing
    assert list(inc["rank"]) == list(range(1, len(inc) + 1))
    # the ranked list leads with the trigger and the most severe/biggest knock-ons
    assert inc.iloc[0]["role"] == "trigger"


def test_multi_service_group_detected(sample_df):
    cand, templates = sample_df
    inc = rank_incidents(cand, templates, RankConfig()).incidents
    multi = inc[inc["template"].str.contains("Request queue saturated")]
    assert len(multi) == 1 and multi.iloc[0]["n_services"] == 2


def test_score_breakdown_adds_up(sample_df):
    cand, templates = sample_df
    cfg = RankConfig()
    inc = rank_incidents(cand, templates, cfg).incidents
    row = inc.iloc[0]
    table = score_breakdown(row, cfg.weights, n_services_total=5)
    assert list(table["Factor"])[:2] == ["Occurrences", "Severity"]
    assert abs(table["Points"].sum() - row["score"]) < 0.5


def test_fallback_when_nothing_has_an_onset():
    """A file that only covers the incident: every group is present from the start."""
    rows = []
    t0 = pd.Timestamp("2026-10-09 03:00:00")
    for i in range(120):
        rows.append({"line_no": 2 * i + 1, "timestamp": t0 + pd.Timedelta(seconds=i), "severity": "ERROR",
                     "sev_rank": 4, "service": "a", "message": "x", "raw": "x", "cluster_id": 0})
        rows.append({"line_no": 2 * i + 2, "timestamp": t0 + pd.Timedelta(seconds=i + 5), "severity": "WARN",
                     "sev_rank": 3, "service": "b", "message": "y", "raw": "y", "cluster_id": 1})
    df = pd.DataFrame(rows)
    ranked = rank_incidents(df, {0: "x", 1: "y"}, RankConfig())
    assert ranked.fallback_mode
    assert ranked.trigger_id == 0
    roles = dict(zip(ranked.incidents["cluster_id"], ranked.incidents["role"]))
    assert roles == {0: "trigger", 1: "knock-on"}


def test_rank_handles_empty_input():
    ranked = rank_incidents(pd.DataFrame(), {}, RankConfig())
    assert ranked.incidents.empty and ranked.trigger_id is None
