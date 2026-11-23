```text
          .--~~~~~~~~~~~~~~~--.
      .-~~        .---.        ~~-.
   .-~          .'  _  '.          ~-.
  (            |   (_)   |            )
   `-.          '.     .'          .-'
      `~-.        '---'        .-~'
          `~--.._________..--~'

  _                _
 | |    ___   __ _| |    ___ _ __  ___
 | |   / _ \ / _` | |   / _ \ '_ \/ __|
 | |__| (_) | (_| | |__|  __/ | | \__ \
 |_____\___/ \__, |_____\___|_| |_|___/
             |___/

     find the signal in 10,000 log lines
```

**LogLens** turns a raw log file into a handful of ranked, explained incidents — which error groups exist, how big each one is, when each started, which services it hit and which one most likely set the others off. It needs no API keys, no database and no hand-written rules about what an error "looks like", and it is deployed as a FastAPI function + static frontend on Vercel.

On the bundled 10,000-line demo log it reports **8 incidents (+4 background-noise groups)** in about **0.3 seconds**, names the likely trigger (database timeouts in `payment-svc`) and marks the seven groups that started within minutes of it as probable knock-on effects.

Deployed Link: [LogLens](https://loglens-byteforce.vercel.app/)

---

## Contents

1. [Problem statement](#problem-statement)
2. [Team](#team)
3. [What we built](#what-we-built)
4. [Why we built it this way](#why-we-built-it-this-way)
5. [Installation](#installation)
6. [Running LogLens](#running-loglens)
7. [API reference](#api-reference)
8. [Deployment](#deployment)
9. [Checking that it works](#checking-that-it-works)
10. [How it works under the hood](#how-it-works-under-the-hood)
11. [Unfinished features and known limitations](#unfinished-features-and-known-limitations)
12. [Project layout](#project-layout)

---

## Problem statement

We selected **Problem Statement 8 — "Finding the signal in 10,000 log lines at 3 a.m."**
*Submitted by Vinay.*

> An on-call engineer is paged at three in the morning and has to scroll thousands of near-identical log lines to work out what broke. Build a tool that ingests raw logs, groups similar errors without hand-written rules, and ranks what it finds by impact — when each started, which service it hit, what likely triggered it. A good outcome: a 10,000-line log becomes a handful of incidents someone can act on inside a minute.

How the requirements map onto LogLens:

| Requirement in the statement | Where it lives | Status |
|---|---|---|
| Ingest raw logs | `parser.py` — paste, upload or load the sample; several timestamp/layout formats | ✅ |
| Group similar errors **without hand-written rules** | `cluster.py` — placeholder normalisation + Drain template mining (TF-IDF fallback) | ✅ |
| Rank by impact | `rank.py` — 0–100 score from five transparent factors, breakdown shown per incident | ✅ |
| When each started | first/last seen, onset time, per-incident sparkline, overall timeline | ✅ |
| Which service it hit | affected-service count and names on every card; service column in the raw-lines view and the CSV export | ✅ |
| What likely triggered it | ⚡ likely-trigger callout, ↳ knock-on lags, 〰 background noise | ✅ (heuristic) |
| 10,000 lines → a handful of incidents inside a minute | 10,000 lines in ~0.3 s; 100,000 lines in ~1.5 s | ✅ |

---

## Team

**Team:** `2392608004-ByteForce`

| USN | Name |
|---|---|
| 2392608004 | Anurag Tiwari |
| 2392608017 | Saksham Hada |
| 2392608086 | Shriyam Gupta |
| 2392608082 | Ansh Raj |
| 2392608141 | Jatin Alwani |
| 2392608048 | Rohitash Jangir |

---

## What we built

LogLens is a **FastAPI** app (one Python function on Vercel) plus a **static HTML/CSS/vanilla-JS frontend**. The pipeline is pure Python + pandas/NumPy and runs inside the API function; the browser only renders JSON.

```text
                        ┌─────────────── Vercel ───────────────┐
 raw log text ──POST──> │ api/index.py  ->  loglens/service.py │
 (paste/upload)         │   (FastAPI)        parser -> cluster  │──JSON──┐
                        │                    -> rank -> summary │        │
                        └──────────────────────────────────────┘        v
                                        public/ static frontend: banner, KPIs,
                                        cascade strip, timeline, incident cards,
                                        filters, CSV/raw-line downloads
```

| Piece | File | What it does |
|---|---|---|
| **Ingest** | `parser.py` | Reads each line tolerantly: finds a timestamp (ISO-8601 in several spellings, syslog `Oct  9 03:00:01`, Apache/CLF, Unix epoch), a severity (`ERROR`, `[warn]`, `level=error`, …) and a service name (`[payment-svc]`, `payment-svc:`, `service=…`, `logger -`, syslog program, docker-compose prefix), and keeps the rest as the message. Stack-trace continuation lines are attached to the line above; anything unparseable is counted and skipped, never fatal. |
| **Group** | `cluster.py` | Replaces variable fragments with placeholders (numbers, IDs, UUIDs, IPs, hex, durations, sizes, paths, URLs, e-mails) and then mines message *templates* with a from-scratch implementation of **Drain** (He et al., 2017). An alternative **TF-IDF + agglomerative clustering** grouping is one click away. Nothing in the code knows what any specific error looks like. |
| **Rank** | `rank.py` | Scores every group 0–100 from five explainable factors — occurrences, severity, services affected, growth and start time — and assigns a role: **trigger**, **knock-on**, **background** or **independent**. The per-factor breakdown is shown on every card and the rows add up to the score. |
| **Orchestration** | `loglens/service.py` | Runs parse → filter → cluster → rank and serialises everything to JSON-safe types (timestamps to ISO strings, NumPy scalars to plain numbers, NaN/inf to `null`). Also computes the window/bucket resolution, sparklines, the stacked timeline and the parsing-detail counts. |
| **HTTP API** | `api/index.py` | FastAPI app with `GET /api/health` and `POST /api/analyze`: Pydantic validation, a 4 MB request cap (413), graceful 400 when TF-IDF/scikit-learn is unavailable, and a JSON 500 handler. |
| **UI** | `public/index.html`, `public/style.css`, `public/app.js` | Static frontend: hero landing, summary banner ("10,000 lines → 8 incidents"), KPI strip, ⚡ trigger + cascade strip, Vega-Lite timeline and per-card sparklines, ranked incident cards (first/last seen, services, count, growth, sample raw line, score breakdown, raw-lines table), role/template/service filters, sort, CSV export, parsing details, team/about/contact dialogs. Sidebar controls for severity floor, grouping method, similarity threshold, knock-on window, card count and score weights (300 ms debounce + `AbortController`). |
| **Demo data** | `generate_sample_log.py`, `sample_logs/sample.log` | Seeded generator for a realistic 10,000-line, 60-minute log from five services in three different line formats, with normal traffic, steady background noise, deliberately malformed lines and a scripted cascade (DB timeouts → upstream timeouts → 502s → queue saturation → publish failures → circuit breaker → expired reservations). |
| **Tests** | `tests/test_pipeline.py`, `tests/test_api.py` | 23 pipeline cases (parser formats, normaliser, Drain and TF-IDF grouping, scoring, end-to-end root-cause check) plus 22 API cases (health, happy path, timeline stacking, strict JSON, 413/422, edge cases, rewrite compatibility). |

**Stack:** Python 3.12 (Vercel runtime) · FastAPI · pandas · NumPy · static HTML/CSS/JS · Vega-Lite (pinned CDN) · pytest. scikit-learn is a **dev-only** dependency (see [Why TF-IDF is off in the hosted build](#why-tf-idf-is-off-in-the-hosted-build)). No paid APIs, no database, no external services.

---

## Why we built it this way

**Why no rules?** Regex/keyword rules only catch errors someone has already seen and written a rule for — exactly the ones that *don't* page you at 3 a.m. LogLens instead learns the message templates from the file itself: lines that differ only in IDs, numbers, hosts or durations collapse into one group, whatever the error text happens to be.

**Why Drain?** It is the standard algorithm for online log template mining: a fixed-depth prefix tree keyed by token count and leading tokens with a similarity test at the leaves. It is linear in the number of lines, needs no training data, runs offline and produces human-readable templates (`Database connection timeout after <DUR> (pool=<*>, host=<IP>)`) instead of opaque cluster numbers. The TF-IDF/agglomerative option exists as a second opinion and because judges may ask "why not classic clustering?".

**Why heuristics for ranking instead of a model?** An on-call engineer needs to *trust* the ordering. Five named factors with visible weights, a breakdown table on every card and sliders to change the weights are something a person can argue with; a learned score is not. The same goes for the trigger/knock-on logic: it is explained in plain words on the card ("earliest group with a clear onset", "started 18 s after the trigger in checkout-svc").

**Why FastAPI + a static frontend?** The original version was a Streamlit app, but Streamlit needs a long-lived server with WebSockets and cannot run as a Vercel serverless function. Splitting the pipeline into a stateless JSON API and a build-free static frontend keeps the exact same pipeline and design while deploying on Vercel's free tier with no Node build step — the single biggest source of Vercel build failures — and it still runs offline on a laptop (`python dev.py`).

**Why a generated demo log?** Real incident logs are confidential. A seeded generator gives a realistic multi-service, multi-format file with a *known* answer, which means the result can be verified rather than just admired (see [Checking that it works](#checking-that-it-works)).

---

## Installation

### Prerequisites

- **Python 3.12** for the Vercel runtime (`.python-version`); locally, Python 3.10+ works (developed and verified on 3.11 and 3.12).
- **pip** (ships with Python) and **git**.
- Any OS — Windows, macOS or Linux. No GPU, no Docker, no internet after `pip install`.
- Optional: the [Vercel CLI](https://vercel.com/docs/cli) (`npm i -g vercel`) for `vercel dev` / `vercel --prod`.

Check your Python first:

```bash
python --version      # Windows
python3 --version     # macOS / Linux
```

### 1. Get the code

```bash
git clone https://github.com/sakshamhada-tech/LogLens.git
cd LogLens
```

### 2. Create and activate a virtual environment

**Windows — PowerShell**

```powershell
py -3.12 -m venv .venv          # or:  python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows — Command Prompt**

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the dependencies

```bash
pip install -r requirements-dev.txt
```

Two requirement files exist on purpose:

| File | Contents | Used by |
|---|---|---|
| `requirements.txt` | `fastapi`, `pandas`, `numpy` — **runtime only** | Vercel's function bundle (kept under the 250 MB unzipped limit) |
| `requirements-dev.txt` | `-r requirements.txt` + `pytest`, `httpx`, `uvicorn`, `scikit-learn` | your laptop, the test suite, the TF-IDF option |

### Troubleshooting

| Symptom | Fix |
|---|---|
| `python3.12: command not found` | Use whatever runs Python 3.10+: `python -m venv .venv`, `py -3 -m venv .venv`. |
| PowerShell: *"running scripts is disabled on this system"* | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Command Prompt and `.venv\Scripts\activate.bat`. |
| `uvicorn: command not found` | The venv isn't activated, or you installed only `requirements.txt`. Activate it and `pip install -r requirements-dev.txt`. |
| `ModuleNotFoundError: fastapi` / `pandas` | Same cause — install the dev requirements. |
| Port 8000 already in use | `uvicorn api.index:app --port 8010` (and open that port). |
| VS Code uses the wrong Python | `Ctrl/Cmd + Shift + P` → **Python: Select Interpreter** → pick the one inside `.venv`. |

---

## Running LogLens

### The quick way (one process, one origin)

```bash
python dev.py
```

Open <http://127.0.0.1:8000>. `dev.py` mounts the same FastAPI app Vercel runs **and** serves `public/` as static files, so the frontend and the API share one origin exactly as they do in production. It is excluded from the deployment bundle.

### The production-faithful way (Vercel CLI)

```bash
vercel dev          # serves public/ statically and api/index.py as a function
```

This is the closest thing to the real deployment; use it when checking rewrites, headers or the Python runtime.

### The manual way (two terminals)

```bash
# terminal 1 — API
uvicorn api.index:app --reload --port 8000

# terminal 2 — static frontend (from the repo root)
python -m http.server 3000 --directory public
```

The browser must reach both on the same origin; open <http://127.0.0.1:3000> only if you add a proxy, otherwise prefer `python dev.py` or `vercel dev`. `uvicorn` alone serves `/api/*` only.

### Using the app

1. **Load logs** (sidebar, step 1) in any of three ways:
   - **📂 Load 10K sample log** — the bundled 10,000-line demo (fastest way to see it work);
   - **Upload** a `.log` / `.txt` / `.text` / `.out` file (≤ 4 MB on the hosted deployment);
   - **Paste** lines into the text box and click **Analyse pasted text**.
2. **Read the results** (main pane):
   - the **banner** — `N lines → K incidents (+B background noise groups)` and how long the analysis took;
   - the **KPI strip** — lines in file, parsed, skipped, lines at the chosen severity, services, and the span of the log itself (not processing time);
   - the **⚡ root-cause trigger + cascade strip** — the earliest group with a clear onset, with knock-ons listed as `+18 s`, `+40 s`, … after it;
   - the **timeline** — lines per time bucket, coloured by incident, with a dashed rule at the trigger onset;
   - the **ranked incident cards** — template, impact ring, role badge (⚡ trigger · ↳ knock-on · 〰 background), first/last seen, services, count, growth, sparkline, tabs for the sample raw line, the score breakdown and all raw lines, plus a per-incident `.log` download;
   - **All groups as a table / CSV export** and **Parsing details** at the bottom.
3. **Filter and sort** — role pills, template/service search, service multi-select and sort order all work client-side on the returned incidents; the **Incident cards to show** control limits how many render.
4. **Tune** (sidebar, step 2): minimum severity (default `WARN`), grouping method (Drain; TF-IDF is disabled in the hosted build), similarity threshold, knock-on window, card count, score weights. Each change re-runs the analysis after a 300 ms debounce, cancelling the previous request.

Templates use placeholders: `<NUM>`, `<IP>`, `<DUR>`, `<UUID>`, `<PATH>`, … are inserted by the normaliser, and `<*>` marks a position that Drain found to vary between lines of the same group.

### Other commands

```bash
python -m pytest -q                                     # run all 45 tests
python generate_sample_log.py                           # regenerate sample_logs/sample.log (10,000 lines, seed 42)
python generate_sample_log.py --lines 50000 --seed 7 --out big.log
python -c "from generate_sample_log import generate; from pathlib import Path; from datetime import datetime; Path('public/sample_logs/sample.log').write_text('\n'.join(generate(10000, 42, datetime(2026,10,9,2,30), 60, 22)) + '\n')"
```

---

## API reference

Base URL: the deployment root (`https://<your-project>.vercel.app`). All responses are JSON; the API is stateless and keeps nothing between requests.

### `GET /api/health`

```bash
curl https://<your-project>.vercel.app/api/health
```

```json
{ "status": "ok" }
```

### `POST /api/analyze`

| Field | Type | Default | Notes |
|---|---|---|---|
| `text` | string | `""` | Raw log text. Max **4,000,000 bytes** (utf-8) → `413` above that. |
| `min_severity` | `"WARN"` \| `"ERROR"` \| `"INFO"` \| `"DEBUG"` | `"WARN"` | Lines below this level are counted but not grouped. |
| `method` | `"drain"` \| `"tfidf"` | `"drain"` | `"tfidf"` returns `400` when scikit-learn is not installed (the hosted build). |
| `similarity` | float 0.3–0.9 | `0.5` | Higher = stricter grouping. |
| `knock_on_minutes` | int 1–30 | `5` | Window after the trigger in which other groups become knock-ons. |
| `weights` | object | `{"count":0.30,"severity":0.25,"services":0.20,"growth":0.15,"start":0.10}` | Each 0–1. |

```bash
curl -X POST https://<your-project>.vercel.app/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text":"2026-10-09 10:05:00 ERROR [database] Connection refused\n2026-10-09 10:05:20 ERROR [web] Login failed: database unavailable\n2026-10-09 10:05:25 ERROR [web] Login failed: database unavailable","min_severity":"WARN"}'
```

Response (abridged — every key is always present):

```json
{
  "error": null,
  "empty_reason": null,
  "stats": {
    "total_lines": 3, "parsed": 3, "continuation": 0, "skipped": 0, "blank": 0,
    "skipped_samples": [], "n_unique": 2, "seconds": 0.01,
    "candidate_count": 3, "n_services_total": 2, "services_detected_count": 2
  },
  "window": { "t0": "2026-10-09T10:05:00", "t1": "2026-10-09T10:05:25",
              "span_s": 25.0, "bucket_s": 10, "bucket_label": "10 s" },
  "notes": [],
  "trigger_id": 0,
  "fallback_mode": false,
  "incidents": [
    {
      "rank": 1, "cluster_id": 0, "template": "Connection refused", "count": 1,
      "max_severity": "ERROR", "services": ["database"], "n_services": 1,
      "first_seen": "2026-10-09T10:05:00", "last_seen": "2026-10-09T10:05:00",
      "growth_ratio": 1.0, "count_earlier": 1, "role": "trigger",
      "role_detail": "…", "lag_s": 0.0, "score": 61.2,
      "score_breakdown": [{ "Factor": "Occurrences", "Evidence": "1 lines",
                            "Normalised": 0.31, "Weight": 0.3, "Points": 9.3 }],
      "sample_raw": "2026-10-09 10:05:00 ERROR [database] Connection refused",
      "sample_line_no": 1, "onset": "2026-10-09T10:05:00",
      "sparkline": [{ "t": "2026-10-09T10:05:00", "lines": 1 }],
      "raw_lines": [{ "line_no": 1, "timestamp": "2026-10-09T10:05:00",
                      "severity": "ERROR", "service": "database",
                      "raw": "2026-10-09 10:05:00 ERROR [database] Connection refused" }],
      "raw_lines_total": 1
    }
  ],
  "timeline": [{ "bucket": "2026-10-09T10:05:00", "bucket_end": "2026-10-09T10:05:10",
                 "incident_cluster_id": 0, "series": "#1 database: Connection refused",
                 "lines": 1, "y0": 0, "y1": 1 }],
  "severity_counts": { "ERROR": 3 },
  "service_counts": { "database": 1, "web": 2 }
}
```

Edge cases return **HTTP 200** with a reason instead of an error page:

| `empty_reason` | When |
|---|---|
| `empty_input` | `text` is empty or whitespace. |
| `no_timestamps` | Nothing parseable — `stats.skipped_samples` lists the first offending lines. |
| `no_severity_lines` | Parsed lines exist but none at/above `min_severity`. |

Other status codes: `413` (payload over 4 MB), `422` (validation), `400` (TF-IDF requested without scikit-learn), `500` (unexpected — always JSON `{"detail": "..."}`).

---

## Deployment

The repo is already configured for Vercel: `vercel.json` rewrites `/api/(.*)` to the `api/index.py` function, `public/` is served as static hosting, and `.python-version` pins Python 3.12. There is **no build step**. The function carries a tiny middleware so it answers correctly whether the platform forwards the original path (`/api/analyze`) or the rewrite destination (`/api/index`), which removes the most common "404 on the API" failure mode.

### Option A — Git import (recommended, no CLI)

1. Push the repository to GitHub.
2. Go to <https://vercel.com/new> and **import** the repository.
3. Leave **Framework Preset** on **Other**, and leave **Build Command**, **Output Directory**, **Install Command** and **Root Directory** empty/default.
4. Click **Deploy**.

Vercel then installs `requirements.txt`, packs `api/index.py` (plus `loglens/`), serves `public/`, and applies the rewrites and cache headers from `vercel.json`. The first build takes a couple of minutes because of pandas/NumPy.

### Option B — CLI

```bash
npm i -g vercel
vercel            # preview deployment
vercel --prod     # production
```

### After the first deploy

Update the `Deployed Link:` line at the top of this README with the URL Vercel gives you, then commit it. Nothing else needs configuring — there are no environment variables, no secrets and no database.

### Why TF-IDF is off in the hosted build

scikit-learn (plus scipy) is roughly 150 MB on its own; with pandas and NumPy the unzipped function would approach or cross Vercel's 250 MB limit and the deployment would fail. The grouping-method control therefore keeps the TF-IDF option **visible but disabled**, with the tooltip *"Available in local/dev install only"*, and the API returns `400` with the same message if it is requested anyway. Install `requirements-dev.txt` and run locally to use it.

---

## Checking that it works

You don't need to be a logging expert to verify LogLens: every test input has a **known answer**, so "working" just means the app recovers the story that was planted in the log.

### 1. The sample log has an answer key (30 seconds)

The demo log is generated from a script (described at the top of `generate_sample_log.py`): an hour of normal traffic, four harmless warnings that were there all along, and at **02:52:00** the primary database behind `payment-svc` starts timing out, which breaks seven other things over the next four minutes. Click **📂 Load 10K sample log** and compare:

| You should see | Meaning |
|---|---|
| Banner: **10,000 lines → 8 incidents (+4 background noise groups)** | 3,469 WARN+ lines collapsed into 12 groups |
| ⚡ Likely trigger: **payment-svc** · `Database connection timeout after <DUR> …` · first seen **02:52:01** | the planted root cause was found |
| Knock-ons at roughly **+18 s, +26 s, +40 s, +69 s, +1.6 min, +3 min, +4 min** across `checkout-svc`, `api-gateway`, `notification-svc`, `inventory-svc` | the planted cascade was found, in order |
| Background: invalid JWT, cache miss, slow query, SMTP retry | old noise was not mistaken for the incident |
| Parsed 9,994 · 4 continuation · 2 skipped | the deliberately broken lines did not break anything |

### 2. Write your own story (2 minutes)

Click **✨ Try 22-line mini story** (or paste the block below into the sidebar and press **Analyse pasted text**). The story *you* planted: a backup job has been nagging about disk space all along; at 10:05:00 the **database** goes down; 20 seconds later the **web** app starts failing logins because of it.

<details>
<summary>22-line mini log (click to expand)</summary>

```text
2026-10-09 10:00:05 WARN [backup-job] Disk usage at 81% on /var/backups
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
2026-10-09 10:08:05 WARN [backup-job] Disk usage at 83% on /var/backups
```

</details>

Expected result:

- banner **22 lines → 2 incidents (+1 background noise group)**, "12 distinct messages into 3 groups";
- **database** — ⚡ likely trigger (8 lines);
- **web** — ↳ probable knock-on, **+20 s** after the trigger (7 lines);
- **backup-job** — 〰 background noise (5 lines). 8 + 7 + 5 = 20, nothing lost.

"12 distinct messages → 3 groups" is the no-rules requirement made visible: `attempt 1…8` and `user 1041…7781` were recognised as the same message without anyone telling the tool that attempt numbers and user IDs don't matter.

### 3. Break it on purpose

| Do this | Expected |
|---|---|
| Move every `[database]` line 3 minutes later, so the web app fails *first* | the trigger flips to **web**; database becomes "knock-on (+3 min)" |
| Delete the dates and times | a red message: *No lines with a recognisable timestamp were found* — no crash |
| Paste something that isn't a log at all (a crash dump, a poem) | the same polite message |
| `python -m pytest -q` | `45 passed` |

---

## How it works under the hood

### Ingest — be tolerant, never crash

Each line is scanned for the earliest timestamp of any supported format. Header tokens after it (`[payment-svc]`, `ERROR`, `level=warn`, `com.acme.DbPool -`, …) are peeled off one by one; whatever remains is the message. Lines with no timestamp are glued to the previous record if they look like a stack trace (indented, `at …`, `Caused by:`), otherwise skipped and counted. Severities are normalised to `TRACE / DEBUG / INFO / WARN / ERROR / CRITICAL`; timestamps with zone information are converted to UTC.

### Group — placeholders + Drain

Variable fragments are replaced first: `5000ms → <DUR>`, `10.0.3.17:5432 → <IP>`, `/v1/charge → <PATH>`, `98765 → <NUM>`, UUIDs, hex hashes, e-mails, byte sizes. Short integers (≤ 3 digits) are deliberately kept so that Drain can decide: they become `<*>` where they vary (`attempt 3`) and stay where they are constant (`502 Bad Gateway`). Normalisation alone typically collapses 10,000 lines to a few hundred distinct strings.

Those strings are then fed, most frequent first, into **Drain**: a prefix tree keyed by token count and the first tokens, with a token-wise similarity test at the leaves. A message joins the most similar template if at least 50 % of positions match (the slider in the UI); positions that differ become `<*>`.

The fallback uses binary token-presence vectors (plain IDF would up-weight exactly the one-off tokens we want to ignore; tokens seen in a single line are dropped) and average-linkage agglomerative clustering on cosine distance, with a majority-vote template per cluster.

### Rank — five explainable factors

| Factor | Default weight | Normalised how |
|---|---|---|
| Occurrences | 0.30 | `log(1+count) / log(1+max count)` |
| Severity | 0.25 | ½ max level + ½ mean level (`WARN .5, ERROR .8, CRITICAL 1`) |
| Services affected | 0.20 | `services in group / services in log` |
| Growth | 0.15 | rate in the recent window (¼ of the span, clamped to 1–10 min) ÷ rate before it, log-scaled, capped at ×20 |
| Early start | 0.10 | earlier onset → higher; steady noise with no onset gets a neutral 0.5 |

Score = Σ weight × factor ÷ Σ weights × 100. Weights are sliders, and every card shows the breakdown.

### Explain — trigger, knock-on, background

A group has a **clear onset** when a long silence (≥ max(60 s, 5 % of the log's span)) is followed by dense repeats (silence ≥ 3× the group's 90th-percentile gap). Groups already logging steadily when the file begins are **background noise** — unless they spike later (> 4× their median per-minute rate), in which case the spike is their onset.

- **Likely trigger** = the group with a clear onset that started earliest (ties → higher score).
- **Probable knock-on** = any group whose onset falls within the knock-on window (default 5 min) after the trigger.
- If *no* group has a clear onset (e.g. the file covers only the incident) LogLens falls back to the literal rule — earliest-starting group — and says so on the card.

---

## Unfinished features and known limitations

This is a hackathon prototype. The following are **not** done, and we would rather you hear it from us:

**Input formats**

- **No timestamps → no analysis.** Every line needs a recognisable wall-clock timestamp. There is no fallback to line order, and relative counters such as `dmesg`'s `[ 1234.567890]` or Wine's `+timestamp` output are skipped. Crash dumps, build logs and plain console output therefore produce the "no recognisable timestamp" message rather than a result.
- **Structured JSON logs are not parsed as JSON.** The timestamp and level inside a JSON line are usually picked up, but the message shows a raw JSON fragment and the `service` field is missed, so the templates look ugly.
- **Service detection only knows common layouts** — `[svc]`, `svc:`, `service=…`, `logger -`, the syslog program name and docker-compose prefixes. A plain `ERROR api something happened` is parsed as service `unknown` with `api` left in the message, and a Java thread name in brackets can occasionally be mistaken for a service.
- **Lines with no severity word are treated as INFO**, so they are hidden by the default `WARN` floor; lower the floor to see them.
- **Syslog timestamps carry no year**, so the current year is assumed; a file that crosses New Year will be mis-ordered.
- **Stack-trace lines are attached to their parent line for display and download only** — their text is not used for grouping, so two different exceptions that share the same first line land in the same group.

**Grouping and ranking**

- **Causality is temporal, not proven.** "Likely trigger" means *earliest clear onset*; "knock-on" means *started shortly after*. Two unrelated incidents that begin within the window will be linked, and clock skew between hosts will mislead it. It is a strong first hint for triage, not a dependency graph.
- **Small inputs rarely have a "clear onset"** (a few dozen lines per group is the practical minimum). LogLens then falls back to earliest-group-first and says so, but the trigger call is weaker.
- **Drain is greedy and order-dependent.** Short messages with different meanings but the same shape can merge at the default threshold; raising the similarity slider splits them. Templates show `<*>` where a smarter placeholder name would be nicer. Depth and thresholds are fixed defaults — there is no automatic tuning.
- **Growth is relative to the file's own window.** A log that ends mid-incident shows "exploding" growth; one that covers hours after recovery shows decay. Both are correct but easy to misread.
- **No feedback loop.** You cannot tell LogLens "these two groups are the same" or "this is not the trigger" and have it remember.

**Product**

- **Single file, in memory, one shot.** Measured at 10,000 lines in ~0.3 s and 100,000 lines in ~1.5 s; not tested beyond that, and multi-GB files will not fit. No streaming / live tail, no multiple files, no correlation across files or days.
- **4 MB per request on the hosted deployment.** This is a hard limit of the Vercel function body (~4.5 MB); LogLens rejects anything larger with a friendly `413` / sidebar error rather than failing mid-upload. On a laptop there is no such cap (the browser refuses only > 4 MB uploads in the UI, for the same reason). The **10K sample** (≈1.3 MB) is well inside it; split bigger files and analyse them in parts.
- **TF-IDF grouping is disabled in the hosted build** (see [Why TF-IDF is off in the hosted build](#why-tf-idf-is-off-in-the-hosted-build)). Drain remains the default and the only engine online; install the dev requirements locally for TF-IDF.
- **Stateless, by design.** Nothing is written to disk, there is no database, no session and no cache between requests — identical inputs give identical output. Downloads (`.csv` of incidents, `.log` of a group's lines) are generated in the browser.
- **No integrations** — no Slack/PagerDuty alerts, no scheduled runs, no auth. The JSON API is public and unauthenticated, so do not post confidential logs to a public deployment.
- **Serverless cold starts.** The first request after idle can take ~1–2 s while the function boots (pandas import); warm analyses stay around 0.3 s.
- **UI coverage.** The 45 automated tests cover the pipeline and the HTTP API; the frontend is verified with a DOM harness (jsdom) plus real Vega-Lite compilation of the chart specs, not with a real browser in CI.
- **Not evaluated on non-English logs** or on logs from the wild beyond a handful of formats we tried; the demo file is synthetic.

What we would build next, in order: a line-order / relative-timestamp fallback, proper JSON-line parsing, smarter service discovery, stack-trace-aware grouping, and a merge/split feedback control on the incident cards.

---

## Project layout

```text
api/index.py               FastAPI app (`app`) — validation + JSON only; Vercel ASGI entrypoint
loglens/__init__.py        package exports
loglens/parser.py          tolerant log parsing -> pandas DataFrame
loglens/cluster.py         normalisation + Drain template miner + lazy TF-IDF fallback
loglens/rank.py            impact scoring, score breakdown, trigger / knock-on roles
loglens/service.py         analyze(): orchestrates the pipeline, returns JSON-safe dicts
public/index.html          single-page frontend shell (semantic, accessible)
public/style.css           light-mode design system (tokens, cards, badges, dialogs)
public/app.js              all UI logic: fetch/debounce/abort, cards, filters, charts, CSV
public/assets/team/*.jpg   team avatars used by the Team ByteForce dialog
public/sample_logs/sample.log   10,000-line demo served statically ("Load 10K sample")
generate_sample_log.py     seeded demo-log generator (dev tool, not deployed)
sample_logs/sample.log     source copy of the demo log
tests/test_pipeline.py     23 pipeline tests
tests/test_api.py          22 FastAPI tests
dev.py                     local launcher: API + public/ on one origin (not deployed)
requirements.txt           runtime only: fastapi, pandas, numpy
requirements-dev.txt       -r requirements.txt + pytest, httpx, uvicorn, scikit-learn
vercel.json                rewrites, function config, cache headers
.python-version            3.12
.vercelignore              keeps tests/dev files out of the deployment
```


