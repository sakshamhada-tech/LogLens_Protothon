"""
app.py — LogLens: turn thousands of raw log lines into a handful of ranked incidents.

Run with:  streamlit run app.py

Pipeline (all local, no external services):
    parser.parse_text      -> one row per log line (timestamp, severity, service, message)
    cluster.cluster_messages -> Drain-style templates (or TF-IDF fallback), no hand-written rules
    rank.rank_incidents    -> impact score per group + trigger / knock-on / background roles
"""

from __future__ import annotations

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

st.set_page_config(page_title="LogLens", page_icon="🔎", layout="wide")

SAMPLE_PATH = Path(__file__).parent / "sample_logs" / "sample.log"
PALETTE = ["#d62728", "#ff7f0e", "#1f77b4", "#2ca02c", "#9467bd", "#8c564b",
           "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"]
OTHER_COLOUR = "#c7c7c7"
SEV_ICON = {"CRITICAL": "🟣", "ERROR": "🔴", "WARN": "🟠", "INFO": "🔵", "DEBUG": "⚪", "TRACE": "⚪"}
ROLE_BADGE = {
    "trigger": "⚡ LIKELY TRIGGER",
    "knock-on": "↳ probable knock-on",
    "independent": "◦ independent",
    "background": "〰 background noise",
}
MAX_RAW_ROWS = 500  # rows rendered per "raw lines" table (full set is downloadable)


# --------------------------------------------------------------------------- #
# Helpers
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
# Charts (Altair ships with Streamlit)
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
    # explicit stacking (robust for temporal x): y0/y1 per bucket
    agg["y1"] = agg.groupby("bucket")["lines"].cumsum()
    agg["y0"] = agg["y1"] - agg["lines"]
    agg["bucket_end"] = agg["bucket"] + pd.Timedelta(seconds=bucket_s)

    domain = list(order_of)
    range_ = [colours.get(cid, OTHER_COLOUR) for cid, lab in label_of.items()] + [OTHER_COLOUR]
    bars = alt.Chart(agg).mark_rect(opacity=0.9).encode(
        x=alt.X("bucket:T", title=None, axis=alt.Axis(format="%H:%M")),
        x2="bucket_end:T",
        y=alt.Y("y0:Q", title=f"lines per {bucket_label}"),
        y2="y1:Q",
        color=alt.Color("incident:N", scale=alt.Scale(domain=domain, range=range_),
                        legend=alt.Legend(title=None, orient="bottom", columns=2, labelLimit=420)),
        tooltip=[alt.Tooltip("bucket:T", title="time", format="%H:%M:%S"),
                 alt.Tooltip("incident:N", title="group"), alt.Tooltip("lines:Q", title="lines")],
    )
    layers = [bars]
    if trigger_onset is not None:
        rule_df = pd.DataFrame({"t": [trigger_onset], "label": ["likely trigger"]})
        layers.append(alt.Chart(rule_df).mark_rule(color="#d62728", strokeDash=[6, 4], size=2).encode(x="t:T"))
        layers.append(alt.Chart(rule_df).mark_text(align="left", dx=4, dy=-4, color="#d62728", fontSize=11,
                                                   baseline="top").encode(x="t:T", y=alt.value(0), text="label:N"))
    return alt.layer(*layers).properties(height=300)


def sparkline(ts: pd.Series, t0, t1, bucket_s: int, colour: str, trigger_onset) -> alt.Chart:
    """Tiny area chart of one incident's volume across the whole log window."""
    data = bucket_counts(ts, t0, t1, bucket_s)
    area = alt.Chart(data).mark_area(interpolate="step-after", color=colour, opacity=0.75,
                                     line={"color": colour}).encode(
        x=alt.X("bucket:T", axis=None),
        y=alt.Y("lines:Q", axis=None),
        tooltip=[alt.Tooltip("bucket:T", title="time", format="%H:%M:%S"), alt.Tooltip("lines:Q")],
    )
    layers = [area]
    if trigger_onset is not None:
        layers.append(alt.Chart(pd.DataFrame({"t": [trigger_onset]})).mark_rule(
            color="#d62728", strokeDash=[3, 3], opacity=0.6).encode(x="t:T"))
    return alt.layer(*layers).properties(height=90).configure_view(strokeWidth=0)


# --------------------------------------------------------------------------- #
# Incident card
# --------------------------------------------------------------------------- #

def render_card(row: pd.Series, lines: pd.DataFrame, colour: str, weights: dict, n_services_total: int,
                t0, t1, bucket_s: int, trigger_onset, trigger_row: pd.Series | None, compact: bool = False) -> None:
    sev = row["max_severity"]
    role = row["role"]
    badge = ROLE_BADGE[role]
    if role == "knock-on" and pd.notna(row["lag_s"]):
        badge += f" (+{fmt_duration(row['lag_s'])})"

    with st.container(border=True):
        head_l, head_r = st.columns([5, 1.2])
        with head_l:
            st.markdown(
                f"**#{int(row['rank'])}** &nbsp; {SEV_ICON.get(sev, '⚪')} **{sev}** &nbsp;·&nbsp; "
                f"{', '.join(row['services'])} &nbsp;·&nbsp; "
                f"<span style='color:{'#d62728' if role == 'trigger' else '#555'};font-weight:600'>{badge}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(f"`{row['template']}`")
        with head_r:
            st.metric("Impact score", f"{row['score']:.0f} / 100")

        m1, m2, m3, m4, m5, chart_col = st.columns([1, 1, 1.3, 1.3, 1, 3])
        m1.metric("Lines", f"{int(row['count']):,}")
        m2.metric("Services", int(row["n_services"]), help=", ".join(row["services"]))
        m3.metric("First seen", f"{row['first_seen']:%H:%M:%S}", help=f"{row['first_seen']:%Y-%m-%d %H:%M:%S}")
        m4.metric("Last seen", f"{row['last_seen']:%H:%M:%S}", help=f"{row['last_seen']:%Y-%m-%d %H:%M:%S}")
        m5.metric("Growth", fmt_growth(row), help="rate in the recent window vs. the rate before it")
        with chart_col:
            st.altair_chart(sparkline(lines["timestamp"], t0, t1, bucket_s, colour, trigger_onset), width="stretch")

        # Likely-trigger / knock-on explanation
        detail = row["role_detail"]
        if role == "trigger":
            st.markdown(f"⚡ **Likely trigger.** {detail} Later groups that began shortly after are marked as knock-on effects.")
        elif role == "knock-on" and trigger_row is not None:
            st.markdown(f"↳ **Probable knock-on effect** of #{int(trigger_row['rank'])} "
                        f"({trigger_row['services'][0]}). {detail}")
        else:
            st.caption(detail)

        st.caption(f"Sample raw line (line {row['sample_line_no']:,} of the input):")
        st.code(row["sample_raw"], language="text", wrap_lines=True)

        if compact:
            return
        c1, c2 = st.columns(2)
        with c1.expander("Score breakdown"):
            st.dataframe(score_breakdown(row, weights, n_services_total), hide_index=True, width="stretch")
            st.caption("Points = weight × normalised factor ÷ Σweights × 100; the five rows add up to the impact score.")
        with c2.expander(f"Raw lines ({len(lines):,})"):
            show = lines[["line_no", "timestamp", "severity", "service", "raw"]].sort_values("timestamp")
            if len(show) > MAX_RAW_ROWS:
                st.caption(f"Showing the first {MAX_RAW_ROWS:,} of {len(show):,} lines — download for the full set.")
            st.dataframe(show.head(MAX_RAW_ROWS), hide_index=True, width="stretch", height=300,
                         column_config={"line_no": st.column_config.NumberColumn("line", format="%d"),
                                        "timestamp": st.column_config.DatetimeColumn("time", format="HH:mm:ss.SSS")})
            st.download_button("Download these lines (.log)", "\n".join(show["raw"]).encode("utf-8"),
                               file_name=f"incident_{int(row['rank'])}.log", mime="text/plain",
                               key=f"dl_{int(row['cluster_id'])}")


# --------------------------------------------------------------------------- #
# Page: sidebar (data source + settings) and main view
# --------------------------------------------------------------------------- #

def main() -> None:  # noqa: C901 - a straightforward top-to-bottom UI script
    """Render the whole page: sidebar inputs, then the analysis results."""
    st.session_state.setdefault("log_text", None)
    st.session_state.setdefault("log_name", None)

    with st.sidebar:
        st.title("🔎 LogLens")
        st.caption("10,000 log lines → a handful of ranked incidents. Offline, rule-free.")

        st.subheader("1 · Load logs")
        if st.button("📂 Load sample log", type="primary", width="stretch",
                     help="10,000 lines from 5 services: a DB outage in payment-svc cascading everywhere"):
            st.session_state.log_text = load_sample_text()
            st.session_state.log_name = "sample_logs/sample.log"
            st.session_state.pop("uploaded_key", None)

        uploaded = st.file_uploader("Upload a .log / .txt file", type=["log", "txt", "text", "out"])
        if uploaded is not None:
            key = (uploaded.name, uploaded.size)
            if st.session_state.get("uploaded_key") != key:
                st.session_state.log_text = uploaded.getvalue().decode("utf-8", errors="replace")
                st.session_state.log_name = uploaded.name
                st.session_state.uploaded_key = key

        pasted = st.text_area("…or paste log lines", height=120, placeholder="2026-10-09T03:00:01Z ERROR [payment-svc] ...")
        if st.button("Analyse pasted text", disabled=not pasted.strip()):
            st.session_state.log_text = pasted
            st.session_state.log_name = "pasted text"

        st.subheader("2 · Settings")
        min_sev = st.selectbox("Minimum severity to analyse", ["WARN", "ERROR", "INFO", "DEBUG"], index=0,
                               help="Lines below this level are counted but not grouped into incidents.")
        method_label = st.radio("Grouping method", ["Drain template mining", "TF-IDF + agglomerative"], index=0,
                                help="Drain learns templates token-by-token (fast, default). "
                                     "TF-IDF clusters on token overlap — a fallback for free-form messages.")
        method = "drain" if method_label.startswith("Drain") else "tfidf"
        similarity = st.slider("Similarity threshold", 0.3, 0.9, 0.5, 0.05,
                               help="Higher = stricter grouping (more, smaller incidents).")
        knock_on_min = st.slider("Knock-on window (minutes)", 1, 30, 5,
                                 help="Groups that start within this long after the trigger are marked as knock-on effects.")
        max_cards = st.number_input("Incident cards to show", 3, 50, 10)
        with st.expander("Score weights"):
            weights = {k: st.slider(k.replace("_", " ").title(), 0.0, 1.0, float(v), 0.05)
                       for k, v in DEFAULT_WEIGHTS.items()}
        show_background = st.checkbox("Show background-noise groups", value=True)

    # --- Main view ----------------------------------------------------------------
    st.title("🔎 LogLens")
    st.markdown("**From 10,000 near-identical log lines to the handful of incidents that matter — "
                "grouped without rules, ranked by impact, with the likely trigger called out.**")

    text = st.session_state.log_text
    if not text:
        st.info("👈 Load the sample log, upload a `.log`/`.txt` file, or paste lines in the sidebar to begin.")
        st.markdown(
            """
            **How it works**

            1. **Ingest** — tolerant regexes pull out the timestamp, severity, service and message
               (ISO / syslog / Apache timestamps; `[service]`, `service:` or `service=` names). Lines that
               don't parse are skipped, never fatal.
            2. **Group** — numbers, IDs, UUIDs, IPs, hex, durations and paths are replaced by placeholders,
               then a Drain-style template miner learns one template per error family. No per-error rules.
            3. **Rank** — each group is scored on occurrences, severity, services affected, growth and
               start time; the breakdown is shown on every card.
            4. **Explain** — the earliest-starting group is flagged as the likely trigger and groups that
               began shortly after it, in other services, as probable knock-on effects.
            """
        )
        st.stop()

    min_rank = SEVERITY_RANK[min_sev]
    with st.spinner("Parsing and grouping…"):
        df, cand, templates, stats = run_pipeline(text, min_rank, method, similarity)

    if df.empty:
        st.error("No lines with a recognisable timestamp were found. LogLens needs a timestamp per line "
                 "(e.g. `2026-10-09T03:00:01Z`, `2026-10-09 03:00:01,123`, `Oct  9 03:00:01`).")
        if stats["skipped_samples"]:
            st.code("\n".join(f"{n}: {s}" for n, s in stats["skipped_samples"]), language="text")
        st.stop()

    if cand.empty:
        st.warning(f"Parsed {stats['parsed']:,} lines but none at **{min_sev}** or above. "
                   "Lower the minimum severity in the sidebar.")
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

    # --- Summary banner ---------------------------------------------------------
    extra = f" (+{plural(len(background), 'background noise group')})" if len(background) else ""
    st.success(
        f"### {plural(stats['total_lines'], 'line')} → {plural(len(incidents), 'incident')}{extra}\n"
        f"`{st.session_state.log_name}` · {plural(len(cand), 'line')} at {min_sev}+ collapsed from "
        f"{plural(stats['n_unique'], 'distinct message')} into {plural(len(inc), 'group')} in {stats['seconds']:.2f} s"
    )
    k = st.columns(6)
    k[0].metric("Lines in file", f"{stats['total_lines']:,}")
    k[1].metric("Parsed", f"{stats['parsed']:,}", help=f"{stats['continuation']:,} stack-trace continuation lines attached")
    k[2].metric("Skipped", f"{stats['skipped']:,}", help="lines without a recognisable timestamp")
    k[3].metric(f"{min_sev}+ lines", f"{len(cand):,}")
    k[4].metric("Services", f"{df['service'].nunique()}")
    k[5].metric("Time span", fmt_duration(span_s), help=f"{t0:%Y-%m-%d %H:%M:%S} → {t1:%Y-%m-%d %H:%M:%S}")

    if trigger_row is not None:
        knock_ons = incidents[incidents["role"] == "knock-on"]
        st.error(
            f"⚡ **Likely trigger:** `{trigger_row['template']}` in **{', '.join(trigger_row['services'])}** — "
            f"first seen {trigger_row['first_seen']:%H:%M:%S}. "
            + (f"**{len(knock_ons)} other group{'s' if len(knock_ons) != 1 else ''}** started within "
               f"{knock_on_min} min afterwards across {knock_ons['services'].explode().nunique()} service(s) "
               f"— probable knock-on effects." if len(knock_ons) else "No other group started shortly after it.")
        )
    for note in ranked.notes:
        st.caption(f"ℹ️ {note}")

    # --- Overall timeline -------------------------------------------------------
    st.subheader(f"Timeline — {min_sev}+ lines per {bucket_label}, coloured by group")
    st.altair_chart(timeline_chart(cand, inc, colours, t0, t1, bucket_s, bucket_label, trigger_onset), width="stretch")

    # --- Incident cards ---------------------------------------------------------
    st.subheader(f"Ranked incidents ({len(incidents)})")
    st.caption("Ranked by impact score. ⚡ = likely trigger, ↳ = started shortly after the trigger.")
    for _, row in incidents.head(int(max_cards)).iterrows():
        lines = cand[cand["cluster_id"] == row["cluster_id"]]
        render_card(row, lines, colours.get(int(row["cluster_id"]), OTHER_COLOUR), weights, n_services_total,
                    t0, t1, bucket_s, trigger_onset, trigger_row)
    if len(incidents) > max_cards:
        st.info(f"Showing the top {int(max_cards)} of {len(incidents)} incidents — raise the limit in the sidebar "
                "or use the table below.")

    if show_background and len(background):
        with st.expander(f"Background noise groups ({len(background)}) — steady before the trigger, probably not the cause"):
            for _, row in background.iterrows():
                lines = cand[cand["cluster_id"] == row["cluster_id"]]
                render_card(row, lines, colours.get(int(row["cluster_id"]), OTHER_COLOUR), weights, n_services_total,
                            t0, t1, bucket_s, trigger_onset, trigger_row, compact=True)

    # --- Tables & downloads -----------------------------------------------------
    with st.expander("All groups as a table / download"):
        table = inc[["rank", "score", "role", "max_severity", "count", "n_services", "services", "first_seen",
                     "last_seen", "growth_ratio", "template"]].copy()
        table["services"] = table["services"].apply(", ".join)
        table["score"] = table["score"].round(1)
        table["growth_ratio"] = table["growth_ratio"].round(2)
        st.dataframe(table, hide_index=True, width="stretch")
        st.download_button("Download incidents (.csv)", table.to_csv(index=False).encode("utf-8"),
                           file_name="loglens_incidents.csv", mime="text/csv")

    with st.expander("Parsing details"):
        c1, c2 = st.columns(2)
        c1.markdown("**Lines by severity**")
        c1.dataframe(df["severity"].value_counts().reindex(SEVERITY_ORDER).dropna().astype(int).rename("lines"),
                     width="stretch")
        c2.markdown("**Lines by service**")
        c2.dataframe(df["service"].value_counts().rename("lines"), width="stretch")
        if stats["skipped_samples"]:
            st.markdown(f"**Skipped lines** ({stats['skipped']:,} total, first {len(stats['skipped_samples'])} shown)")
            st.code("\n".join(f"line {n}: {s}" for n, s in stats["skipped_samples"]), language="text")


if __name__ == "__main__":
    main()
