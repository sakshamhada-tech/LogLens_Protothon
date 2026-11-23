"""
rank.py — score incident groups by impact and explain the causal chain.

Input: a DataFrame of parsed log lines (see parser.py) with a ``cluster_id``
column (see cluster.py). Output: one row per cluster with

* **impact score** (0-100) built from five transparent factors:
  occurrence count, severity, number of services affected, growth rate
  (recent vs. earlier) and how early the group started;
* a **role** in the incident: ``trigger`` (started first), ``knock-on``
  (started shortly after the trigger), ``background`` (present since the log
  started, no clear onset) or ``independent``.

Nothing here knows about specific error texts — it only uses counts, times,
severities and service names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

#: Relative importance of each level when computing the severity factor.
SEVERITY_WEIGHT = {"TRACE": 0.05, "DEBUG": 0.10, "INFO": 0.25, "WARN": 0.50, "ERROR": 0.80, "CRITICAL": 1.00}

DEFAULT_WEIGHTS = {"count": 0.30, "severity": 0.25, "services": 0.20, "growth": 0.15, "start": 0.10}

FACTOR_LABELS = {
    "count": "Occurrences",
    "severity": "Severity",
    "services": "Services affected",
    "growth": "Growth (recent vs earlier)",
    "start": "Early start",
}

GROWTH_CAP = 20.0        # growth ratios above this all count as "exploding"
SPIKE_BUCKET_S = 60      # bucket size used for spike detection


@dataclass
class RankConfig:
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    recent_window_s: Optional[float] = None   # None -> auto: span/4 clamped to [60 s, 10 min]
    knock_on_window_s: float = 300.0          # "shortly after" the trigger
    onset_grace_s: Optional[float] = None     # None -> auto: max(60 s, 5 % of span)
    onset_sharpness: float = 3.0              # silence-before-onset / typical gap
    min_count_for_trigger: int = 3


@dataclass
class RankResult:
    incidents: pd.DataFrame
    trigger_id: Optional[int]
    t0: pd.Timestamp
    t1: pd.Timestamp
    recent_window_s: float
    onset_grace_s: float
    fallback_mode: bool   # True when no group had a clear onset
    notes: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _auto_recent_window(span_s: float) -> float:
    return float(min(600.0, max(60.0, span_s / 4.0)))


def _auto_grace(span_s: float) -> float:
    return float(max(60.0, 0.05 * span_s))


def _spike_time(seconds: np.ndarray, span_s: float, t0: pd.Timestamp) -> Optional[pd.Timestamp]:
    """First minute in which the group's rate jumps far above its typical rate."""
    n_buckets = int(span_s // SPIKE_BUCKET_S) + 1
    if n_buckets < 5:
        return None
    counts = np.bincount((seconds // SPIKE_BUCKET_S).astype(int), minlength=n_buckets)
    threshold = max(5.0, 4.0 * np.median(counts) + 2.0)
    hits = np.flatnonzero(counts >= threshold)
    if len(hits) == 0:
        return None
    return t0 + pd.Timedelta(seconds=int(hits[0]) * SPIKE_BUCKET_S)


def _fmt_lag(seconds: float) -> str:
    seconds = float(seconds)
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def _group_features(df: pd.DataFrame, templates: dict, t0: pd.Timestamp, t1: pd.Timestamp,
                    recent_window_s: float, grace_s: float, sharpness: float) -> pd.DataFrame:
    """Aggregate per-cluster statistics (counts, times, services, onset shape)."""
    span_s = max((t1 - t0).total_seconds(), 0.0)
    split = t1 - pd.Timedelta(seconds=recent_window_s)
    earlier_dur = max(span_s - recent_window_s, 1.0)
    rows = []

    for cid, g in df.groupby("cluster_id", sort=False):
        g = g.sort_values("timestamp")
        ts = g["timestamp"]
        secs = (ts - t0).dt.total_seconds().to_numpy()
        first, last = ts.iloc[0], ts.iloc[-1]
        count = len(g)

        # Severity mix
        weights = g["severity"].map(SEVERITY_WEIGHT).fillna(0.25)
        sev_counts = g["severity"].value_counts()
        max_sev = max(sev_counts.index, key=lambda s: SEVERITY_WEIGHT.get(s, 0))

        # Growth: rate in the recent window vs. rate before it
        recent = int((ts > split).sum())
        earlier = count - recent
        if span_s < 2:
            growth_ratio = 1.0
        elif earlier == 0:
            growth_ratio = GROWTH_CAP if recent else 0.0
        else:
            growth_ratio = (recent / recent_window_s) / (earlier / earlier_dur)

        # Onset shape: a long silence before the first line, then dense
        # repeats, means the group *started* inside this log window.
        gap_before = secs[0]
        gaps = np.diff(secs)
        typical_gap = float(np.percentile(gaps, 90)) if len(gaps) else max(span_s - secs[0], 1.0)
        typical_gap = max(typical_gap, 1.0)
        present_from_start = gap_before < grace_s
        sharp_onset = gap_before >= grace_s and gap_before / typical_gap >= sharpness

        spike_at = _spike_time(secs, span_s, t0) if present_from_start else None
        onset = spike_at if spike_at is not None else first
        emerged = sharp_onset or (spike_at is not None and (spike_at - t0).total_seconds() >= grace_s)

        services = sorted(g["service"].unique().tolist())
        rows.append({
            "cluster_id": int(cid),
            "template": templates.get(int(cid), g["message"].iloc[0]),
            "count": count,
            "severity_counts": sev_counts.to_dict(),
            "max_severity": max_sev,
            "mean_sev_weight": float(weights.mean()),
            "max_sev_weight": float(SEVERITY_WEIGHT.get(max_sev, 0.25)),
            "services": services,
            "n_services": len(services),
            "first_seen": first,
            "last_seen": last,
            "duration_s": float((last - first).total_seconds()),
            "count_recent": recent,
            "count_earlier": earlier,
            "growth_ratio": float(growth_ratio),
            "onset": onset,
            "emerged": bool(emerged),
            "present_from_start": bool(present_from_start),
            "spike_at": spike_at,
            "sample_raw": g["raw"].iloc[0],
            "sample_line_no": int(g["line_no"].iloc[0]) if "line_no" in g else -1,
        })
    return pd.DataFrame(rows)


def _score(inc: pd.DataFrame, weights: dict, n_services_total: int, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.DataFrame:
    """Add normalised factor columns (s_*) and the final 0-100 score."""
    span_s = max((t1 - t0).total_seconds(), 1.0)
    max_count = max(int(inc["count"].max()), 1)

    inc["s_count"] = np.log1p(inc["count"]) / np.log1p(max_count)
    inc["s_severity"] = 0.5 * inc["max_sev_weight"] + 0.5 * inc["mean_sev_weight"]
    inc["s_services"] = inc["n_services"] / max(n_services_total, 1)
    inc["s_growth"] = np.log1p(inc["growth_ratio"].clip(upper=GROWTH_CAP)) / np.log1p(GROWTH_CAP)

    # Early start: groups whose onset is earlier score higher (likely causes).
    # Steady background noise that was already there when the log began has no
    # meaningful "start", so it gets a neutral 0.5 instead of a free maximum —
    # unless *nothing* emerged, in which case we fall back to raw first-seen order.
    inc["s_start"] = 1.0 - (inc["onset"] - t0).dt.total_seconds() / span_s
    if inc["emerged"].any():
        inc.loc[inc["present_from_start"] & ~inc["emerged"], "s_start"] = 0.5

    w = {k: float(weights.get(k, 0.0)) for k in DEFAULT_WEIGHTS}
    total_w = sum(w.values()) or 1.0
    inc["score"] = sum(w[k] * inc[f"s_{k}"] for k in w) / total_w * 100.0
    for k in w:  # points contributed by each factor (sums to score)
        inc[f"pts_{k}"] = w[k] * inc[f"s_{k}"] / total_w * 100.0
    return inc


# --------------------------------------------------------------------------- #
# Roles: trigger / knock-on / background / independent
# --------------------------------------------------------------------------- #


def _assign_roles(inc: pd.DataFrame, cfg: RankConfig, t0: pd.Timestamp) -> tuple[pd.DataFrame, Optional[int], bool, list]:
    notes: list[str] = []
    inc["role"] = "independent"
    inc["role_detail"] = ""
    inc["lag_s"] = np.nan
    if inc.empty:
        return inc, None, False, notes

    candidates = inc[inc["emerged"] & (inc["count"] >= cfg.min_count_for_trigger)]
    fallback = candidates.empty
    if fallback:
        # Nothing has a clear onset (e.g. the file covers only the incident):
        # fall back to the literal rule "the group that started earliest".
        candidates = inc[inc["count"] >= cfg.min_count_for_trigger]
        if candidates.empty:
            candidates = inc
        notes.append("No group shows a clear onset inside this log window, so the earliest-starting "
                     "group is treated as the likely trigger.")

    trig = candidates.sort_values(["onset", "score"], ascending=[True, False]).iloc[0]
    trigger_id = int(trig["cluster_id"])
    trig_onset = trig["onset"]
    trig_services = set(trig["services"])

    for idx, row in inc.iterrows():
        lag = (row["onset"] - trig_onset).total_seconds()
        if row["cluster_id"] == trigger_id:
            minutes_in = (trig_onset - t0).total_seconds()
            how = "Earliest group with a clear onset" if not fallback else "Earliest-starting group"
            role, detail = "trigger", f"{how} — {_fmt_lag(minutes_in)} into the log — in {', '.join(row['services'])}."
        elif 0 <= lag <= cfg.knock_on_window_s:
            other = sorted(set(row["services"]) - trig_services)
            where = f"in {', '.join(other)}" if other else f"in the same service ({', '.join(row['services'])})"
            kind = "Spiked" if row["spike_at"] is not None and row["present_from_start"] else "Started"
            role, detail = "knock-on", f"{kind} {_fmt_lag(lag)} after the trigger {where}."
        elif lag < 0 and not row["emerged"]:
            since = "the start of the log" if row["present_from_start"] else f"{row['first_seen']:%H:%M:%S}"
            role, detail = "background", f"Steady low-level noise since {since}; no clear onset, predates the trigger."
        elif lag < 0:
            role, detail = "independent", f"Started {_fmt_lag(-lag)} before the trigger (too few lines to be the trigger)."
        else:
            role, detail = "independent", f"Started {_fmt_lag(lag)} after the trigger (outside the knock-on window)."
        inc.at[idx, "role"] = role
        inc.at[idx, "role_detail"] = detail
        inc.at[idx, "lag_s"] = lag
    return inc, trigger_id, fallback, notes


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def rank_incidents(df: pd.DataFrame, templates: dict, cfg: Optional[RankConfig] = None) -> RankResult:
    """Score and label every cluster in ``df`` (needs a ``cluster_id`` column)."""
    cfg = cfg or RankConfig()
    if df.empty:
        now = pd.Timestamp.now()
        return RankResult(pd.DataFrame(), None, now, now, 0.0, 0.0, False, ["No lines to rank."])

    t0, t1 = df["timestamp"].min(), df["timestamp"].max()
    span_s = (t1 - t0).total_seconds()
    recent_window_s = cfg.recent_window_s or _auto_recent_window(span_s)
    recent_window_s = min(recent_window_s, max(span_s / 2.0, 1.0))
    grace_s = cfg.onset_grace_s or _auto_grace(span_s)

    inc = _group_features(df, templates, t0, t1, recent_window_s, grace_s, cfg.onset_sharpness)
    inc = _score(inc, cfg.weights, int(df["service"].nunique()), t0, t1)
    inc, trigger_id, fallback, notes = _assign_roles(inc, cfg, t0)

    inc = inc.sort_values(["score", "count"], ascending=[False, False]).reset_index(drop=True)
    inc.insert(0, "rank", np.arange(1, len(inc) + 1))
    return RankResult(inc, trigger_id, t0, t1, recent_window_s, grace_s, fallback, notes)


def score_breakdown(row: pd.Series, weights: Optional[dict] = None, n_services_total: Optional[int] = None) -> pd.DataFrame:
    """Human-readable table explaining one incident's score."""
    weights = weights or DEFAULT_WEIGHTS
    if row["growth_ratio"] >= GROWTH_CAP:
        growth_txt = "new / exploding" if row["count_earlier"] == 0 else f"×{row['growth_ratio']:.0f}+"
    else:
        growth_txt = f"×{row['growth_ratio']:.2f}"
    evidence = {
        "count": f"{row['count']:,} lines",
        "severity": ", ".join(f"{k} ×{v}" for k, v in sorted(row["severity_counts"].items(),
                                                             key=lambda kv: -SEVERITY_WEIGHT.get(kv[0], 0))),
        "services": f"{row['n_services']} of {n_services_total}" if n_services_total else str(row["n_services"]),
        "growth": f"{growth_txt} ({row['count_recent']} recent vs {row['count_earlier']} earlier)",
        "start": f"first seen {row['first_seen']:%H:%M:%S}",
    }
    return pd.DataFrame({
        "Factor": [FACTOR_LABELS[k] for k in DEFAULT_WEIGHTS],
        "Evidence": [evidence[k] for k in DEFAULT_WEIGHTS],
        "Normalised": [round(float(row[f"s_{k}"]), 2) for k in DEFAULT_WEIGHTS],
        "Weight": [float(weights.get(k, 0.0)) for k in DEFAULT_WEIGHTS],
        "Points": [round(float(row[f"pts_{k}"]), 1) for k in DEFAULT_WEIGHTS],
    })
