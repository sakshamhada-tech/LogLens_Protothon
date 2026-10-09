# 🔎 LogLens

**From 10,000 near-identical log lines to a handful of ranked, explained incidents — in seconds, offline, with no hand-written rules.**

LogLens is a hackathon prototype for **Problem Statement 8**:

> *An on-call engineer is paged at 3 a.m. and has to scroll through ~10,000 near-identical log lines to
> find what broke. Build a tool that ingests raw logs, groups similar errors without hand-written rules,
> and ranks them by impact, so 10,000 lines become a handful of actionable incidents in under a minute.*

On the bundled demo log LogLens turns **10,000 lines → 8 incidents (+4 background-noise groups)** in
about 0.3 s, names the **likely trigger** (database timeouts in `payment-svc`) and marks the seven
groups that started within minutes of it in the other services as **probable knock-on effects**.

---

## What was built

| Piece | File | What it does |
|---|---|---|
| **Ingest** | `parser.py` | Tolerant parsing of timestamp, severity, service and message. Handles ISO-8601 (`2026-10-09T03:00:01.123Z`, `2026-10-09 03:00:01,123`, offsets), syslog (`Oct  9 03:00:01`), Apache/CLF and epoch timestamps; `[service]`, `service:`, `service=`, `logger -` and docker-compose `service \|` prefixes; `level=` / `[ERROR]` / bare `ERROR` severities; logfmt `msg="…"`. Stack-trace continuation lines are attached to the previous record; anything else that does not parse is counted and skipped — never fatal. |
| **Group** | `cluster.py` | Normalises messages (numbers, IDs, UUIDs, IPs, hex, durations, sizes, paths, URLs, e-mails → placeholders), then mines templates with a from-scratch **Drain** implementation (He et al., 2017). A **TF-IDF + agglomerative clustering** fallback is one click away. No per-error rules anywhere. |
| **Rank** | `rank.py` | Impact score (0–100) from five transparent factors — occurrence count, severity, services affected, growth rate (recent vs. earlier) and start time — with the per-factor breakdown shown on every card. Also assigns each group a role: **trigger**, **knock-on**, **background** or **independent**. |
| **Explain / UI** | `app.py` | Streamlit app: summary banner ("10,000 lines → 8 incidents"), likely-trigger callout, overall timeline (lines per minute coloured by incident), ranked incident cards with first/last seen, affected services, count, growth, sparkline, sample raw line, score breakdown and an expandable raw-lines view with download. |
| **Demo data** | `generate_sample_log.py`, `sample_logs/sample.log` | Seeded generator for a realistic 10,000-line log from five services where DB timeouts in `payment-svc` cascade into `checkout-svc`, `api-gateway`, `notification-svc` and `inventory-svc`, on top of normal traffic and steady background noise. A **Load sample log** button loads it. |
| **Tests** | `tests/test_pipeline.py` | 23 pytest cases: parser formats, normaliser, Drain/TF-IDF grouping, scoring, and an end-to-end check that the root cause is found. |

Stack: Python 3.11, Streamlit, pandas, NumPy, scikit-learn, Altair (bundled with Streamlit).
No paid APIs, no external services — everything runs locally and offline.

---

## How to run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then click **📂 Load sample log** in the sidebar (or upload / paste your own `.log` / `.txt`).

Optional:

```bash
python generate_sample_log.py --lines 10000 --seed 42   # regenerate sample_logs/sample.log
pytest -q                                              # run the tests
```

Tested with Python 3.11, Streamlit 1.65, pandas 3.0, scikit-learn 1.9 (any recent versions should work; see `requirements.txt`).

---

## The approach

### 1. Ingest — be tolerant, never crash
Each line is scanned for the *earliest* timestamp of any supported format. Header tokens after it
(`[payment-svc]`, `ERROR`, `level=warn`, `com.acme.DbPool -`, …) are peeled off one by one; whatever
remains is the message. Lines with no timestamp are either glued to the previous record (indented /
`at …` / `Caused by:` stack-trace lines) or skipped and counted. Severities are normalised to
`TRACE / DEBUG / INFO / WARN / ERROR / CRITICAL`; timezones are converted to UTC.

### 2. Group — placeholders + Drain template mining
Variable fragments are replaced first (`5000ms → <DUR>`, `10.0.3.17:5432 → <IP>`, `/v1/charge → <PATH>`,
`98765 → <NUM>`, UUIDs, hex hashes, e-mails, …). Short integers (≤ 3 digits) are deliberately **kept**:
Drain turns them into `<*>` where they vary (`attempt 3/5`) and keeps them where they are constant
(`502 Bad Gateway`). Normalisation alone typically collapses 10,000 lines to a few hundred distinct
strings.

Those strings are then fed (most frequent first) into **Drain**: a fixed-depth prefix tree keyed by
token count and leading tokens, with a token-wise similarity test at the leaves. A message joins the
most similar template if ≥ 50 % of positions match (slider in the UI); positions that differ become
`<*>`. The template is therefore *learnt from the data* — nothing in the code knows what a "database
timeout" looks like.

Fallback: binary token-presence vectors (no IDF — it would up-weight exactly the one-off tokens we want
to ignore; tokens seen in a single log line are dropped) + average-linkage **agglomerative clustering**
on cosine distance, with a majority-vote template per cluster.

### 3. Rank — five explainable factors
For every group:

| Factor | Default weight | Normalised how |
|---|---|---|
| Occurrences | 0.30 | `log(1+count) / log(1+max count)` |
| Severity | 0.25 | ½ max level + ½ mean level (`WARN .5, ERROR .8, CRITICAL 1`) |
| Services affected | 0.20 | `n services / total services in the log` |
| Growth | 0.15 | rate in the recent window (¼ of the span, 1–10 min) ÷ rate before it, log-scaled, capped at ×20 |
| Early start | 0.10 | earlier onset → higher; steady noise with no onset gets a neutral 0.5 |

Score = Σ weight × factor ÷ Σ weights × 100. Weights are sliders in the sidebar and every card shows the
breakdown table (the rows add up to the score).

### 4. Explain — likely trigger and knock-on effects
A group has a **clear onset** when there is a long silence before its first line (≥ max(60 s, 5 % of the
window)) followed by dense repeats (silence ≥ 3× the group's 90th-percentile gap). Groups that were already
logging at a steady rate when the file begins are **background noise** — unless they *spike* later
(> 4× their median per-minute rate), in which case the spike counts as their onset.

* **Likely trigger** = the group with a clear onset that started earliest (ties → higher score).
* **Probable knock-on** = any group whose onset falls within the knock-on window (default 5 min,
  adjustable) after the trigger; the card says how long after and in which service(s).
* If *no* group has a clear onset (e.g. the file covers only the incident) LogLens falls back to the
  literal rule — earliest-starting group — and says so.

On the demo log this yields: `payment-svc` DB timeouts at 02:52:01 → `checkout-svc` upstream timeouts
+18 s → `api-gateway` 502s +40 s → pool exhaustion +26 s → thread-pool saturation in two services +69 s →
`notification-svc` publish failures +1.6 min → circuit breaker CRITICAL +3 min → `inventory-svc`
reservation expiries +4 min, while the slow queries, cache misses, JWT errors and SMTP retries that were
there all along are filed as background.

---

## Limitations (honest list)

* **Timestamps are required.** Lines without a recognisable timestamp are skipped (continuation lines
  are attached to the previous record). Syslog lines carry no year, so the current year is assumed.
* **Service detection is heuristic.** `[payment-svc]`, `payment-svc:`, `service=…`, `logger -` and
  docker-compose prefixes are recognised; unusual layouts fall back to `unknown`, and a Java thread name
  in brackets can occasionally be mistaken for a service.
* **Drain is greedy and order-dependent.** Short messages with different meanings but the same shape
  (`Invalid token for user <*>: expired` vs `… signature mismatch`) can merge at the default threshold;
  raise the similarity slider to split them. Templates may show `<*>` where a smarter placeholder
  would be nicer.
* **Causality is temporal, not proven.** "Likely trigger" means *earliest clear onset*; "knock-on"
  means *started shortly after*. It is a strong hint for a 3 a.m. triage, not a dependency graph. Two
  unrelated incidents that start within minutes of each other will be linked.
* **Single-file, in-memory.** Tuned for files up to a few hundred thousand lines; the TF-IDF fallback
  clusters at most 3,000 distinct normalised strings directly and assigns the rest to the nearest
  centroid. There is no streaming / tailing mode.
* **Growth is relative to the file's own window**, so a log that ends mid-incident shows "exploding"
  growth while one that covers hours after recovery shows decay — both are correct but worth knowing.
* No persistence, auth or multi-user state — it is a hackathon prototype.

---

## Project layout

```
app.py                  Streamlit UI (single command: streamlit run app.py)
parser.py               tolerant log parsing -> DataFrame
cluster.py              normalisation + Drain template miner + TF-IDF fallback
rank.py                 impact scoring, score breakdown, trigger / knock-on roles
generate_sample_log.py  seeded demo-log generator
sample_logs/sample.log  10,000-line demo (5 services, one root cause, cascading failures)
tests/test_pipeline.py  pytest suite
requirements.txt
```
