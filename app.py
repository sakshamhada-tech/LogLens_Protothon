"""
app.py — LogLens: turn thousands of raw log lines into a handful of ranked incidents.

Run with:  streamlit run app.py

Pipeline (all local, no external services):
    parser.parse_text        -> one row per log line (timestamp, severity, service, message)
    cluster.cluster_messages -> Drain-style templates (or TF-IDF fallback), no hand-written rules
    rank.rank_incidents      -> impact score per group + trigger / knock-on / background roles
"""

from __future__ import annotations

import base64
import html
import re
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from cluster import cluster_messages
from parser import SEVERITY_ORDER, SEVERITY_RANK, parse_text
from rank import DEFAULT_WEIGHTS, RankConfig, rank_incidents, score_breakdown

# --------------------------------------------------------------------------- #
# Page setup & constants
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="LogLens — Incident Intelligence",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

ROOT_DIR = Path(__file__).parent
SAMPLE_PATH = ROOT_DIR / "sample_logs" / "sample.log"
TEAM_IMG_DIR = ROOT_DIR / "assets" / "team"

PALETTE = [
    "#E11D48", "#EA580C", "#4F46E5", "#059669", "#7C3AED",
    "#0284C7", "#DB2777", "#0D9488", "#D97706", "#64748B",
]
OTHER_COLOUR = "#CBD5E1"
SEV_ICON = {"CRITICAL": "🟣", "ERROR": "🔴", "WARN": "🟠", "INFO": "🔵", "DEBUG": "⚪", "TRACE": "⚪"}
ROLE_BADGE = {
    "trigger": "⚡ LIKELY TRIGGER",
    "knock-on": "↳ probable knock-on",
    "independent": "◦ independent",
    "background": "〰 background noise",
}
MAX_RAW_ROWS = 500  # rows rendered per "raw lines" table (full set is downloadable)

MINI_DEMO_LOG = """2026-10-09 10:00:05 WARN [backup-job] Disk usage at 81% on /var/backups
2026-10-09 10:01:10 INFO [web] GET /home 200 in 45ms
2026-10-09 10:02:05 WARN [backup-job] Disk usage at 81% on /var/backups
2026-10-09 10:03:30 INFO [web] GET /home 200 in 51ms
2026-10-09 10:04:05 WARN [backup-job] Disk usage at 82% on /var/backups
2026-10-09 10:05:00 ERROR [database] Connection refused to replica db-2 (attempt 1)
2026-10-09 10:05:03 ERROR [database] Connection refused to replica db-2 (attempt 2)
2026-10-09 10:05:06 ERROR [database] Connection refused to replica db-2 (attempt 3)
2026-10-09 10:05:09 ERROR [database] Connection refused to replica db-2 (attempt 4)
2026-10-09 10:05:12 ERROR [database] Connection refused to replica db-2 (attempt 5)
2026-10-09 10:05:20 ERROR [web] Login failed for user 1041: database unavailable
2026-10-09 10:05:25 ERROR [web] Login failed for user 2207: database unavailable
2026-10-09 10:05:31 ERROR [database] Connection refused to replica db-2 (attempt 6)
2026-10-09 10:05:40 ERROR [web] Login failed for user 3390: database unavailable
2026-10-09 10:05:55 ERROR [web] Login failed for user 4412: database unavailable
2026-10-09 10:06:05 WARN [backup-job] Disk usage at 82% on /var/backups
2026-10-09 10:06:10 ERROR [database] Connection refused to replica db-2 (attempt 7)
2026-10-09 10:06:15 ERROR [web] Login failed for user 5110: database unavailable
2026-10-09 10:06:30 ERROR [web] Login failed for user 6002: database unavailable
2026-10-09 10:07:00 ERROR [database] Connection refused to replica db-2 (attempt 8)
2026-10-09 10:07:10 ERROR [web] Login failed for user 7781: database unavailable
2026-10-09 10:08:05 WARN [backup-job] Disk usage at 83% on /var/backups"""

TEAM_MEMBERS = [
    {
        "name": "Anurag Tiwari",
        "initials": "AT",
        "usn": "2392608004",
        "photo": "anurag.jpg",
        "role": "Team Leader · UI/UX Designer",
        "gradient": "linear-gradient(135deg, #4F46E5, #7C3AED)",
        "pill_bg": "#EEF2FF",
        "pill_fg": "#4338CA",
        "contribution": (
            "Led Team ByteForce and crafted the complete UI/UX architecture, "
            "light-mode visual system, and interactive experience for LogLens."
        ),
        "github": "https://github.com/Anurag-tiwaricodes",
        "linkedin": "https://www.linkedin.com/in/anurag-tiwari-2b1913427/",
    },
    {
        "name": "Saksham Hada",
        "initials": "SH",
        "usn": "2392608017",
        "photo": "saksham.jpg",
        "role": "Log Parsing & Data Ingestion",
        "gradient": "linear-gradient(135deg, #059669, #0D9488)",
        "pill_bg": "#ECFDF5",
        "pill_fg": "#047857",
        "contribution": (
            "Engineered the tolerant log parsing and data ingestion pipeline (parser.py), "
            "handling multi-format timestamps, severities, services, and stack-trace continuations."
        ),
        "github": "https://github.com/sakshamhada-tech",
        "linkedin": "https://www.linkedin.com/in/sakshamhada/",
    },
    {
        "name": "Shriyam Gupta",
        "initials": "SG",
        "usn": "2392608086",
        "photo": "shriyam.jpg",
        "role": "Clustering & Template Mining Engine",
        "gradient": "linear-gradient(135deg, #D97706, #EA580C)",
        "pill_bg": "#FFFBEB",
        "pill_fg": "#B45309",
        "contribution": (
            "Built the rule-free clustering and Drain template mining engine (cluster.py), "
            "including placeholder normalisation and TF-IDF agglomerative fallback."
        ),
        "github": "https://github.com/shriyamgupta14-sys",
        "linkedin": "https://www.linkedin.com/in/shriyam-gupta-957ab5356/",
    },
    {
        "name": "Ansh Raj",
        "initials": "AR",
        "usn": "2392608082",
        "photo": "ansh.jpg",
        "role": "Impact Scoring, Root-Cause Logic & Testing",
        "gradient": "linear-gradient(135deg, #0284C7, #2563EB)",
        "pill_bg": "#F0F9FF",
        "pill_fg": "#0369A1",
        "contribution": (
            "Developed the 5-factor impact scoring and trigger/knock-on root-cause logic (rank.py), "
            "plus synthetic log generation and the 23-case automated pytest suite."
        ),
        "github": "https://github.com/anshraj3060",
        "linkedin": "https://www.linkedin.com/in/ansh-raj-86a795321/",
    },
    {
        "name": "Jatin Alwani",
        "initials": "JA",
        "usn": "2392608141",
        "photo": "jatin.jpg",
        "role": "Debugging, Documentation & Product Strategy",
        "gradient": "linear-gradient(135deg, #E11D48, #DB2777)",
        "pill_bg": "#FFF1F2",
        "pill_fg": "#BE123C",
        "contribution": (
            "Led end-to-end debugging across the LogLens pipeline, authored the technical "
            "documentation (README.md), and shaped overall product strategy."
        ),
        "github": "https://github.com/jatinalwani8",
        "linkedin": "https://www.linkedin.com/in/jatin-alwani-0b3489420/",
    },
    {
        "name": "Rohitash Jangir",
        "initials": "RJ",
        "usn": "2392608048",
        "photo": "rohitash.jpg",
        "role": "Pitch Deck & Presentation",
        "gradient": "linear-gradient(135deg, #7C3AED, #C026D3)",
        "pill_bg": "#F5F3FF",
        "pill_fg": "#6D28D9",
        "contribution": (
            "Created and structured the LogLens Pitch Deck (PPT/PDF), "
            "translating the technical pipeline into a clear 3 a.m. incident story."
        ),
        "github": "https://github.com/rohitjangir2310",
        "linkedin": "https://www.linkedin.com/in/rohit-jangir-6926743b8/",
    },
]

LOGO_SVG = """<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" width="38" height="38" style="flex-shrink:0;filter:drop-shadow(0 2px 6px rgba(79,70,229,0.22));">
  <defs>
    <linearGradient id="llGrad" x1="2" y1="2" x2="38" y2="38" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#4F46E5"/>
      <stop offset="55%" stop-color="#6366F1"/>
      <stop offset="100%" stop-color="#0EA5E9"/>
    </linearGradient>
    <linearGradient id="llInner" x1="10" y1="10" x2="28" y2="28" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.98"/>
      <stop offset="100%" stop-color="#E0E7FF" stop-opacity="0.92"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="36" height="36" rx="11" fill="url(#llGrad)"/>
  <circle cx="18.5" cy="18.5" r="8.5" stroke="url(#llInner)" stroke-width="2.4" fill="rgba(255,255,255,0.10)"/>
  <rect x="13.5" y="18.5" width="2.2" height="4.2" rx="1.1" fill="#FFFFFF"/>
  <rect x="17.4" y="14.2" width="2.2" height="8.5" rx="1.1" fill="#FFFFFF"/>
  <rect x="21.3" y="16.4" width="2.2" height="6.3" rx="1.1" fill="#BAE6FD"/>
  <path d="M25.2 25.2L30.5 30.5" stroke="#FFFFFF" stroke-width="2.8" stroke-linecap="round"/>
  <circle cx="29.5" cy="10.5" r="2.1" fill="#38BDF8"/>
</svg>"""


# --------------------------------------------------------------------------- #
# Core Pipeline Helpers (UNTOUCHED LOGIC)
# --------------------------------------------------------------------------- #

def load_sample_text() -> str:
    """Read the bundled demo log, regenerating it if it is missing."""
    if not SAMPLE_PATH.exists():
        from datetime import datetime
        import generate_sample_log as gen
        lines = gen.generate(10000, 42, datetime(2026, 10, 9, 2, 30), 60, 22)
        SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SAMPLE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return SAMPLE_PATH.read_text(encoding="utf-8", errors="replace")


@st.cache_data(show_spinner=False)
def run_pipeline(text: str, min_sev_rank: int, method: str, similarity: float):
    """Parse + cluster. Cached on the inputs so widget changes are instant."""
    t_start = time.perf_counter()
    parsed = parse_text(text)
    df = parsed.df
    cand = df[df["sev_rank"] >= min_sev_rank].copy()
    if not cand.empty:
        result = cluster_messages(cand["message"], method=method, similarity=similarity)
        cand["cluster_id"] = result.labels
        templates, n_unique = result.templates, result.n_unique
    else:
        cand["cluster_id"] = pd.Series(dtype=int)
        templates, n_unique = {}, 0
    stats = {
        "total_lines": parsed.stats.total_lines, "parsed": parsed.stats.parsed,
        "continuation": parsed.stats.continuation, "skipped": parsed.stats.skipped,
        "blank": parsed.stats.blank, "skipped_samples": parsed.stats.skipped_samples,
        "n_unique": n_unique, "seconds": time.perf_counter() - t_start,
    }
    return df, cand, templates, stats


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


def fmt_duration(seconds: float) -> str:
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def fmt_growth(row: pd.Series) -> str:
    if row["count_earlier"] == 0:
        return "new"
    return f"×{row['growth_ratio']:.1f}"


def short_label(row: pd.Series, width: int = 48) -> str:
    text = f"#{row['rank']} {row['services'][0]}: {row['template']}"
    return text if len(text) <= width else text[: width - 1] + "…"


def bucket_counts(ts: pd.Series, t0: pd.Timestamp, t1: pd.Timestamp, bucket_s: int) -> pd.DataFrame:
    """Lines per bucket over the *whole* window (zeros included)."""
    start = t0.floor(f"{bucket_s}s")
    index = pd.date_range(start, t1.floor(f"{bucket_s}s"), freq=f"{bucket_s}s")
    counts = ts.dt.floor(f"{bucket_s}s").value_counts().reindex(index, fill_value=0)
    return pd.DataFrame({"bucket": index, "lines": counts.to_numpy()})


# --------------------------------------------------------------------------- #
# UI / Visual Helpers (Light-Mode Design System)
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False)
def load_avatar_data_uri(filename: str) -> str | None:
    """Load a local team avatar image as a base64 data URI if present."""
    p = TEAM_IMG_DIR / filename
    if not p.exists():
        # Try alternate common extensions
        for ext in (".png", ".jpeg", ".webp", ".jpg"):
            alt_p = p.with_suffix(ext)
            if alt_p.exists():
                p = alt_p
                break
        else:
            return None
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def format_template_chips(template: str) -> str:
    escaped = html.escape(template)
    return re.sub(
        r"&lt;(DUR|IP|NUM|UUID|PATH|HEX|URL|EMAIL|SIZE|\*)&gt;",
        lambda m: f'<span class="ll-chip">&lt;{m.group(1)}&gt;</span>',
        escaped,
    )


def inject_custom_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');

        :root {
            --ll-bg: #FAFBFD;
            --ll-sidebar: #F3F6FA;
            --ll-card: #FFFFFF;
            --ll-border: #E2E8F0;
            --ll-ink: #0F172A;
            --ll-muted: #475569;
            --ll-brand: #4F46E5;
            --ll-trigger: #E11D48;
        }

        /* Light-mode ambient mesh background */
        .stApp {
            background-color: var(--ll-bg);
            background-image:
                radial-gradient(at 10% 0%, rgba(99, 102, 241, 0.08) 0px, transparent 42%),
                radial-gradient(at 90% 3%, rgba(14, 165, 233, 0.07) 0px, transparent 38%);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: var(--ll-ink);
        }

        /* Hide default Streamlit footer & decorative rainbow bar */
        footer, #MainMenu, [data-testid="stDecoration"] { display: none !important; }
        [data-testid="stHeader"] {
            background: rgba(250, 251, 253, 0.80) !important;
            backdrop-filter: blur(12px);
        }
        [data-testid="stSidebar"] {
            background-color: var(--ll-sidebar) !important;
            border-right: 1px solid #E2E8F0;
        }

        /* Animations */
        @keyframes llFadeUp {
            from { opacity: 0; transform: translateY(10px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes llPulse {
            0%   { box-shadow: 0 0 0 0 rgba(225, 29, 72, 0.45); }
            70%  { box-shadow: 0 0 0 8px rgba(225, 29, 72, 0); }
            100% { box-shadow: 0 0 0 0 rgba(225, 29, 72, 0); }
        }
        .ll-fade { animation: llFadeUp 0.4s cubic-bezier(0.16, 1, 0.3, 1) both; }
        .ll-pulse-dot {
            display: inline-block; width: 10px; height: 10px; border-radius: 999px;
            background: #E11D48; animation: llPulse 2s infinite; margin-right: 8px;
        }

        /* Brand Header */
        .ll-topbar {
            display: flex; align-items: center; justify-content: space-between;
            padding: 6px 0 18px 0; border-bottom: 1px solid #E2E8F0; margin-bottom: 22px;
        }
        .ll-brand-wrap { display: flex; align-items: center; gap: 12px; }
        .ll-brand-title {
            font-family: 'Plus Jakarta Sans', 'Inter', sans-serif;
            font-weight: 800; font-size: 1.35rem; letter-spacing: -0.025em; color: #0F172A;
            line-height: 1.1;
        }
        .ll-brand-title span { color: #4F46E5; }
        .ll-brand-sub { font-size: 0.74rem; color: #64748B; font-weight: 500; margin-top: 2px; }
        .ll-status-pill {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 4px 11px; border-radius: 999px;
            background: #ECFDF5; color: #047857; border: 1px solid #A7F3D0;
            font-size: 0.72rem; font-weight: 600;
        }
        .ll-status-dot { width: 7px; height: 7px; border-radius: 999px; background: #10B981; }

        /* Hero Landing */
        .ll-hero {
            background:
                radial-gradient(circle at 15% 20%, rgba(79, 70, 229, 0.08), transparent 45%),
                radial-gradient(circle at 85% 20%, rgba(14, 165, 233, 0.08), transparent 42%),
                radial-gradient(#CBD5E1 1px, transparent 1px),
                #FFFFFF;
            background-size: 100% 100%, 100% 100%, 22px 22px, auto;
            border: 1px solid #E2E8F0; border-radius: 24px;
            padding: 42px 32px; text-align: center;
            box-shadow: 0 4px 20px rgba(15, 23, 42, 0.04);
            margin-bottom: 24px;
        }
        .ll-hero-badge {
            display: inline-flex; align-items: center; gap: 8px;
            background: #EEF2FF; color: #4338CA; border: 1px solid #C7D2FE;
            padding: 5px 14px; border-radius: 999px; font-size: 0.76rem; font-weight: 600;
            margin-bottom: 16px;
        }
        .ll-hero h1 {
            font-family: 'Plus Jakarta Sans', 'Inter', sans-serif;
            font-size: clamp(1.9rem, 3.6vw, 2.85rem); font-weight: 800;
            letter-spacing: -0.03em; color: #0F172A; margin: 0 auto 12px auto; max-width: 680px;
            line-height: 1.14;
        }
        .ll-hero h1 span { color: #4F46E5; }
        .ll-hero p {
            color: #475569; font-size: 0.98rem; max-width: 580px;
            margin: 0 auto; line-height: 1.6;
        }

        /* Step & KPI Cards */
        .ll-step-card, .ll-kpi-card {
            background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 18px;
            padding: 18px; height: 100%;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
            transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
        }
        .ll-step-card:hover, .ll-kpi-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.07);
            border-color: #CBD5E1;
        }
        .ll-step-num {
            display: inline-flex; align-items: center; justify-content: center;
            width: 34px; height: 34px; border-radius: 10px;
            font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: 0.85rem;
            margin-bottom: 10px;
        }
        .ll-kpi-label { font-size: 0.72rem; font-weight: 600; color: #64748B; text-transform: uppercase; letter-spacing: 0.04em; }
        .ll-kpi-val {
            font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.45rem; font-weight: 800;
            color: #0F172A; margin: 4px 0 2px 0;
        }
        .ll-kpi-sub { font-size: 0.72rem; color: #94A3B8; }

        /* Summary Banner */
        .ll-banner {
            background: linear-gradient(135deg, #4F46E5 0%, #4F46E5 52%, #0284C7 100%);
            color: #FFFFFF; border-radius: 22px; padding: 24px 28px;
            box-shadow: 0 10px 28px rgba(79, 70, 229, 0.18);
            margin-bottom: 18px;
        }
        .ll-banner-pills { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
        .ll-banner-pill {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 3px 11px; border-radius: 999px; font-size: 0.72rem; font-weight: 600;
            background: rgba(255, 255, 255, 0.16); color: #FFFFFF;
        }
        .ll-banner-pill.green {
            background: rgba(16, 185, 129, 0.24); color: #D1FAE5; border: 1px solid rgba(110, 231, 183, 0.35);
            font-family: 'JetBrains Mono', monospace;
        }
        .ll-banner h2 {
            font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.55rem; font-weight: 800;
            margin: 0 0 6px 0; color: #FFFFFF; letter-spacing: -0.02em;
        }
        .ll-banner p { margin: 0; font-size: 0.86rem; color: #E0E7FF; }
        .ll-banner code {
            background: rgba(255,255,255,0.16); color: #FFFFFF;
            padding: 2px 7px; border-radius: 6px; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem;
        }

        /* Cascade Card */
        .ll-cascade {
            background: #FFFFFF; border: 1px solid #FECDD3; border-radius: 20px;
            padding: 20px 22px; margin: 16px 0 20px 0;
            box-shadow: 0 2px 10px rgba(225, 29, 72, 0.05);
        }
        .ll-cascade-title {
            font-size: 0.74rem; font-weight: 800; letter-spacing: 0.06em;
            text-transform: uppercase; color: #BE123C; display: flex; align-items: center;
            margin-bottom: 10px;
        }
        .ll-cascade-flow { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; }
        .ll-node-trigger {
            display: inline-flex; align-items: center; gap: 7px;
            background: #E11D48; color: #FFFFFF; padding: 6px 12px; border-radius: 12px;
            font-size: 0.78rem; font-weight: 700; box-shadow: 0 3px 10px rgba(225,29,72,0.22);
        }
        .ll-node-knock {
            display: inline-flex; align-items: center; gap: 6px;
            background: #F8FAFC; color: #334155; border: 1px solid #E2E8F0;
            padding: 5px 11px; border-radius: 11px; font-size: 0.76rem; font-weight: 600;
        }
        .ll-node-knock span { color: #4F46E5; font-family: 'JetBrains Mono', monospace; font-weight: 700; }
        .ll-arrow { color: #CBD5E1; font-weight: 700; }

        /* Template Code & Placeholder Chips */
        .ll-template-box {
            font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; color: #1E293B;
            background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px;
            padding: 10px 13px; margin: 8px 0 12px 0; line-height: 1.55; word-break: break-word;
        }
        .ll-chip {
            display: inline-block; background: #EEF2FF; color: #4338CA;
            border: 1px solid #C7D2FE; border-radius: 5px; padding: 0 5px;
            font-size: 0.76rem; font-weight: 600; margin: 0 1px;
        }

        /* Severity & Role Badges */
        .ll-badge {
            display: inline-block; padding: 2px 9px; border-radius: 7px;
            font-size: 0.72rem; font-weight: 700; margin-right: 6px;
        }
        .ll-sev-CRITICAL { background: #F5F3FF; color: #6D28D9; border: 1px solid #DDD6FE; }
        .ll-sev-ERROR    { background: #FFF1F2; color: #BE123C; border: 1px solid #FECDD3; }
        .ll-sev-WARN     { background: #FFFBEB; color: #B45309; border: 1px solid #FDE68A; }
        .ll-sev-INFO     { background: #F0F9FF; color: #0369A1; border: 1px solid #BAE6FD; }
        .ll-role-trigger { background: #E11D48; color: #FFFFFF; border-radius: 999px; }
        .ll-role-knock   { background: #EEF2FF; color: #4338CA; border: 1px solid #C7D2FE; border-radius: 999px; }
        .ll-role-bg      { background: #F1F5F9; color: #64748B; border-radius: 999px; }
        .ll-svc-tag {
            display: inline-block; background: #F1F5F9; color: #334155;
            padding: 2px 8px; border-radius: 6px; font-family: 'JetBrains Mono', monospace;
            font-size: 0.72rem; font-weight: 500; margin-right: 4px;
        }

        /* Elevated Incident Container */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #FFFFFF !important;
            border: 1px solid #E2E8F0 !important;
            border-radius: 18px !important;
            box-shadow: 0 2px 10px rgba(15, 23, 42, 0.03) !important;
            transition: transform 0.2s ease, box-shadow 0.2s ease !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.07) !important;
        }

        /* Footer */
        .ll-footer-card {
            margin-top: 40px; background: #FFFFFF; border: 1px solid #E2E8F0;
            border-radius: 24px; padding: 28px 28px 18px 28px;
            box-shadow: 0 2px 12px rgba(15, 23, 42, 0.03);
        }
        .ll-footer-col-title {
            font-size: 0.72rem; font-weight: 800; text-transform: uppercase;
            letter-spacing: 0.07em; color: #94A3B8; margin-bottom: 10px;
        }
        .ll-footer-copy {
            margin-top: 18px; padding-top: 14px; border-top: 1px solid #F1F5F9;
            display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px;
            font-size: 0.76rem; color: #64748B;
        }

        /* Spotlight Modal Card */
        .ll-spotlight {
            background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 20px;
            padding: 28px; display: flex; flex-wrap: wrap; align-items: center; gap: 24px;
            animation: llFadeUp 0.25s ease-out both;
        }
        .ll-avatar-ring {
            padding: 4px; border-radius: 999px; display: inline-flex; flex-shrink: 0;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.12);
        }
        .ll-avatar-img {
            width: 96px; height: 96px; border-radius: 999px; object-fit: cover;
            border: 3px solid #FFFFFF; background: #FFFFFF; display: block;
        }
        .ll-avatar-init {
            width: 96px; height: 96px; border-radius: 999px; border: 3px solid #FFFFFF;
            background: #FFFFFF; color: #0F172A; display: flex; align-items: center;
            justify-content: center; font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 1.7rem; font-weight: 800;
        }
        .ll-social-btn {
            display: inline-flex; align-items: center; gap: 7px;
            padding: 8px 16px; border-radius: 12px; font-size: 0.8rem; font-weight: 600;
            text-decoration: none !important; transition: transform 0.18s ease, opacity 0.18s ease;
            margin-right: 8px; margin-top: 6px;
        }
        .ll-social-btn:hover { transform: translateY(-1px); opacity: 0.92; }
        .ll-btn-gh { background: #0F172A; color: #FFFFFF !important; }
        .ll-btn-li { background: #FFFFFF; color: #0369A1 !important; border: 1px solid #BAE6FD; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_score_ring_html(score: float, colour: str) -> str:
    pct = max(0.0, min(100.0, float(score)))
    dash = 106.8
    offset = dash * (1.0 - pct / 100.0)
    return f"""
    <div style="display:flex;align-items:center;justify-content:flex-end;gap:10px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:16px;padding:8px 14px;">
      <div style="position:relative;width:46px;height:46px;display:flex;align-items:center;justify-content:center;">
        <svg width="46" height="46" viewBox="0 0 44 44">
          <circle cx="22" cy="22" r="17" fill="none" stroke="#E2E8F0" stroke-width="3.6" />
          <circle cx="22" cy="22" r="17" fill="none" stroke="{colour}" stroke-width="3.6"
                  stroke-linecap="round" stroke-dasharray="{dash}" stroke-dashoffset="{offset:.1f}"
                  transform="rotate(-90 22 22)" />
        </svg>
        <span style="position:absolute;font-family:'Plus Jakarta Sans',sans-serif;font-weight:800;font-size:0.82rem;color:#0F172A;">{score:.0f}</span>
      </div>
      <div style="line-height:1.2;">
        <div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#94A3B8;">Impact</div>
        <div style="font-size:0.74rem;font-weight:600;color:#475569;">out of 100</div>
      </div>
    </div>
    """


# --------------------------------------------------------------------------- #
# Charts (Light-Mode Styled Altair)
# --------------------------------------------------------------------------- #

def timeline_chart(cand: pd.DataFrame, inc: pd.DataFrame, colours: dict, t0, t1, bucket_s: int,
                   bucket_label: str, trigger_onset) -> alt.Chart:
    """Stacked bars: lines per bucket, coloured by incident (top groups + 'other')."""
    label_of = {int(r["cluster_id"]): short_label(r) for _, r in inc.iterrows() if int(r["cluster_id"]) in colours}
    order_of = {lab: i for i, lab in enumerate(label_of.values())}
    order_of["Other groups"] = len(order_of)

    d = cand[["timestamp", "cluster_id"]].copy()
    d["bucket"] = d["timestamp"].dt.floor(f"{bucket_s}s")
    d["incident"] = d["cluster_id"].map(label_of).fillna("Other groups")
    agg = d.groupby(["bucket", "incident"], observed=True).size().reset_index(name="lines")
    agg["order"] = agg["incident"].map(order_of)
    agg = agg.sort_values(["bucket", "order"])
    agg["y1"] = agg.groupby("bucket")["lines"].cumsum()
    agg["y0"] = agg["y1"] - agg["lines"]
    agg["bucket_end"] = agg["bucket"] + pd.Timedelta(seconds=bucket_s)

    domain = list(order_of)
    range_ = [colours.get(cid, OTHER_COLOUR) for cid, lab in label_of.items()] + [OTHER_COLOUR]
    bars = alt.Chart(agg).mark_rect(opacity=0.92, cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
        x=alt.X("bucket:T", title=None, axis=alt.Axis(format="%H:%M", labelColor="#64748B", grid=False)),
        x2="bucket_end:T",
        y=alt.Y("y0:Q", title=f"lines per {bucket_label}",
                axis=alt.Axis(labelColor="#64748B", titleColor="#475569", gridColor="#F1F5F9")),
        y2="y1:Q",
        color=alt.Color(
            "incident:N",
            scale=alt.Scale(domain=domain, range=range_),
            legend=alt.Legend(title=None, orient="bottom", columns=2, labelLimit=420, labelColor="#334155"),
        ),
        tooltip=[
            alt.Tooltip("bucket:T", title="Time", format="%H:%M:%S"),
            alt.Tooltip("incident:N", title="Group"),
            alt.Tooltip("lines:Q", title="Lines"),
        ],
    )
    layers = [bars]
    if trigger_onset is not None:
        rule_df = pd.DataFrame({"t": [trigger_onset], "label": ["⚡ likely trigger"]})
        layers.append(alt.Chart(rule_df).mark_rule(color="#E11D48", strokeDash=[6, 4], size=2).encode(x="t:T"))
        layers.append(
            alt.Chart(rule_df).mark_text(
                align="left", dx=5, dy=-2, color="#E11D48", fontSize=11, fontWeight="bold", baseline="top"
            ).encode(x="t:T", y=alt.value(0), text="label:N")
        )
    return (
        alt.layer(*layers)
        .properties(height=300, background="#FFFFFF")
        .configure_view(strokeWidth=0)
    )


def sparkline(ts: pd.Series, t0, t1, bucket_s: int, colour: str, trigger_onset) -> alt.Chart:
    """Tiny area chart of one incident's volume across the whole log window."""
    data = bucket_counts(ts, t0, t1, bucket_s)
    area = alt.Chart(data).mark_area(
        interpolate="step-after", color=colour, opacity=0.28, line={"color": colour, "strokeWidth": 1.8}
    ).encode(
        x=alt.X("bucket:T", axis=None),
        y=alt.Y("lines:Q", axis=None),
        tooltip=[alt.Tooltip("bucket:T", title="Time", format="%H:%M:%S"), alt.Tooltip("lines:Q", title="Lines")],
    )
    layers = [area]
    if trigger_onset is not None:
        layers.append(
            alt.Chart(pd.DataFrame({"t": [trigger_onset]})).mark_rule(
                color="#E11D48", strokeDash=[3, 3], opacity=0.65
            ).encode(x="t:T")
        )
    return alt.layer(*layers).properties(height=84, background="transparent").configure_view(strokeWidth=0)


# --------------------------------------------------------------------------- #
# Modals: Team ByteForce Spotlight, About Us, Contact Us
# --------------------------------------------------------------------------- #

@st.dialog("Team ByteForce", width="large")
def show_team_modal() -> None:
    st.session_state.setdefault("team_idx", 0)
    names = [m["name"].split()[0] for m in TEAM_MEMBERS]

    st.markdown(
        "<div style='margin-bottom:10px;'>"
        "<span style='background:#EEF2FF;color:#4338CA;font-size:0.72rem;font-weight:700;padding:3px 10px;border-radius:999px;'>"
        "2392608004-ByteForce</span>"
        "<p style='color:#64748B;font-size:0.84rem;margin:8px 0 0 0;'>Select a team member below to view their role, contribution, and profiles.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    selected_name = st.segmented_control(
        "Team Member",
        options=names,
        default=names[st.session_state.team_idx],
        label_visibility="collapsed",
        key="team_modal_selector",
    )
    if selected_name in names:
        st.session_state.team_idx = names.index(selected_name)

    m = TEAM_MEMBERS[st.session_state.team_idx]
    avatar_uri = load_avatar_data_uri(m["photo"])
    if avatar_uri:
        avatar_html = f'<img src="{avatar_uri}" alt="{html.escape(m["name"])}" class="ll-avatar-img" />'
    else:
        avatar_html = f'<div class="ll-avatar-init">{html.escape(m["initials"])}</div>'

    st.markdown(
        f"""
        <div class="ll-spotlight">
          <div class="ll-avatar-ring" style="background:{m['gradient']};">
            {avatar_html}
          </div>
          <div style="flex:1;min-width:220px;">
            <div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:6px;">
              <span style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.35rem;font-weight:800;color:#0F172A;">
                {html.escape(m['name'])}
              </span>
              <span style="font-family:'JetBrains Mono',monospace;font-size:0.74rem;color:#64748B;background:#FFFFFF;border:1px solid #E2E8F0;padding:2px 8px;border-radius:6px;">
                {html.escape(m['usn'])}
              </span>
            </div>
            <div style="margin-bottom:10px;">
              <span style="display:inline-block;background:{m['pill_bg']};color:{m['pill_fg']};font-size:0.76rem;font-weight:700;padding:4px 12px;border-radius:999px;">
                {html.escape(m['role'])}
              </span>
            </div>
            <p style="color:#475569;font-size:0.88rem;line-height:1.58;margin:0 0 12px 0;">
              {html.escape(m['contribution'])}
            </p>
            <div>
              <a href="{m['github']}" target="_blank" rel="noopener noreferrer" class="ll-social-btn ll-btn-gh">GitHub Profile ↗</a>
              <a href="{m['linkedin']}" target="_blank" rel="noopener noreferrer" class="ll-social-btn ll-btn-li">LinkedIn Profile ↗</a>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c_prev, c_count, c_next = st.columns([1, 2, 1])
    with c_prev:
        if st.button("← Prev", use_container_width=True, key="team_prev_btn"):
            st.session_state.team_idx = (st.session_state.team_idx - 1) % len(TEAM_MEMBERS)
            st.rerun()
    with c_count:
        st.markdown(
            f"<div style='text-align:center;color:#64748B;font-size:0.8rem;font-family:JetBrains Mono,monospace;padding-top:8px;'>"
            f"{st.session_state.team_idx + 1} / {len(TEAM_MEMBERS)}</div>",
            unsafe_allow_html=True,
        )
    with c_next:
        if st.button("Next →", use_container_width=True, key="team_next_btn"):
            st.session_state.team_idx = (st.session_state.team_idx + 1) % len(TEAM_MEMBERS)
            st.rerun()


@st.dialog("About LogLens", width="medium")
def show_about_modal() -> None:
    st.markdown(
        """
        **LogLens** eliminates the 3 a.m. log-scrolling nightmare by turning massive raw log files into a handful of ranked, explained incidents in under a second.

        * **100% Local & Offline** — runs completely on your machine with zero external API keys.
        * **Rule-Free Pattern Mining** — uses placeholder normalisation and Drain template mining (plus TF-IDF fallback) so unseen errors are grouped automatically.
        * **Transparent Impact Ranking** — scores every group 0–100 across five explainable factors with live-tunable weights and likely-trigger cascade detection.
        """
    )
    a1, a2, a3 = st.columns(3)
    a1.metric("10,000 Lines", "~0.3 s")
    a2.metric("Offline Local", "100%")
    a3.metric("Pytest Suite", "23 / 23")


@st.dialog("Contact Us", width="medium")
def show_contact_modal() -> None:
    st.caption("Have feedback, questions, or collaboration ideas for Team ByteForce?")
    with st.form("contact_us_form", clear_on_submit=True):
        name = st.text_input("Your Name", placeholder="e.g. Developer / Reviewer Name")
        msg = st.text_area("Message or Feedback", placeholder="Share your thoughts about LogLens...")
        submitted = st.form_submit_button("Send Feedback", type="primary", use_container_width=True)
        if submitted:
            st.success(f"Thanks {name or 'there'}! Your feedback has been noted for Team ByteForce.")
    st.markdown(
        "[GitHub Repository ↗](https://github.com/sakshamhada-tech/LogLens) &nbsp;·&nbsp; "
        "[Team Leader LinkedIn ↗](https://www.linkedin.com/in/anurag-tiwari-2b1913427/)"
    )


# --------------------------------------------------------------------------- #
# Incident Card
# --------------------------------------------------------------------------- #

def render_card(row: pd.Series, lines: pd.DataFrame, colour: str, weights: dict, n_services_total: int,
                t0, t1, bucket_s: int, trigger_onset, trigger_row: pd.Series | None, compact: bool = False) -> None:
    sev = row["max_severity"]
    role = row["role"]
    badge = ROLE_BADGE[role]
    if role == "knock-on" and pd.notna(row["lag_s"]):
        badge += f" (+{fmt_duration(row['lag_s'])})"

    role_cls = "ll-role-trigger" if role == "trigger" else ("ll-role-knock" if role == "knock-on" else "ll-role-bg")
    svc_tags = "".join(f'<span class="ll-svc-tag">{html.escape(s)}</span>' for s in row["services"])

    with st.container(border=True):
        st.markdown(
            f"<div style='height:4px;border-radius:4px;background:{colour};margin:-8px 0 12px 0;'></div>",
            unsafe_allow_html=True,
        )
        head_l, head_r = st.columns([4.8, 1.4])
        with head_l:
            st.markdown(
                f"<div style='display:flex;flex-wrap:wrap;align-items:center;gap:4px;'>"
                f"<span style='font-family:Plus Jakarta Sans,sans-serif;font-weight:800;font-size:0.95rem;color:#0F172A;margin-right:6px;'>#{int(row['rank'])}</span>"
                f"<span class='ll-badge ll-sev-{sev}'>{sev}</span>"
                f"{svc_tags}"
                f"<span class='ll-badge {role_cls}'>{html.escape(badge)}</span>"
                f"</div>"
                f"<div class='ll-template-box'>{format_template_chips(row['template'])}</div>",
                unsafe_allow_html=True,
            )
        with head_r:
            st.markdown(render_score_ring_html(row["score"], colour), unsafe_allow_html=True)

        m1, m2, m3, m4, m5, chart_col = st.columns([1, 1, 1.25, 1.25, 1, 3])
        m1.metric("Lines", f"{int(row['count']):,}")
        m2.metric("Services", int(row["n_services"]), help=", ".join(row["services"]))
        m3.metric("First seen", f"{row['first_seen']:%H:%M:%S}", help=f"{row['first_seen']:%Y-%m-%d %H:%M:%S}")
        m4.metric("Last seen", f"{row['last_seen']:%H:%M:%S}", help=f"{row['last_seen']:%Y-%m-%d %H:%M:%S}")
        m5.metric("Growth", fmt_growth(row), help="rate in the recent window vs. the rate before it")
        with chart_col:
            st.altair_chart(sparkline(lines["timestamp"], t0, t1, bucket_s, colour, trigger_onset), width="stretch")

        detail = row["role_detail"]
        if role == "trigger":
            st.markdown(f"⚡ **Likely trigger.** {detail} Later groups that began shortly after are marked as knock-on effects.")
        elif role == "knock-on" and trigger_row is not None:
            st.markdown(
                f"↳ **Probable knock-on effect** of #{int(trigger_row['rank'])} "
                f"({trigger_row['services'][0]}). {detail}"
            )
        else:
            st.caption(detail)

        if compact:
            st.caption(f"Sample raw line (line {row['sample_line_no']:,}):")
            st.code(row["sample_raw"], language="text", wrap_lines=True)
            return

        tab_sample, tab_score, tab_raw = st.tabs([
            "Sample Raw Line",
            "Score Breakdown",
            f"All Raw Lines ({len(lines):,})",
        ])
        with tab_sample:
            st.caption(f"Line {row['sample_line_no']:,} of the input:")
            st.code(row["sample_raw"], language="text", wrap_lines=True)
        with tab_score:
            st.dataframe(score_breakdown(row, weights, n_services_total), hide_index=True, width="stretch")
            st.caption("Points = weight × normalised factor ÷ Σweights × 100; the five rows add up to the impact score.")
        with tab_raw:
            show = lines[["line_no", "timestamp", "severity", "service", "raw"]].sort_values("timestamp")
            if len(show) > MAX_RAW_ROWS:
                st.caption(f"Showing the first {MAX_RAW_ROWS:,} of {len(show):,} lines — download for the full set.")
            st.dataframe(
                show.head(MAX_RAW_ROWS),
                hide_index=True,
                width="stretch",
                height=280,
                column_config={
                    "line_no": st.column_config.NumberColumn("line", format="%d"),
                    "timestamp": st.column_config.DatetimeColumn("time", format="HH:mm:ss.SSS"),
                },
            )
            st.download_button(
                "Download these lines (.log)",
                "\n".join(show["raw"]).encode("utf-8"),
                file_name=f"incident_{int(row['rank'])}.log",
                mime="text/plain",
                key=f"dl_{int(row['cluster_id'])}",
            )


# --------------------------------------------------------------------------- #
# Footer (4-Column Modern Light-Mode SaaS Footer)
# --------------------------------------------------------------------------- #

def render_footer() -> None:
    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
    with st.container(border=True):
        f1, f2, f3, f4 = st.columns([2.2, 1.1, 1.4, 1.6])
        with f1:
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:8px;'>"
                f"{LOGO_SVG}"
                f"<span style='font-family:Plus Jakarta Sans,sans-serif;font-weight:800;font-size:1.1rem;color:#0F172A;'>Log<span style='color:#4F46E5;'>Lens</span></span>"
                f"</div>"
                f"<p style='color:#64748B;font-size:0.8rem;line-height:1.55;margin:0 0 10px 0;'>"
                f"Turning 10,000 noisy log lines into a handful of ranked, explained incidents in under a second. Built for fast, offline root-cause analysis.</p>"
                f"<a href='https://github.com/sakshamhada-tech/LogLens' target='_blank' rel='noopener noreferrer' "
                f"style='display:inline-block;padding:5px 12px;border-radius:8px;background:#F8FAFC;border:1px solid #E2E8F0;color:#334155;font-size:0.76rem;font-weight:600;text-decoration:none;'>"
                f"GitHub Repo ↗</a>",
                unsafe_allow_html=True,
            )
        with f2:
            st.markdown("<div class='ll-footer-col-title'>Explore</div>", unsafe_allow_html=True)
            if st.button("Landing Home", use_container_width=True, key="ft_home_btn"):
                st.session_state.log_text = None
                st.session_state.log_name = None
                st.rerun()
            if st.button("10K Demo Log", use_container_width=True, key="ft_demo_btn"):
                st.session_state.log_text = load_sample_text()
                st.session_state.log_name = "sample_logs/sample.log"
                st.rerun()
            if st.button("About Us", use_container_width=True, key="ft_about_btn"):
                show_about_modal()
        with f3:
            st.markdown(
                "<div class='ll-footer-col-title'>Core Pipeline</div>"
                "<div style='font-size:0.8rem;color:#475569;line-height:1.95;'>"
                "🔵 <code>parser.py</code> · Ingestion<br/>"
                "🟣 <code>cluster.py</code> · Drain Mining<br/>"
                "🔴 <code>rank.py</code> · Impact &amp; Trigger<br/>"
                "🟢 <code>pytest</code> · 23 Passing Tests"
                "</div>",
                unsafe_allow_html=True,
            )
        with f4:
            st.markdown("<div class='ll-footer-col-title'>Contact &amp; Team</div>", unsafe_allow_html=True)
            if st.button("Meet Team ByteForce →", type="primary", use_container_width=True, key="ft_team_btn"):
                show_team_modal()
            if st.button("Contact Us", use_container_width=True, key="ft_contact_btn"):
                show_contact_modal()

        st.markdown(
            "<div class='ll-footer-copy'>"
            "<span>&copy; 2026 <strong>LogLens</strong> · Team ByteForce (<code>2392608004-ByteForce</code>). All rights reserved.</span>"
            "<span>Offline Local Engine · Zero Paid APIs</span>"
            "</div>",
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------- #
# Page: sidebar (data source + settings) and main view
# --------------------------------------------------------------------------- #

def main() -> None:  # noqa: C901 - top-to-bottom UI script
    """Render the whole page: sidebar inputs, then the analysis results."""
    inject_custom_css()
    st.session_state.setdefault("log_text", None)
    st.session_state.setdefault("log_name", None)

    with st.sidebar:
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:4px;'>"
            f"{LOGO_SVG}"
            f"<div><div style='font-family:Plus Jakarta Sans,sans-serif;font-weight:800;font-size:1.2rem;color:#0F172A;'>Log<span style='color:#4F46E5;'>Lens</span></div>"
            f"<div style='font-size:0.72rem;color:#64748B;'>Offline · Rule-Free</div></div></div>",
            unsafe_allow_html=True,
        )
        st.caption("10,000 log lines → a handful of ranked incidents.")

        st.subheader("1 · Data Source")
        if st.button(
            "📂 Load 10K sample log",
            type="primary",
            use_container_width=True,
            help="10,000 lines from 5 services: a DB outage in payment-svc cascading everywhere",
        ):
            st.session_state.log_text = load_sample_text()
            st.session_state.log_name = "sample_logs/sample.log"
            st.session_state.pop("uploaded_key", None)

        if st.button("✨ Try 22-line mini story", use_container_width=True):
            st.session_state.log_text = MINI_DEMO_LOG
            st.session_state.log_name = "mini_cascade.log"
            st.session_state.pop("uploaded_key", None)

        uploaded = st.file_uploader("Upload a .log / .txt file", type=["log", "txt", "text", "out"])
        if uploaded is not None:
            key = (uploaded.name, uploaded.size)
            if st.session_state.get("uploaded_key") != key:
                st.session_state.log_text = uploaded.getvalue().decode("utf-8", errors="replace")
                st.session_state.log_name = uploaded.name
                st.session_state.uploaded_key = key

        pasted = st.text_area("…or paste log lines", height=110, placeholder="2026-10-09T03:00:01Z ERROR [payment-svc] ...")
        if st.button("Analyse pasted text", disabled=not pasted.strip(), use_container_width=True):
            st.session_state.log_text = pasted
            st.session_state.log_name = "pasted text"

        st.subheader("2 · Analysis Controls")
        min_sev = st.selectbox(
            "Minimum severity to analyse",
            ["WARN", "ERROR", "INFO", "DEBUG"],
            index=0,
            help="Lines below this level are counted but not grouped into incidents.",
        )
        method_label = st.radio(
            "Grouping method",
            ["Drain template mining", "TF-IDF + agglomerative"],
            index=0,
            help="Drain learns templates token-by-token (fast, default). "
                 "TF-IDF clusters on token overlap — a fallback for free-form messages.",
        )
        method = "drain" if method_label.startswith("Drain") else "tfidf"
        similarity = st.slider(
            "Similarity threshold", 0.3, 0.9, 0.5, 0.05,
            help="Higher = stricter grouping (more, smaller incidents).",
        )
        knock_on_min = st.slider(
            "Knock-on window (minutes)", 1, 30, 5,
            help="Groups that start within this long after the trigger are marked as knock-on effects.",
        )
        max_cards = st.number_input("Incident cards to show", 3, 50, 10)
        with st.expander("Score weights"):
            weights = {
                k: st.slider(k.replace("_", " ").title(), 0.0, 1.0, float(v), 0.05)
                for k, v in DEFAULT_WEIGHTS.items()
            }
        show_background = st.checkbox("Show background-noise groups", value=True)

    # --- Top Brand Header -------------------------------------------------------
    h_left, h_right = st.columns([4, 1.3])
    with h_left:
        st.markdown(
            f"<div class='ll-brand-wrap'>"
            f"{LOGO_SVG}"
            f"<div><div class='ll-brand-title'>Log<span>Lens</span> "
            f"<span class='ll-status-pill' style='margin-left:8px;vertical-align:middle;'><span class='ll-status-dot'></span>Local Engine</span></div>"
            f"<div class='ll-brand-sub'>Incident Intelligence · Offline, Rule-Free Log Analysis</div></div></div>",
            unsafe_allow_html=True,
        )
    with h_right:
        if st.button("👥 Team ByteForce", use_container_width=True, key="hdr_team_btn"):
            show_team_modal()
    st.markdown("<div style='border-bottom:1px solid #E2E8F0;margin:8px 0 22px 0;'></div>", unsafe_allow_html=True)

    # --- Hero Landing State (when no log is loaded yet) -------------------------
    text = st.session_state.log_text
    if not text:
        st.markdown(
            """
            <div class="ll-hero ll-fade">
              <div class="ll-hero-badge">● Offline · Rule-Free · 10,000 Lines in ~0.3 s</div>
              <h1>Find the signal in <span>10,000 log lines</span> at 3 a.m.</h1>
              <p>
                LogLens collapses noisy raw logs into a handful of ranked incidents, pinpoints the likely
                root-cause trigger, and traces cascading knock-on failures — completely locally.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        cta_sp1, cta_1, cta_2, cta_sp2 = st.columns([1.2, 2, 2, 1.2])
        with cta_1:
            if st.button("▶ Load 10,000-Line Demo Log", type="primary", use_container_width=True, key="hero_demo_btn"):
                st.session_state.log_text = load_sample_text()
                st.session_state.log_name = "sample_logs/sample.log"
                st.rerun()
        with cta_2:
            if st.button("⚡ Try 22-Line Mini Cascade", use_container_width=True, key="hero_mini_btn"):
                st.session_state.log_text = MINI_DEMO_LOG
                st.session_state.log_name = "mini_cascade.log"
                st.rerun()

        st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
        steps = [
            ("01", "#E0F2FE", "#0369A1", "Tolerant Ingest",
             "Extracts timestamps, severities & services across ISO, syslog, and Apache layouts without crashing on malformed lines."),
            ("02", "#EEF2FF", "#4338CA", "Rule-Free Grouping",
             "Masks IDs, IPs, durations & UUIDs, then runs Drain template mining to collapse thousands of lines into clean families."),
            ("03", "#FEF3C7", "#B45309", "Transparent Ranking",
             "Scores every group 0–100 across 5 explainable factors with live-tunable weights and per-card point breakdowns."),
            ("04", "#FFE4E6", "#BE123C", "Trigger & Cascade",
             "Flags the earliest sharp onset as the likely trigger and links downstream services as timed knock-on effects."),
        ]
        cols = st.columns(4)
        for col, (num, bg, fg, title, desc) in zip(cols, steps):
            col.markdown(
                f"<div class='ll-step-card ll-fade'>"
                f"<div class='ll-step-num' style='background:{bg};color:{fg};'>{num}</div>"
                f"<div style='font-family:Plus Jakarta Sans,sans-serif;font-weight:700;font-size:0.92rem;color:#0F172A;margin-bottom:6px;'>{title}</div>"
                f"<div style='font-size:0.78rem;color:#475569;line-height:1.55;'>{desc}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        render_footer()
        st.stop()

    # --- Run Core Pipeline ------------------------------------------------------
    min_rank = SEVERITY_RANK[min_sev]
    with st.spinner("Parsing and grouping logs…"):
        df, cand, templates, stats = run_pipeline(text, min_rank, method, similarity)

    if df.empty:
        st.error(
            "No lines with a recognisable timestamp were found. LogLens needs a timestamp per line "
            "(e.g. `2026-10-09T03:00:01Z`, `2026-10-09 03:00:01,123`, `Oct  9 03:00:01`)."
        )
        if stats["skipped_samples"]:
            st.code("\n".join(f"{n}: {s}" for n, s in stats["skipped_samples"]), language="text")
        render_footer()
        st.stop()

    if cand.empty:
        st.warning(
            f"Parsed {stats['parsed']:,} lines but none at **{min_sev}** or above. "
            "Lower the minimum severity in the sidebar."
        )
        render_footer()
        st.stop()

    cfg = RankConfig(weights=weights, knock_on_window_s=knock_on_min * 60)
    ranked = rank_incidents(cand, templates, cfg)
    inc = ranked.incidents
    t0, t1 = df["timestamp"].min(), df["timestamp"].max()
    span_s = max((t1 - t0).total_seconds(), 0.0)
    bucket_s, bucket_label = choose_bucket(span_s)

    incidents = inc[inc["role"] != "background"]
    background = inc[inc["role"] == "background"]
    trigger_row = inc[inc["cluster_id"] == ranked.trigger_id].iloc[0] if ranked.trigger_id is not None else None
    trigger_onset = trigger_row["onset"] if trigger_row is not None else None
    colours = {int(cid): PALETTE[i % len(PALETTE)] for i, cid in enumerate(inc["cluster_id"].head(len(PALETTE)))}
    n_services_total = int(cand["service"].nunique())

    # --- Summary Hero Banner ----------------------------------------------------
    noise_pct = (1.0 - (len(incidents) / max(stats["total_lines"], 1))) * 100.0
    extra = f" (+{plural(len(background), 'background noise group')})" if len(background) else ""
    st.markdown(
        f"""
        <div class="ll-banner ll-fade">
          <div class="ll-banner-pills">
            <span class="ll-banner-pill">✓ Analysis Complete · {stats['seconds']:.2f} s</span>
            <span class="ll-banner-pill green">{noise_pct:.2f}% noise reduced</span>
          </div>
          <h2>{plural(stats['total_lines'], 'line')} → {plural(len(incidents), 'incident')}<span style="font-weight:400;opacity:0.85;font-size:1rem;">{extra}</span></h2>
          <p><code>{html.escape(str(st.session_state.log_name))}</code> · {plural(len(cand), 'line')} at {min_sev}+ collapsed from {plural(stats['n_unique'], 'distinct message')} into {plural(len(inc), 'group')}.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Animated Bento KPI Strip -----------------------------------------------
    kpi_items = [
        ("Lines in file", f"{stats['total_lines']:,}", "raw input"),
        ("Parsed", f"{stats['parsed']:,}", f"+{stats['continuation']:,} stack lines"),
        ("Skipped", f"{stats['skipped']:,}", "no timestamp"),
        (f"{min_sev}+ lines", f"{len(cand):,}", f"{stats['n_unique']:,} distinct"),
        ("Services", f"{df['service'].nunique()}", "detected"),
        ("Time span", fmt_duration(span_s), f"{t0:%H:%M:%S} → {t1:%H:%M:%S}"),
    ]
    k_cols = st.columns(6)
    for col, (lbl, val, sub) in zip(k_cols, kpi_items):
        col.markdown(
            f"<div class='ll-kpi-card ll-fade'>"
            f"<div class='ll-kpi-label'>{lbl}</div>"
            f"<div class='ll-kpi-val'>{val}</div>"
            f"<div class='ll-kpi-sub'>{sub}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # --- Root-Cause Cascade Story Strip -----------------------------------------
    if trigger_row is not None:
        knock_ons = incidents[incidents["role"] == "knock-on"].sort_values("lag_s")
        flow_chips = [
            f"<span class='ll-node-trigger'>⚡ {html.escape(trigger_row['services'][0])} "
            f"<span style='opacity:0.85;font-family:JetBrains Mono,monospace;font-size:0.72rem;'>{trigger_row['first_seen']:%H:%M:%S}</span></span>"
        ]
        for _, kr in knock_ons.head(8).iterrows():
            lag_txt = f"+{fmt_duration(kr['lag_s'])}" if pd.notna(kr["lag_s"]) else ""
            flow_chips.append("<span class='ll-arrow'>→</span>")
            flow_chips.append(
                f"<span class='ll-node-knock'><span>{lag_txt}</span> {html.escape(kr['services'][0])}</span>"
            )
        st.markdown(
            f"""
            <div class="ll-cascade ll-fade">
              <div class="ll-cascade-title"><span class="ll-pulse-dot"></span>Likely Root-Cause Trigger &amp; Cascade</div>
              <div style="font-size:0.88rem;color:#1E293B;line-height:1.55;">
                <strong style="color:#BE123C;">{html.escape(', '.join(trigger_row['services']))}</strong> started failing first at
                <code>{trigger_row['first_seen']:%H:%M:%S}</code> with
                <code>{html.escape(trigger_row['template'])}</code> —
                followed by <strong>{len(knock_ons)}</strong> probable knock-on group{'s' if len(knock_ons) != 1 else ''} within {knock_on_min} min.
              </div>
              <div class="ll-cascade-flow">{''.join(flow_chips)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    for note in ranked.notes:
        st.caption(f"ℹ️ {note}")

    # --- Overall Timeline -------------------------------------------------------
    st.subheader(f"Incident Volume Timeline — {min_sev}+ lines per {bucket_label}")
    st.altair_chart(timeline_chart(cand, inc, colours, t0, t1, bucket_s, bucket_label, trigger_onset), width="stretch")

    # --- Interactive Incident Explorer Bar (UI-Only Filtering on `inc`) ---------
    st.subheader(f"Ranked Incidents ({len(incidents)})")
    all_view_df = inc if show_background else incidents

    f_col1, f_col2, f_col3 = st.columns([2.2, 1.5, 1.3])
    with f_col1:
        role_options = ["All", "⚡ Trigger", "↳ Knock-on", "◦ Independent"] + (["〰 Background"] if show_background else [])
        selected_role = st.pills("Filter by role", role_options, default="All", key="ui_role_filter")
    with f_col2:
        search_q = st.text_input("Search templates", placeholder="Filter by keyword or service…", key="ui_search")
    with f_col3:
        sort_by = st.selectbox("Sort by", ["Impact Score", "Earliest First", "Most Lines", "Fastest Growth"], key="ui_sort")

    all_services = sorted({s for svcs in all_view_df["services"] for s in svcs})
    selected_services = st.multiselect("Filter by service", all_services, default=[], placeholder="All services")

    filtered = all_view_df.copy()
    role_map = {"⚡ Trigger": "trigger", "↳ Knock-on": "knock-on", "◦ Independent": "independent", "〰 Background": "background"}
    if selected_role and selected_role != "All":
        filtered = filtered[filtered["role"] == role_map[selected_role]]
    if selected_services:
        filtered = filtered[filtered["services"].apply(lambda svcs: any(s in selected_services for s in svcs))]
    if search_q.strip():
        q = search_q.strip().lower()
        filtered = filtered[
            filtered["template"].str.lower().str.contains(q, regex=False)
            | filtered["services"].apply(lambda svcs: any(q in s.lower() for s in svcs))
        ]

    if sort_by == "Earliest First":
        filtered = filtered.sort_values("first_seen", ascending=True)
    elif sort_by == "Most Lines":
        filtered = filtered.sort_values("count", ascending=False)
    elif sort_by == "Fastest Growth":
        filtered = filtered.sort_values("growth_ratio", ascending=False)
    else:
        filtered = filtered.sort_values("score", ascending=False)

    st.caption(f"Showing {min(len(filtered), int(max_cards))} of {len(filtered)} matching groups.")
    if filtered.empty:
        st.info("No incident groups match your current filter selection.")
    else:
        for _, row in filtered.head(int(max_cards)).iterrows():
            lines = cand[cand["cluster_id"] == row["cluster_id"]]
            render_card(
                row, lines, colours.get(int(row["cluster_id"]), OTHER_COLOUR),
                weights, n_services_total, t0, t1, bucket_s, trigger_onset, trigger_row,
                compact=(row["role"] == "background"),
            )

    if len(filtered) > max_cards:
        st.info(f"Showing the top {int(max_cards)} of {len(filtered)} matching groups — raise the limit in the sidebar or use the table below.")

    # --- Tables & Downloads -----------------------------------------------------
    with st.expander("All groups as a table / CSV export"):
        table = inc[[
            "rank", "score", "role", "max_severity", "count", "n_services",
            "services", "first_seen", "last_seen", "growth_ratio", "template",
        ]].copy()
        table["services"] = table["services"].apply(", ".join)
        table["score"] = table["score"].round(1)
        table["growth_ratio"] = table["growth_ratio"].round(2)
        st.dataframe(table, hide_index=True, width="stretch")
        st.download_button(
            "Download incidents (.csv)",
            table.to_csv(index=False).encode("utf-8"),
            file_name="loglens_incidents.csv",
            mime="text/csv",
        )

    with st.expander("Parsing details"):
        c1, c2 = st.columns(2)
        c1.markdown("**Lines by severity**")
        c1.dataframe(df["severity"].value_counts().reindex(SEVERITY_ORDER).dropna().astype(int).rename("lines"), width="stretch")
        c2.markdown("**Lines by service**")
        c2.dataframe(df["service"].value_counts().rename("lines"), width="stretch")
        if stats["skipped_samples"]:
            st.markdown(f"**Skipped lines** ({stats['skipped']:,} total, first {len(stats['skipped_samples'])} shown)")
            st.code("\n".join(f"line {n}: {s}" for n, s in stats["skipped_samples"]), language="text")

    # --- Footer -----------------------------------------------------------------
    render_footer()


if __name__ == "__main__":
    main()
