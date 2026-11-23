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

**LogLens** turns a raw log file into a handful of ranked, explained incidents: which error groups exist, how big each one is, when each started, which services it hit, and which one most likely set the others off. It needs no API keys, no database and no hand-written rules about what an error "looks like". It runs as a FastAPI function with a static frontend on Vercel.

On the bundled 10,000-line demo log it reports **8 incidents (+4 background-noise groups)** in about **0.3 seconds**, names the likely trigger (database timeouts in `payment-svc`) and marks the seven groups that started within minutes of it as probable knock-on effects.

**Live demo:** [https://loglens-byteforce.vercel.app](https://loglens-byteforce.vercel.app)

---

## Contents

1. [Problem statement](#problem-statement)
2. [Team](#team)
3. [What we built](#what-we-built)
4. [Why we built it this way](#why-we-built-it-this-way)
5. [Theming](#theming)
6. [Installation](#installation)
7. [Running LogLens](#running-loglens)
8. [API reference](#api-reference)
9. [Deployment](#deployment)
10. [Checking that it works](#checking-that-it-works)
11. [How it works under the hood](#how-it-works-under-the-hood)
12. [Limitations](#limitations)
13. [Project layout](#project-layout)

---

## Problem statement

We selected **Problem Statement 8: "Finding the signal in 10,000 log lines at 3 a.m."**
*Submitted by Vinay.*

> An on-call engineer is paged at three in the morning and has to scroll thousands of near-identical log lines to work out what broke. Build a tool that ingests raw logs, groups similar errors without hand-written rules, and ranks what it finds by impact: when each started, which service it hit, what likely triggered it. A good outcome: a 10,000-line log becomes a handful of incidents someone can act on inside a minute.

How the requirements map onto LogLens:

| Requirement in the statement | Where it lives | Status |
|---|---|---|
| Ingest raw logs | `loglens/parser.py`: paste, upload or load the sample; several timestamp and layout formats | ✅ |
| Group similar errors **without hand-written rules** | `loglens/cluster.py`: placeholder normalisation + Drain template mining (TF-IDF as a local-only alternative) | ✅ |
| Rank by impact | `loglens/rank.py`: 0–100 score from five transparent factors, with a breakdown on every incident | ✅ |
| When each started | first/last seen, onset time, per-incident sparkline, overall timeline | ✅ |
| Which service it hit | affected-service count and names on every card; service column in the raw-lines view and the CSV export | ✅ |
| What likely triggered it | ⚡ likely-trigger callout, ↳ knock-on lags, 〰 background noise | ✅ (heuristic) |
| 10,000 lines → a handful of incidents inside a minute | 10,000 lines in ~0.3 s; 100,000 lines in ~1.5 s | ✅ |

---

## Team

**Team:** `2392608004-ByteForce`

| USN | Name | Role |
|---|---|---|
| 2392608004 | Anurag Tiwari | Team Leader · UI/UX Designer |
| 2392608017 | Saksham Hada | Log Parsing & Data Ingestion |
| 2392608086 | Shriyam Gupta | Clustering & Template Mining Engine |
| 2392608082 | Ansh Raj | Impact Scoring, Root-Cause Logic & Testing |
| 2392608141 | Jatin Alwani | Debugging, Documentation & Product Strategy |
| 2392608048 | Rohitash Jangir | Pitch Deck & Presentation |

---

## What we built

LogLens is a **FastAPI** app (a single Python function on Vercel) plus a **static HTML/CSS/vanilla-JS frontend**. The pipeline is pure Python on pandas and NumPy and runs inside the API function; the browser only renders the JSON it returns.

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
| **Ingest** | `loglens/parser.py` | Reads each line tolerantly. Finds a timestamp (ISO-8601 in several spellings, syslog `Oct  9 03:00:01`, Apache/CLF, Unix epoch), a severity (`ERROR`, `[warn]`, `level=error`, …) and a service name (`[payment-svc]`, `payment-svc:`, `service=…`, `logger -`, syslog program, docker-compose prefix), and keeps the rest as the message. Stack-trace continuation lines are attached to the line above; anything unparseable is counted and skipped, never fatal. |
| **Group** | `loglens/cluster.py` | Replaces variable fragments with placeholders (numbers, IDs, UUIDs, IPs, hex, durations, sizes, paths, URLs, e-mails), then mines message *templates* with a from-scratch implementation of **Drain** (He et al., 2017). An alternative **TF-IDF + agglomerative clustering** mode is available in local installs. Nothing in the code knows what any specific error looks like. |
| **Rank** | `loglens/rank.py` | Scores every group 0–100 from five explainable factors (occurrences, severity, services affected, growth and start time) and assigns a role: **trigger**, **knock-on**, **background** or **independent**. The per-factor breakdown is shown on every card and the rows add up to the score. |
| **Orchestration** | `loglens/service.py` | Runs parse → filter → cluster → rank and serialises everything to JSON-safe types. Also computes the time buckets, sparklines, the stacked timeline and the parsing-detail counts. |
| **HTTP API** | `api/index.py` | FastAPI app with `GET /api/health` and `POST /api/analyze`: request validation, a 4 MB request cap, and JSON error responses. |
| **UI** | `public/index.html`, `public/style.css`, `public/app.js` | Static frontend with a light/dark theme, landing page, summary banner, KPI strip, ⚡ trigger and cascade strip, Vega-Lite timeline and sparklines, ranked incident cards, role/template/service filters, sorting, CSV export, parsing details, and Team / About / Contact dialogs. Sidebar controls for severity floor, grouping method, similarity threshold, knock-on window, card count and score weights. |
| **Demo data** | `generate_sample_log.py`, `sample_logs/sample.log` | Seeded generator for a realistic 10,000-line, 60-minute log from five services in three different line formats, with normal traffic, steady background noise, deliberately malformed lines and a scripted cascade (DB timeouts → upstream timeouts → 502s → queue saturation → publish failures → circuit breaker → expired reservations). |
| **Tests** | `tests/test_pipeline.py`, `tests/test_api.py` | 23 pipeline tests (parser formats, normaliser, Drain and TF-IDF grouping, scoring, and an end-to-end check that the planted root cause is found) plus 22 API tests. |

**Stack:** Python 3.12 · FastAPI · pandas · NumPy · static HTML/CSS/JS · Vega-Lite · pytest. scikit-learn is a dev-only dependency. No paid APIs, no database, no external services.

---

## Why we built it this way

**Why no rules?** Regex and keyword rules only catch errors someone has already seen and written a rule for, which are exactly the ones that *don't* page you at 3 a.m. LogLens instead learns the message templates from the file itself: lines that differ only in IDs, numbers, hosts or durations collapse into one group, whatever the error text happens to be.

**Why Drain?** It is the standard algorithm for online log template mining: a fixed-depth prefix tree keyed by token count and leading tokens, with a similarity test at the leaves. It is linear in the number of lines, needs no training data, and produces human-readable templates (`Database connection timeout after <DUR> (pool=<*>, host=<IP>)`) instead of opaque cluster numbers. The TF-IDF/agglomerative option exists as a second opinion for free-form messages.

**Why heuristics for ranking instead of a model?** An on-call engineer needs to *trust* the ordering. Five named factors with visible weights, a breakdown table on every card and sliders to change the weights are something a person can argue with; a learned score is not. The trigger and knock-on logic is explained in plain words on the card ("earliest group with a clear onset", "started 18 s after the trigger in checkout-svc").

**Why FastAPI and a static frontend?** The first version was a Streamlit app, which needs a long-lived server with WebSockets and cannot run as a Vercel serverless function. Splitting the pipeline into a stateless JSON API and a build-free static frontend keeps the same analysis and design while deploying on Vercel with no Node build step.

**Why a generated demo log?** Real incident logs are confidential. A seeded generator gives a realistic multi-service, multi-format file with a *known* answer, so the result can be verified rather than just admired (see [Checking that it works](#checking-that-it-works)).

---

## Theming

LogLens has a light and a dark theme. On a first visit it follows your operating system's setting, and once you use the toggle in the top bar (next to **Team ByteForce**) your choice is remembered in `localStorage`.

### Design tokens

Every colour in `public/style.css` goes through a named CSS custom property declared on `:root`: surfaces, text, borders, brand, trigger/danger, the severity colours, status colours and effects. The dark theme is a second block that overrides those values:

```css
:root { /* light values */ }
:root[data-theme="dark"] { /* dark overrides */ }
```

Because rules only reference token names, switching the palette restyles the whole app at once. Colours needed in JavaScript, such as the Vega-Lite axis and legend colours, are read back with `getComputedStyle`, and the charts re-render when the theme changes.

Two tokens were split because they did two jobs in the original light design:

- `--ll-brand` was used both as a text colour and as a fill behind white text. Fills now use `--ll-brand-fill`, `--ll-brand-fill-2` and `--ll-brand-fill-3`.
- `--ll-ink` was used both as the primary text colour and as the fill of the GitHub button. That button now has its own `--ll-btn-ink`, so it doesn't turn white-on-white in dark mode.

### No flash of the wrong theme

A small inline script in `<head>` runs before the first paint. It reads the saved preference, falls back to `prefers-color-scheme`, and sets `data-theme` on `<html>`. `<meta name="color-scheme" content="light dark">` lets the browser style native widgets (scrollbars, inputs, dialogs) to match.

### Transition

Switching to dark sweeps down from the top edge, and switching to light sweeps up from the bottom. This uses the [View Transitions API](https://developer.mozilla.org/en-US/docs/Web/API/View_Transition_API): the browser snapshots the page, the theme changes inside `startViewTransition`, and the new snapshot is revealed by animating its `clip-path`. The page stays visible and readable throughout. Browsers without the API (such as Firefox) get a simpler fallback, a sheet in the destination colour that sweeps across the screen. Users with `prefers-reduced-motion` get an instant switch with no animation.

### Buttons

Buttons lift 2 px on hover (3 px for large buttons) with a deeper shadow, and settle back with a slight scale-down when pressed. The primary button has a diagonal shine that passes across it once on hover. Only `transform`, `box-shadow`, `background` and `border-color` are animated, so nothing reflows. All of this is disabled under `prefers-reduced-motion`.

---

## Installation

### Prerequisites

- **Python 3.12** (what Vercel uses, pinned in `.python-version`). Python 3.10 or newer works locally.
- **pip** and **git**.
- Any OS: Windows, macOS or Linux. No GPU or Docker needed.
- Optional: the [Vercel CLI](https://vercel.com/docs/cli) (`npm i -g vercel`) for `vercel dev` and `vercel --prod`.

### 1. Get the code

```bash
git clone https://github.com/sakshamhada-tech/LogLens_Protothon.git
cd LogLens_Protothon
```

### 2. Create and activate a virtual environment

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt)**

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

There are two requirement files on purpose:

| File | Contents | Used by |
|---|---|---|
| `requirements.txt` | `fastapi`, `pandas`, `numpy` (runtime only) | Vercel's function bundle, which must stay under the 250 MB unzipped limit |
| `requirements-dev.txt` | `requirements.txt` plus `pytest`, `httpx`, `uvicorn`, `scikit-learn` | your machine, the test suite, the TF-IDF option |

### Troubleshooting

| Symptom | Fix |
|---|---|
| `python3.12: command not found` | Use whatever runs Python 3.10+ for you: `python -m venv .venv` or `py -3 -m venv .venv`. |
| PowerShell: *"running scripts is disabled on this system"* | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Command Prompt and `.venv\Scripts\activate.bat`. |
| `uvicorn: command not found` or `ModuleNotFoundError: fastapi` | The venv isn't activated, or only `requirements.txt` was installed. Activate it and run `pip install -r requirements-dev.txt`. |
| Port 8000 already in use | Set a different port: `PORT=8010 python dev.py` (macOS/Linux) or `set PORT=8010 && python dev.py` (Windows Command Prompt). |
| VS Code uses the wrong Python | `Ctrl/Cmd + Shift + P` → **Python: Select Interpreter** → pick the one inside `.venv`. |

---

## Running LogLens

### Local development

```bash
python dev.py
```

Open <http://127.0.0.1:8000>. `dev.py` runs the same FastAPI app that Vercel runs **and** serves `public/` as static files, so the frontend and API share one origin exactly as they do in production. It reads `HOST` and `PORT` from the environment (defaults: `127.0.0.1` and `8000`), for example `HOST=0.0.0.0` inside a container.

### Closest to production (Vercel CLI)

```bash
vercel dev
```

This serves `public/` statically and `api/index.py` as a function, so use it when checking rewrites, headers or the Python runtime.

### Using the app

1. **Pick a theme** with the ☀/☾ toggle in the top bar. It follows your OS setting until you choose one.
2. **Load logs** (sidebar, step 1) in any of three ways:
   - **📂 Load 10K sample log**: the bundled 10,000-line demo, the fastest way to see it work.
   - **Upload** a `.log`, `.txt`, `.text` or `.out` file (up to 4 MB on the hosted site).
   - **Paste** lines into the text box and click **Analyse pasted text**.
3. **Read the results** (main pane):
   - the **banner**: `N lines → K incidents (+B background noise groups)` and how long the analysis took;
   - the **KPI strip**: lines in file, parsed, skipped, lines at the chosen severity, services, and the time span covered by the log itself (not processing time);
   - the **⚡ root-cause trigger and cascade strip**: the earliest group with a clear onset, with knock-ons listed as `+18 s`, `+40 s`, … after it;
   - the **timeline**: lines per time bucket, coloured by incident, with a dashed line at the trigger onset;
   - the **ranked incident cards**: template, impact ring, role badge (⚡ trigger · ↳ knock-on · 〰 background), first/last seen, services, count, growth, sparkline, and tabs for the sample raw line, score breakdown and all raw lines, plus a per-incident `.log` download;
   - **All groups as a table / CSV export** and **Parsing details** at the bottom.
4. **Filter and sort** with the role pills, template/service search, service multi-select and sort menu. These work in the browser on the returned incidents; **Incident cards to show** limits how many render.
5. **Tune** (sidebar, step 2): minimum severity (default `WARN`), grouping method, similarity threshold, knock-on window, card count and score weights. Each server-side change re-runs the analysis after a short debounce, cancelling any request still in flight.

Templates use placeholders: `<NUM>`, `<IP>`, `<DUR>`, `<UUID>`, `<PATH>`, … are inserted by the normaliser, and `<*>` marks a position that Drain found to vary between lines of the same group.

### Other commands

```bash
python -m pytest -q                                     # run all 45 tests
python generate_sample_log.py                           # regenerate sample_logs/sample.log (10,000 lines, seed 42)
python generate_sample_log.py --lines 50000 --seed 7 --out big.log
```

After regenerating the sample, copy it to `public/sample_logs/sample.log` so the hosted "Load 10K sample" button serves the new file.

---

## API reference

Base URL: `https://loglens-byteforce.vercel.app`. All responses are JSON, and the API is stateless.

### `GET /api/health`

```bash
curl https://loglens-byteforce.vercel.app/api/health
```

```json
{ "status": "ok" }
```

### `POST /api/analyze`

| Field | Type | Default | Notes |
|---|---|---|---|
| `text` | string | `""` | Raw log text. Max **4,000,000 bytes**; larger bodies get `413`. |
| `min_severity` | `"WARN"` \| `"ERROR"` \| `"INFO"` \| `"DEBUG"` | `"WARN"` | Lines below this level are counted but not grouped. |
| `method` | `"drain"` \| `"tfidf"` | `"drain"` | `"tfidf"` returns `400` when scikit-learn is not installed (the hosted build). |
| `similarity` | float, 0.3–0.9 | `0.5` | Higher means stricter grouping. |
| `knock_on_minutes` | int, 1–30 | `5` | Window after the trigger in which other groups count as knock-ons. |
| `weights` | object | `{"count":0.30,"severity":0.25,"services":0.20,"growth":0.15,"start":0.10}` | Each value 0–1. |

```bash
curl -X POST https://loglens-byteforce.vercel.app/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text":"2026-10-09 10:05:00 ERROR [database] Connection refused\n2026-10-09 10:05:20 ERROR [web] Login failed: database unavailable\n2026-10-09 10:05:25 ERROR [web] Login failed: database unavailable","min_severity":"WARN"}'
```

Response (abridged):

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
| `no_timestamps` | Nothing parseable. `stats.skipped_samples` lists the first offending lines. |
| `no_severity_lines` | Lines were parsed, but none at or above `min_severity`. |

Other status codes: `413` (payload over 4 MB), `422` (validation error), `400` (TF-IDF requested without scikit-learn), and `500` (unexpected error, always returned as JSON `{"detail": "..."}`).

---

## Deployment

The repo is configured for Vercel out of the box. `vercel.json` rewrites `/api/(.*)` to the `api/index.py` function, `public/` is served as static hosting, and `.python-version` pins Python 3.12. There is **no build step**, no environment variables, no secrets and no database.

### Deploy from GitHub

1. Push the repository to GitHub.
2. Go to <https://vercel.com/new> and **import** the repository.
3. Leave **Framework Preset** on **Other**, and leave Build Command, Output Directory, Install Command and Root Directory at their defaults.
4. Click **Deploy**.

Vercel installs `requirements.txt`, bundles `api/index.py` with `loglens/`, serves `public/`, and applies the rewrites and cache headers from `vercel.json`. Every later push to the production branch redeploys automatically, and other branches get preview URLs. The first build takes a couple of minutes because of pandas and NumPy.

### Deploy with the CLI

```bash
npm i -g vercel
vercel            # preview deployment
vercel --prod     # production deployment
```

### Why TF-IDF is off in the hosted build

scikit-learn and scipy are roughly 150 MB on their own. Together with pandas and NumPy they would push the function past Vercel's 250 MB unzipped limit. The hosted site therefore shows the TF-IDF option as disabled ("Available in local/dev install only"), and the API returns `400` if it is requested anyway. Install `requirements-dev.txt` and run locally to use it.

---

## Checking that it works

Every test input has a **known answer**, so "working" just means the app recovers the story that was planted in the log.

### 1. The sample log has an answer key (30 seconds)

The demo log is generated by `generate_sample_log.py`: an hour of normal traffic, four harmless warnings that were there all along, and at **02:52:00** the primary database behind `payment-svc` starts timing out, which breaks seven other things over the next four minutes. Click **📂 Load 10K sample log** and compare:

| You should see | Meaning |
|---|---|
| Banner: **10,000 lines → 8 incidents (+4 background noise groups)** | 3,469 WARN+ lines collapsed into 12 groups |
| ⚡ Likely trigger: **payment-svc** · `Database connection timeout after <DUR> …` · first seen **02:52:01** | the planted root cause was found |
| Knock-ons at roughly **+18 s, +26 s, +40 s, +69 s, +1.6 min, +3 min, +4 min** across `checkout-svc`, `api-gateway`, `notification-svc`, `inventory-svc` | the planted cascade was found, in order |
| Background: invalid JWT, cache miss, slow query, SMTP retry | old noise was not mistaken for the incident |
| Parsed 9,994 · 4 continuation · 2 skipped | the deliberately broken lines did not break anything |

### 2. Write your own story (2 minutes)

Click **✨ Try 22-line mini story**, or paste the block below into the sidebar and press **Analyse pasted text**. The planted story: a backup job has been nagging about disk space all along; at 10:05:00 the **database** goes down; 20 seconds later the **web** app starts failing logins because of it.

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
- **database**: ⚡ likely trigger (8 lines);
- **web**: ↳ probable knock-on, **+20 s** after the trigger (7 lines);
- **backup-job**: 〰 background noise (5 lines). 8 + 7 + 5 = 20, nothing lost.

"12 distinct messages → 3 groups" is the no-rules requirement made visible: `attempt 1…8` and `user 1041…7781` were recognised as the same message without anyone telling the tool that attempt numbers and user IDs don't matter.

### 3. Break it on purpose

| Do this | Expected |
|---|---|
| Move every `[database]` line 3 minutes later, so the web app fails *first* | the trigger flips to **web**; database becomes "knock-on (+3 min)" |
| Delete the dates and times | a message saying no lines with a recognisable timestamp were found, with no crash |
| Paste something that isn't a log at all (a crash dump, a poem) | the same message |
| `python -m pytest -q` | `45 passed` |

---

## How it works under the hood

### Ingest: be tolerant, never crash

Each line is scanned for the earliest timestamp of any supported format. Header tokens after it (`[payment-svc]`, `ERROR`, `level=warn`, `com.acme.DbPool -`, …) are peeled off one by one, and whatever remains is the message. Lines with no timestamp are attached to the previous record if they look like a stack trace (indented, `at …`, `Caused by:`), and otherwise skipped and counted. Severities are normalised to `TRACE / DEBUG / INFO / WARN / ERROR / CRITICAL`, and timestamps with zone information are converted to UTC.

### Group: placeholders + Drain

Variable fragments are replaced first: `5000ms → <DUR>`, `10.0.3.17:5432 → <IP>`, `/v1/charge → <PATH>`, `98765 → <NUM>`, plus UUIDs, hex hashes, e-mails and byte sizes. Short integers (3 digits or fewer) are deliberately kept so that Drain can decide: they become `<*>` where they vary (`attempt 3`) and stay where they are constant (`502 Bad Gateway`). Normalisation alone typically collapses 10,000 lines to a few hundred distinct strings.

Those strings are then fed, most frequent first, into **Drain**: a prefix tree keyed by token count and the first tokens, with a token-wise similarity test at the leaves. A message joins the most similar template if at least 50 % of positions match (adjustable with the similarity slider), and positions that differ become `<*>`.

The TF-IDF alternative uses binary token-presence vectors (plain IDF would up-weight exactly the one-off tokens we want to ignore, and tokens seen in only one line are dropped) and average-linkage agglomerative clustering on cosine distance, with a majority-vote template per cluster.

### Rank: five explainable factors

| Factor | Default weight | Normalised how |
|---|---|---|
| Occurrences | 0.30 | `log(1+count) / log(1+max count)` |
| Severity | 0.25 | ½ max level + ½ mean level (`WARN .5, ERROR .8, CRITICAL 1`) |
| Services affected | 0.20 | `services in group / services in log` |
| Growth | 0.15 | rate in the recent window (¼ of the span, clamped to 1–10 min) ÷ rate before it, log-scaled, capped at ×20 |
| Early start | 0.10 | earlier onset scores higher; steady noise with no onset gets a neutral 0.5 |

Score = Σ weight × factor ÷ Σ weights × 100. The weights are sliders, and every card shows the breakdown.

### Explain: trigger, knock-on, background

A group has a **clear onset** when a long silence (at least max(60 s, 5 % of the log's span)) is followed by dense repeats (silence ≥ 3× the group's 90th-percentile gap). Groups already logging steadily when the file begins are **background noise**, unless they spike later (more than 4× their median per-minute rate), in which case the spike is their onset.

- **Likely trigger** = the group with a clear onset that started earliest (ties go to the higher score).
- **Probable knock-on** = any group whose onset falls within the knock-on window (default 5 min) after the trigger.
- If *no* group has a clear onset (for example, the file covers only the incident), LogLens falls back to the literal rule, the earliest-starting group, and says so on the card.

---

## Limitations

This is a hackathon prototype. These parts are not done:

**Input formats**

- **No timestamps, no analysis.** Every line needs a recognisable wall-clock timestamp. There is no fallback to line order, and relative counters such as `dmesg`'s `[ 1234.567890]` are skipped. Crash dumps, build logs and plain console output produce the "no recognisable timestamp" message.
- **JSON logs are not parsed as JSON.** The timestamp and level inside a JSON line are usually picked up, but the message shows a raw JSON fragment and the `service` field is missed.
- **Service detection only knows common layouts**: `[svc]`, `svc:`, `service=…`, `logger -`, the syslog program name and docker-compose prefixes. A plain `ERROR api something happened` is parsed as service `unknown`, and a Java thread name in brackets can occasionally be mistaken for a service.
- **Lines with no severity word are treated as INFO**, so the default `WARN` floor hides them. Lower the floor to see them.
- **Syslog timestamps carry no year**, so the current year is assumed, and a file that crosses New Year will be mis-ordered.
- **Stack-trace lines are used for display and download only.** Their text is not used for grouping, so two different exceptions that share the same first line land in the same group.

**Grouping and ranking**

- **Causality is temporal, not proven.** "Likely trigger" means *earliest clear onset*, and "knock-on" means *started shortly after*. Two unrelated incidents that begin within the window will be linked, and clock skew between hosts will mislead it. It is a strong first hint for triage, not a dependency graph.
- **Small inputs rarely have a clear onset.** A few dozen lines per group is the practical minimum. LogLens then falls back to earliest-group-first and says so, but the trigger call is weaker.
- **Drain is greedy and order-dependent.** Short messages with different meanings but the same shape can merge at the default threshold, and raising the similarity slider splits them. Depth and thresholds are fixed defaults, with no automatic tuning.
- **Growth is relative to the file's own window.** A log that ends mid-incident shows "exploding" growth, and one that covers hours after recovery shows decay. Both are correct but easy to misread.
- **No feedback loop.** You cannot tell LogLens that two groups are the same or that a group is not the trigger and have it remember.

**Theming**

- **The wipe animation depends on the browser.** The View Transitions API is available in current Chrome, Edge and Safari. Firefox gets the simpler sheet-sweep fallback. The theme itself works everywhere; only the animation differs.
- **The transition can't be interrupted.** Toggling again during the roughly 0.6 s sweep is ignored rather than reversing it.
- **One secondary text colour is low-contrast in light mode.** `--ll-muted-3` (`#94A3B8` on white, about 2.6:1) is used for KPI subtitles, table notes and metric labels, and it falls below the WCAG 3:1 minimum for non-text and large text and well below 4.5:1 for body text. The dark-mode value passes. Darkening that one token in the light palette would fix it.
- **The Team dialog's per-person accent gradients are fixed colours**, not theme tokens, so they look the same in both themes.

**Product**

- **4 MB per request on the hosted site.** This comes from Vercel's request body limit (about 4.5 MB). LogLens rejects larger input with a clear message instead of failing mid-upload. The 10K sample is roughly 1.3 MB, well inside the limit. For bigger files, split them and analyse the parts, or run locally.
- **TF-IDF grouping is disabled on the hosted site** (see [Why TF-IDF is off in the hosted build](#why-tf-idf-is-off-in-the-hosted-build)). Drain is the default and the only engine online.
- **Stateless by design.** Nothing is written to disk, and there is no database, session or cache between requests. Downloads (the incidents `.csv` and each group's `.log`) are generated in the browser.
- **The API is public and unauthenticated**, so do not send confidential logs to the public deployment.
- **Cold starts.** The first request after the site has been idle can take a second or two while the function boots. Warm analyses of the 10K sample take about 0.3 s.
- **Single file, in memory.** Measured at 10,000 lines in ~0.3 s and 100,000 lines in ~1.5 s locally. There is no streaming or live tail, no multi-file analysis, and no correlation across files or days.
- **Test coverage.** The 45 automated tests cover the pipeline and the HTTP API. The frontend was tested manually on a local machine, and the repo has no CI workflows.
- **Not evaluated on non-English logs**, or on real-world logs beyond a handful of formats we tried. The demo file is synthetic.
- **No integrations.** No Slack or PagerDuty alerts, scheduled runs or authentication.

**Next on the list:** a line-order / relative-timestamp fallback, proper JSON-line parsing, smarter service discovery, stack-trace-aware grouping, and a merge/split feedback control on the incident cards.

---

## Project layout

```text
api/index.py               FastAPI app (`app`): validation and JSON only; Vercel entrypoint
loglens/__init__.py        package exports
loglens/parser.py          tolerant log parsing -> pandas DataFrame
loglens/cluster.py         normalisation + Drain template miner + optional TF-IDF
loglens/rank.py            impact scoring, score breakdown, trigger / knock-on roles
loglens/service.py         analyze(): runs the pipeline, returns JSON-safe dicts
public/index.html          single-page frontend shell
public/style.css           design system: theme tokens (light + dark), cards, badges, dialogs
public/app.js              UI logic: fetch/debounce/abort, cards, filters, charts, CSV, theme toggle
public/assets/team/*.jpg   team avatars used by the Team ByteForce dialog
public/sample_logs/sample.log   10,000-line demo served statically
generate_sample_log.py     seeded demo-log generator (dev tool, not deployed)
sample_logs/sample.log     source copy of the demo log
tests/test_pipeline.py     23 pipeline tests
tests/test_api.py          22 API tests
dev.py                     local launcher: API + public/ on one origin (not deployed)
requirements.txt           runtime only: fastapi, pandas, numpy
requirements-dev.txt       requirements.txt + pytest, httpx, uvicorn, scikit-learn
vercel.json                rewrites, function config, cache headers
.python-version            3.12
.vercelignore              keeps tests and dev files out of the deployment
```
