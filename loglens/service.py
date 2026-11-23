"""
service.py — orchestration + JSON serialization for the LogLens API.

Replicates the original UI's run_pipeline + ranking/summary behaviour, but
returns a plain JSON-safe dict instead of rendering widgets.

    analyze(text, min_severity, method, similarity, knock_on_minutes, weights)
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

from .cluster import cluster_messages
from .parser import SEVERITY_ORDER, SEVERITY_RANK, parse_text
from .rank import DEFAULT_WEIGHTS, RankConfig, rank_incidents, score_breakdown

MAX_RAW_ROWS = 500  # rows returned per incident (full set is not shipped)
TIMELINE_TOP_N = 10  # incidents that get their own timeline series


# --------------------------------------------------------------------------- #
# JSON serialisation
# --------------------------------------------------------------------------- #


def _jsonable(obj: Any) -> Any:
    """Recursively convert pandas/numpy values to JSON-safe Python types.

    Timestamps -> ISO-8601 strings, numpy scalars -> Python scalars,
    NaN/NaT/inf -> None, arrays/sets -> lists. Never returns a DataFrame.
    """
    if obj is None:
        return None
    # NaT / NaN checks (must come before isinstance checks that could match)
    if isinstance(obj, pd.Timestamp) and pd.isna(obj):
        return None
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return None if (math.isnan(val) or math.isinf(val)) else val
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (set, frozenset)):
        return [_jsonable(v) for v in sorted(obj, key=str)]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return obj  # already checked for nan/inf above
    return obj


# --------------------------------------------------------------------------- #
# Helpers ported from app.py (logic unchanged)
# --------------------------------------------------------------------------- #


def choose_bucket(span_s: float) -> tuple[int, str]:
    """Pick a timeline resolution that gives a readable number of bars."""
    if span_s <= 15 * 60:
        return 10, "10 s"
    if span_s <= 3 * 3600:
        return 60, "minute"
    if span_s <= 24 * 3600:
        return 300, "5 min"
    if span_s <= 7 * 86400:
        return 3600, "hour"
    return 86400, "day"


def bucket_counts(ts: pd.Series, t0: pd.Timestamp, t1: pd.Timestamp, bucket_s: int) -> pd.DataFrame:
    """Lines per bucket over the *whole* window (zeros included)."""
    start = t0.floor(f"{bucket_s}s")
    index = pd.date_range(start, t1.floor(f"{bucket_s}s"), freq=f"{bucket_s}s")
    counts = ts.dt.floor(f"{bucket_s}s").value_counts().reindex(index, fill_value=0)
    return pd.DataFrame({"bucket": index, "lines": counts.to_numpy()})


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #


def analyze(
    text: str,
    min_severity: str = "WARN",
    method: str = "drain",
    similarity: float = 0.5,
    knock_on_minutes: int = 5,
    weights: Optional[dict] = None,
) -> dict:
    """Run the full pipeline and return a JSON-safe dict.

    Empty/edge cases return a normal dict with an ``error``/``empty_reason``
    field instead of raising.
    """
    t_start = time.perf_counter()
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    min_rank = SEVERITY_RANK.get(min_severity, SEVERITY_RANK["WARN"])

    parsed = parse_text(text or "")
    df = parsed.df
    stats = {
        "total_lines": int(parsed.stats.total_lines),
        "parsed": int(parsed.stats.parsed),
        "continuation": int(parsed.stats.continuation),
        "skipped": int(parsed.stats.skipped),
        "blank": int(parsed.stats.blank),
        "skipped_samples": [[int(n), str(s)] for n, s in parsed.stats.skipped_samples],
        "n_unique": 0,
        "seconds": 0.0,
        "candidate_count": 0,
        "n_services_total": 0,
        "services_detected_count": 0,
    }

    # --- Empty input ---------------------------------------------------------
    if not (text or "").strip():
        stats["seconds"] = time.perf_counter() - t_start
        return _jsonable({
            "error": "No log text was provided. Load the sample log, upload a file, or paste log lines.",
            "empty_reason": "empty_input",
            "stats": stats,
            "incidents": [],
            "timeline": [],
            "notes": [],
            "trigger_id": None,
            "fallback_mode": False,
            "window": None,
            "severity_counts": {},
            "service_counts": {},
        })

    # --- No parseable timestamps ---------------------------------------------
    if df.empty:
        stats["seconds"] = time.perf_counter() - t_start
        return _jsonable({
            "error": (
                "No lines with a recognisable timestamp were found. LogLens needs a timestamp per line "
                "(e.g. `2026-10-09T03:00:01Z`, `2026-10-09 03:00:01,123`, `Oct  9 03:00:01`)."
            ),
            "empty_reason": "no_timestamps",
            "stats": stats,
            "incidents": [],
            "timeline": [],
            "notes": [],
            "trigger_id": None,
            "fallback_mode": False,
            "window": None,
            "severity_counts": {},
            "service_counts": {},
        })

    # --- Filter + cluster -----------------------------------------------------
    cand = df[df["sev_rank"] >= min_rank].copy()
    stats["candidate_count"] = int(len(cand))
    stats["n_services_total"] = int(cand["service"].nunique()) if not cand.empty else 0
    stats["services_detected_count"] = int(df["service"].nunique())

    if cand.empty:
        stats["seconds"] = time.perf_counter() - t_start
        return _jsonable({
            "error": (
                f"Parsed {parsed.stats.parsed:,} lines but none at {min_severity} or above. "
                "Lower the minimum severity in the sidebar."
            ),
            "empty_reason": "no_severity_lines",
            "stats": stats,
            "incidents": [],
            "timeline": [],
            "notes": [],
            "trigger_id": None,
            "fallback_mode": False,
            "window": None,
            "severity_counts": _severity_counts(df),
            "service_counts": _service_counts(df),
        })

    result = cluster_messages(cand["message"], method=method, similarity=similarity)
    cand["cluster_id"] = result.labels
    templates = result.templates
    stats["n_unique"] = int(result.n_unique)

    # --- Rank -----------------------------------------------------------------
    cfg = RankConfig(weights=weights, knock_on_window_s=float(knock_on_minutes) * 60)
    ranked = rank_incidents(cand, templates, cfg)
    inc = ranked.incidents
    n_services_total = int(cand["service"].nunique())

    t0, t1 = df["timestamp"].min(), df["timestamp"].max()
    span_s = max(float((t1 - t0).total_seconds()), 0.0)
    bucket_s, bucket_label = choose_bucket(span_s)

    trigger_row = None
    if ranked.trigger_id is not None and not inc.empty:
        match = inc[inc["cluster_id"] == ranked.trigger_id]
        if not match.empty:
            trigger_row = match.iloc[0]
    trigger_onset = trigger_row["onset"] if trigger_row is not None else None

    stats["seconds"] = time.perf_counter() - t_start

    incidents = _build_incidents(inc, cand, weights, n_services_total, t0, t1, bucket_s)
    timeline = _build_timeline(cand, inc, t0, t1, bucket_s)

    return _jsonable({
        "error": None,
        "empty_reason": None,
        "stats": stats,
        "window": {
            "t0": t0,
            "t1": t1,
            "span_s": span_s,
            "bucket_s": int(bucket_s),
            "bucket_label": bucket_label,
        },
        "notes": list(ranked.notes),
        "trigger_id": ranked.trigger_id,
        "fallback_mode": bool(ranked.fallback_mode),
        "incidents": incidents,
        "timeline": timeline,
        "severity_counts": _severity_counts(df),
        "service_counts": _service_counts(df),
    })


def _severity_counts(df: pd.DataFrame) -> dict:
    counts = df["severity"].value_counts()
    out: dict[str, int] = {}
    for sev in SEVERITY_ORDER:
        if sev in counts.index:
            out[sev] = int(counts[sev])
    # Any unexpected levels (shouldn't happen) appended after.
    for sev, n in counts.items():
        if sev not in out:
            out[str(sev)] = int(n)
    return out


def _service_counts(df: pd.DataFrame) -> dict:
    return {str(k): int(v) for k, v in df["service"].value_counts().items()}


def _build_incidents(
    inc: pd.DataFrame,
    cand: pd.DataFrame,
    weights: dict,
    n_services_total: int,
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    bucket_s: int,
) -> list[dict]:
    out: list[dict] = []
    if inc.empty:
        return out
    # Group candidate lines by cluster once for sparkline/raw_lines.
    grouped = {int(cid): g for cid, g in cand.groupby("cluster_id")}
    for _, row in inc.iterrows():
        cid = int(row["cluster_id"])
        lines = grouped.get(cid, cand.iloc[0:0])
        # Sparkline: zero-filled buckets over the whole window.
        if not lines.empty:
            bc = bucket_counts(lines["timestamp"], t0, t1, bucket_s)
            sparkline = [
                {"t": b, "lines": int(n)} for b, n in zip(bc["bucket"], bc["lines"])
            ]
        else:
            sparkline = []
        # Raw lines: first 500 sorted by timestamp.
        if not lines.empty:
            show = lines[["line_no", "timestamp", "severity", "service", "raw"]].sort_values("timestamp")
            raw_lines = [
                {
                    "line_no": int(r["line_no"]),
                    "timestamp": r["timestamp"],
                    "severity": str(r["severity"]),
                    "service": str(r["service"]),
                    "raw": str(r["raw"]),
                }
                for _, r in show.head(MAX_RAW_ROWS).iterrows()
            ]
            raw_total = int(len(show))
        else:
            raw_lines = []
            raw_total = 0
        breakdown = score_breakdown(row, weights, n_services_total)
        out.append({
            "rank": int(row["rank"]),
            "cluster_id": cid,
            "template": str(row["template"]),
            "count": int(row["count"]),
            "max_severity": str(row["max_severity"]),
            "services": [str(s) for s in row["services"]],
            "n_services": int(row["n_services"]),
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "growth_ratio": float(row["growth_ratio"]),
            "count_earlier": int(row["count_earlier"]),
            "role": str(row["role"]),
            "role_detail": str(row["role_detail"]),
            "lag_s": float(row["lag_s"]) if pd.notna(row["lag_s"]) else None,
            "score": float(row["score"]),
            "score_breakdown": [
                {
                    "Factor": str(r["Factor"]),
                    "Evidence": str(r["Evidence"]),
                    "Normalised": float(r["Normalised"]),
                    "Weight": float(r["Weight"]),
                    "Points": float(r["Points"]),
                }
                for _, r in breakdown.iterrows()
            ],
            "sample_raw": str(row["sample_raw"]),
            "sample_line_no": int(row["sample_line_no"]),
            "onset": row["onset"],
            "sparkline": sparkline,
            "raw_lines": raw_lines,
            "raw_lines_total": raw_total,
        })
    return out


def _build_timeline(
    cand: pd.DataFrame,
    inc: pd.DataFrame,
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    bucket_s: int,
) -> list[dict]:
    """Stacked-by-incident aggregation (top 10 own series, rest 'Other groups').

    Returns one row per (bucket, series) with a non-zero line count, sorted
    by bucket then series order (top-10 by rank, Other last) so the client
    can compute y0/y1 stacking deterministically.
    """
    if cand.empty or inc.empty:
        return []
    label_of = {}
    for _, row in inc.iterrows():
        cid = int(row["cluster_id"])
        if cid in set(int(c) for c in inc["cluster_id"].head(TIMELINE_TOP_N)):
            label_of[cid] = _short_label(row)
    order_of = {cid: i for i, cid in enumerate(label_of)}
    order_of[None] = len(order_of)  # "Other groups" last
    name_of = dict(label_of)
    name_of[None] = "Other groups"

    d = cand[["timestamp", "cluster_id"]].copy()
    d["bucket"] = d["timestamp"].dt.floor(f"{bucket_s}s")
    d["series_id"] = d["cluster_id"].apply(lambda c: int(c) if int(c) in label_of else None)
    # dropna=False keeps the "Other groups" (None) series.
    agg = d.groupby(["bucket", "series_id"], observed=True, dropna=False).size().reset_index(name="lines")
    agg["order"] = agg["series_id"].map(order_of)
    agg = agg.sort_values(["bucket", "order"])
    agg["bucket_end"] = agg["bucket"] + pd.Timedelta(seconds=bucket_s)
    # Stacking coordinates (same cumsum trick as app.py's timeline_chart).
    agg["y1"] = agg.groupby("bucket")["lines"].cumsum()
    agg["y0"] = agg["y1"] - agg["lines"]
    out = []
    for _, r in agg.iterrows():
        cid = int(r["series_id"]) if pd.notna(r["series_id"]) else None
        out.append({
            "bucket": r["bucket"],
            "bucket_end": r["bucket_end"],
            "incident_cluster_id": cid,
            "incident_cluster_id_or_null": cid,
            "series": name_of.get(cid, "Other groups"),
            "lines": int(r["lines"]),
            "y0": int(r["y0"]),
            "y1": int(r["y1"]),
        })
    return out


def _short_label(row: pd.Series, width: int = 48) -> str:
    """Legend label: '#rank service: template', truncated (from app.py)."""
    text = f"#{int(row['rank'])} {row['services'][0]}: {row['template']}"
    return text if len(text) <= width else text[: width - 1] + "…"
