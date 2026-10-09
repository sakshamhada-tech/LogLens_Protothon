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

**LogLens** turns a raw log file into a handful of ranked, explained incidents — which error groups exist, how big each one is, when each started, which services it hit and which one most likely set the others off. It runs locally with one command, needs no internet, no API keys and no hand-written rules about what an error "looks like".

On the bundled 10,000-line demo log it reports **8 incidents (+4 background-noise groups)** in about **0.3 seconds**, names the likely trigger (database timeouts in `payment-svc`) and marks the seven groups that started within minutes of it as probable knock-on effects.

---

## Contents

1. [Problem statement](#problem-statement)
2. [Team](#team)
3. [What we built](#what-we-built)
4. [Why we built it this way](#why-we-built-it-this-way)
5. [Installation](#installation)
6. [Running LogLens](#running-loglens)
7. [Checking that it works](#checking-that-it-works)
8. [How it works under the hood](#how-it-works-under-the-hood)
9. [Unfinished features and known limitations](#unfinished-features-and-known-limitations)
10. [Project layout](#project-layout)

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

LogLens is a single-page **Streamlit** web app backed by a three-stage Python pipeline. Everything runs on the user's machine.

```text
 raw log text ──> parser.py ──> cluster.py ──> rank.py ──> app.py (Streamlit UI)
 (paste/upload)   timestamp,     normalise +    impact score,   banner, timeline,
                  level,         Drain          trigger /       ranked incident
                  service,       templates      knock-on /      cards, breakdown,
                  message        (no rules)     background      raw lines, CSV
```

| Piece | File | What it does |
|---|---|---|
| **Ingest** | `parser.py` | Reads each line tolerantly: finds a timestamp (ISO-8601 in several spellings, syslog `Oct  9 03:00:01`, Apache/CLF, Unix epoch), a severity (`ERROR`, `[warn]`, `level=error`, …) and a service name (`[payment-svc]`, `payment-svc:`, `service=…`, `logger -`, syslog program, docker-compose prefix), and keeps the rest as the message. Stack-trace continuation lines are attached to the line above; anything unparseable is counted and skipped, never fatal. |
| **Group** | `cluster.py` | Replaces variable fragments with placeholders (numbers, IDs, UUIDs, IPs, hex, durations, sizes, paths, URLs, e-mails) and then mines message *templates* with a from-scratch implementation of **Drain** (He et al., 2017). An alternative **TF-IDF + agglomerative clustering** grouping is one click away. Nothing in the code knows what any specific error looks like. |
| **Rank** | `rank.py` | Scores every group 0–100 from five explainable factors — occurrences, severity, services affected, growth and start time — and assigns a role: **trigger**, **knock-on**, **background** or **independent**. The per-factor breakdown is shown on every card and the rows add up to the score. |
| **Explain / UI** | `app.py` | Summary banner ("10,000 lines → 8 incidents"), parse statistics, likely-trigger callout, overall timeline coloured by incident, ranked incident cards (first/last seen, services, count, growth, sparkline, sample raw line, score breakdown), expandable raw-lines view, downloads (`.csv` of incidents, `.log` of any group's lines). Sidebar controls for severity floor, grouping method, similarity threshold, knock-on window and score weights. |
| **Demo data** | `generate_sample_log.py`, `sample_logs/sample.log` | Seeded generator for a realistic 10,000-line, 60-minute log from five services in three different line formats, with normal traffic, steady background noise, deliberately malformed lines and a scripted cascade (DB timeouts → upstream timeouts → 502s → queue saturation → publish failures → circuit breaker → expired reservations). |
| **Tests** | `tests/test_pipeline.py` | 23 pytest cases: parser formats, normaliser, Drain and TF-IDF grouping, scoring, and an end-to-end check that the planted root cause is found. |

**Stack:** Python 3.11 · Streamlit · pandas · NumPy · scikit-learn · Altair. No paid APIs, no external services, works offline.

---

## Why we built it this way

**Why no rules?** Regex/keyword rules only catch errors someone has already seen and written a rule for — exactly the ones that *don't* page you at 3 a.m. LogLens instead learns the message templates from the file itself: lines that differ only in IDs, numbers, hosts or durations collapse into one group, whatever the error text happens to be.

**Why Drain?** It is the standard algorithm for online log template mining: a fixed-depth prefix tree keyed by token count and leading tokens with a similarity test at the leaves. It is linear in the number of lines, needs no training data, runs offline and produces human-readable templates (`Database connection timeout after <DUR> (pool=<*>, host=<IP>)`) instead of opaque cluster numbers. The TF-IDF/agglomerative option exists as a second opinion and because judges may ask "why not classic clustering?".

**Why heuristics for ranking instead of a model?** An on-call engineer needs to *trust* the ordering. Five named factors with visible weights, a breakdown table on every card and sliders to change the weights are something a person can argue with; a learned score is not. The same goes for the trigger/knock-on logic: it is explained in plain words on the card ("earliest group with a clear onset", "started 18 s after the trigger in checkout-svc").

**Why Streamlit?** One file, one command (`streamlit run app.py`), no front-end build, runs on a laptop with no network — which is where a 3 a.m. investigation actually happens.

**Why a generated demo log?** Real incident logs are confidential. A seeded generator gives a realistic multi-service, multi-format file with a *known* answer, which means the result can be verified rather than just admired (see [Checking that it works](#checking-that-it-works)).

---

## Installation

### Prerequisites

- **Python 3.11** (3.10 or newer should work; everything was developed and tested on 3.11)
- **pip** (ships with Python) and **git**
- Any OS — Windows, macOS or Linux. No GPU, no Docker, no internet after `pip install`.

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

(Or download the ZIP from GitHub and open a terminal inside the extracted folder.)

### 2. Create and activate a virtual environment

**Windows — PowerShell**

```powershell
py -3.11 -m venv .venv          # or:  python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows — Command Prompt**

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt should now start with `(.venv)`.

### 3. Install the dependencies

```bash
pip install -r requirements.txt
```

This pulls Streamlit, pandas, NumPy, scikit-learn, Altair and pytest (a few hundred MB on disk). It is the only step that needs internet.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `python3.11: command not found` / "no such file or directory" | You don't have a 3.11 launcher by that name. Use whatever runs Python 3.10+ for you: `python -m venv .venv`, `python3 -m venv .venv` or `py -3 -m venv .venv`. |
| PowerShell: *"running scripts is disabled on this system"* | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Command Prompt and `.venv\Scripts\activate.bat`. |
| `streamlit: command not found` | The venv isn't activated. Activate it (step 2) or run `python -m streamlit run app.py`. |
| Port 8501 already in use | `streamlit run app.py --server.port 8502` |
| Streamlit asks for an e-mail on first start | Just press **Enter**. |
| VS Code uses the wrong Python | `Ctrl/Cmd + Shift + P` → **Python: Select Interpreter** → pick the one inside `.venv`. |

---

## Running LogLens

```bash
streamlit run app.py
```

A browser tab opens at <http://localhost:8501> (if it doesn't, open the URL printed in the terminal). Stop the app with `Ctrl + C` in the terminal.

### Using the app

1. **Load logs** (sidebar, step 1) in any of three ways:
   - **📂 Load sample log** — the bundled 10,000-line demo (fastest way to see it work);
   - **Upload** a `.log` / `.txt` / `.out` file;
   - **Paste** lines into the text box and click **Analyse pasted text**.
2. **Read the results** (main pane):
   - the green **banner** — `N lines → K incidents (+B background noise groups)` and how long the analysis took;
   - the **metrics row** — lines in file, parsed, skipped, lines at the chosen severity, services, and **"Log covers"**, which is the period between the first and last timestamp *inside the log* (e.g. 60 min), not the processing time;
   - the **⚡ likely trigger** callout — the earliest group with a clear onset, with its knock-ons listed as `+18 s`, `+40 s`, … after it;
   - the **timeline** — lines per time bucket, coloured by incident;
   - the **ranked incident cards** — template, impact score, role badge (⚡ trigger · ↳ knock-on · 〰 background), first/last seen, services, count, growth, a sparkline, a sample raw line, the score breakdown, and an expander with the raw lines and a download button;
   - **Download incidents (.csv)** at the bottom for the summary table.
3. **Tune** (sidebar, step 2) if needed: minimum severity (default `WARN`), grouping method, similarity threshold (raise it if two different errors were merged, lower it if one error was split), knock-on window, number of cards, score weights.

Templates use placeholders: `<NUM>`, `<IP>`, `<DUR>`, `<UUID>`, `<PATH>`, … are inserted by the normaliser, and `<*>` marks a position that Drain found to vary between lines of the same group.

### Other commands

```bash
python -m pytest -q                                     # run the 23 tests
python generate_sample_log.py                           # regenerate sample_logs/sample.log (10,000 lines, seed 42)
python generate_sample_log.py --lines 50000 --seed 7 --out big.log   # a different / bigger demo file
```

---

## Checking that it works

You don't need to be a logging expert to verify LogLens: every test input has a **known answer**, so "working" just means the app recovers the story that was planted in the log.

### 1. The sample log has an answer key (30 seconds)

The demo log is generated from a script (described at the top of `generate_sample_log.py`): an hour of normal traffic, four harmless warnings that were there all along, and at **02:52:00** the primary database behind `payment-svc` starts timing out, which breaks seven other things over the next four minutes. Click **📂 Load sample log** and compare:

| You should see | Meaning |
|---|---|
| Banner: **10,000 lines → 8 incidents (+4 background noise groups)** | 3,469 WARN+ lines collapsed into 12 groups |
| ⚡ Likely trigger: **payment-svc** · `Database connection timeout after <DUR> …` · first seen **02:52:01** | the planted root cause was found |
| Knock-ons at roughly **+18 s, +26 s, +40 s, +69 s, +1.6 min, +3 min, +4 min** across `checkout-svc`, `api-gateway`, `notification-svc`, `inventory-svc` | the planted cascade was found, in order |
| Background: invalid JWT, cache miss, slow query, SMTP retry | old noise was not mistaken for the incident |
| Parsed 9,994 · 4 continuation · 2 skipped | the deliberately broken lines did not break anything |

### 2. Write your own story (2 minutes)

Paste the block below into the sidebar and click **Analyse pasted text**. The story *you* planted: a backup job has been nagging about disk space all along; at 10:05:00 the **database** goes down; 20 seconds later the **web** app starts failing logins because of it.

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
| `python -m pytest -q` | `23 passed` |

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
- **Nothing is saved.** No history between runs, no login, no sharing — only the `.csv` / `.log` downloads.
- **No integrations** — no Slack/PagerDuty alerts, no scheduled runs, no API.
- **UI is not covered by the automated tests.** The 23 tests cover the parsing/grouping/ranking pipeline; the Streamlit UI was exercised by hand and with Streamlit's `AppTest` during development only.
- **Not packaged** — no Dockerfile, no PyPI package, no hosted demo; it runs from a clone.
- **Not evaluated on non-English logs** or on logs from the wild beyond a handful of formats we tried; the demo file is synthetic.

What we would build next, in order: a line-order / relative-timestamp fallback, proper JSON-line parsing, smarter service discovery, stack-trace-aware grouping, and a merge/split feedback control on the incident cards.

---

## Project layout

```text
app.py                  Streamlit UI (single command: streamlit run app.py)
parser.py               tolerant log parsing -> pandas DataFrame
cluster.py              normalisation + Drain template miner + TF-IDF fallback
rank.py                 impact scoring, score breakdown, trigger / knock-on roles
generate_sample_log.py  seeded demo-log generator
sample_logs/sample.log  10,000-line demo (5 services, one root cause, cascading failures)
tests/test_pipeline.py  pytest suite (23 cases)
requirements.txt        streamlit, pandas, numpy, scikit-learn, altair, pytest
```
