/* ==========================================================================
   LogLens — frontend. Vanilla JS, no build step.
   All log-derived strings are inserted with textContent or escaped with
   escapeHtml() before being placed in markup. Log content is untrusted.
   ========================================================================== */
(function () {
  "use strict";

  // ------------------------------------------------------------------ state
  const API = "/api/analyze";

  const PALETTE = [
    "#E11D48", "#EA580C", "#4F46E5", "#059669", "#7C3AED",
    "#0284C7", "#DB2777", "#0D9488", "#D97706", "#64748B",
  ];
  const OTHER_COLOUR_TOKEN = "--ll-border-strong";
  const OTHER_COLOUR_FALLBACK = "#CBD5E1";
  const MAX_UPLOAD_BYTES = 4 * 1000 * 1000; // keep in sync with api MAX_TEXT_BYTES

  const ROLE_BADGE = {
    trigger: "⚡ LIKELY TRIGGER",
    "knock-on": "↳ probable knock-on",
    independent: "◦ independent",
    background: "〰 background noise",
  };
  const ROLE_CLASS = {
    trigger: "ll-role-trigger",
    "knock-on": "ll-role-knock",
    independent: "ll-role-ind",
    background: "ll-role-bg",
  };
  const PLACEHOLDER_RE = /&lt;(DUR|IP|NUM|UUID|PATH|HEX|URL|EMAIL|SIZE|\*)&gt;/g;

  const LOGO_SVG = `<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" width="38" height="38" style="flex-shrink:0;filter:drop-shadow(0 2px 6px rgba(79,70,229,0.22));" aria-hidden="true">
  <defs>
    <linearGradient id="llGrad" x1="2" y1="2" x2="38" y2="38" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#4F46E5"/><stop offset="55%" stop-color="#6366F1"/><stop offset="100%" stop-color="#0EA5E9"/>
    </linearGradient>
    <linearGradient id="llInner" x1="10" y1="10" x2="28" y2="28" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.98"/><stop offset="100%" stop-color="#E0E7FF" stop-opacity="0.92"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="36" height="36" rx="11" fill="url(#llGrad)"/>
  <circle cx="18.5" cy="18.5" r="8.5" stroke="url(#llInner)" stroke-width="2.4" fill="rgba(255,255,255,0.10)"/>
  <rect x="13.5" y="18.5" width="2.2" height="4.2" rx="1.1" fill="#FFFFFF"/>
  <rect x="17.4" y="14.2" width="2.2" height="8.5" rx="1.1" fill="#FFFFFF"/>
  <rect x="21.3" y="16.4" width="2.2" height="6.3" rx="1.1" fill="#BAE6FD"/>
  <path d="M25.2 25.2L30.5 30.5" stroke="#FFFFFF" stroke-width="2.8" stroke-linecap="round"/>
  <circle cx="29.5" cy="10.5" r="2.1" fill="#38BDF8"/>
</svg>`;

  const MINI_DEMO_LOG = `2026-10-09 10:00:05 WARN [backup-job] Disk usage at 81% on /var/backups
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
2026-10-09 10:08:05 WARN [backup-job] Disk usage at 83% on /var/backups`;

  const TEAM_MEMBERS = [
    {
      name: "Anurag Tiwari",
      initials: "AT",
      usn: "2392608004",
      photo: "anurag.jpg",
      role: "Team Leader · UI/UX Designer",
      gradient: "linear-gradient(135deg, #4F46E5, #7C3AED)",
      pill_bg: "#EEF2FF",
      pill_fg: "#4338CA",
      contribution:
        "Led Team ByteForce and crafted the complete UI/UX architecture, light-mode visual system, and interactive experience for LogLens.",
      github: "https://github.com/Anurag-tiwaricodes",
      linkedin: "https://www.linkedin.com/in/anurag-tiwari-2b1913427/",
    },
    {
      name: "Saksham Hada",
      initials: "SH",
      usn: "2392608017",
      photo: "saksham.jpg",
      role: "Log Parsing & Data Ingestion",
      gradient: "linear-gradient(135deg, #059669, #0D9488)",
      pill_bg: "#ECFDF5",
      pill_fg: "#047857",
      contribution:
        "Engineered the tolerant log parsing and data ingestion pipeline (parser.py), handling multi-format timestamps, severities, services, and stack-trace continuations.",
      github: "https://github.com/sakshamhada-tech",
      linkedin: "https://www.linkedin.com/in/sakshamhada/",
    },
    {
      name: "Shriyam Gupta",
      initials: "SG",
      usn: "2392608086",
      photo: "shriyam.jpg",
      role: "Clustering & Template Mining Engine",
      gradient: "linear-gradient(135deg, #D97706, #EA580C)",
      pill_bg: "#FFFBEB",
      pill_fg: "#B45309",
      contribution:
        "Built the rule-free clustering and Drain template mining engine (cluster.py), including placeholder normalisation and TF-IDF agglomerative fallback.",
      github: "https://github.com/shriyamgupta14-sys",
      linkedin: "https://www.linkedin.com/in/shriyam-gupta-957ab5356/",
    },
    {
      name: "Ansh Raj",
      initials: "AR",
      usn: "2392608082",
      photo: "ansh.jpg",
      role: "Impact Scoring, Root-Cause Logic & Testing",
      gradient: "linear-gradient(135deg, #0284C7, #2563EB)",
      pill_bg: "#F0F9FF",
      pill_fg: "#0369A1",
      contribution:
        "Developed the 5-factor impact scoring and trigger/knock-on root-cause logic (rank.py), plus synthetic log generation and the 23-case automated pytest suite.",
      github: "https://github.com/anshraj3060",
      linkedin: "https://www.linkedin.com/in/ansh-raj-86a795321/",
    },
    {
      name: "Jatin Alwani",
      initials: "JA",
      usn: "2392608141",
      photo: "jatin.jpg",
      role: "Debugging, Documentation & Product Strategy",
      gradient: "linear-gradient(135deg, #E11D48, #DB2777)",
      pill_bg: "#FFF1F2",
      pill_fg: "#BE123C",
      contribution:
        "Led end-to-end debugging across the LogLens pipeline, authored the technical documentation (README.md), and shaped overall product strategy.",
      github: "https://github.com/jatinalwani8",
      linkedin: "https://www.linkedin.com/in/jatin-alwani-0b3489420/",
    },
    {
      name: "Rohitash Jangir",
      initials: "RJ",
      usn: "2392608048",
      photo: "rohitash.jpg",
      role: "Pitch Deck & Presentation",
      gradient: "linear-gradient(135deg, #7C3AED, #C026D3)",
      pill_bg: "#F5F3FF",
      pill_fg: "#6D28D9",
      contribution:
        "Created and structured the LogLens Pitch Deck (PPT/PDF), translating the technical pipeline into a clear 3 a.m. incident story.",
      github: "https://github.com/rohitjangir2310",
      linkedin: "https://www.linkedin.com/in/rohit-jangir-6926743b8/",
    },
  ];

  const W = {
    text: null,          // raw log text currently loaded
    name: null,          // display name of the source
    data: null,          // last successful /api/analyze response
    loading: false,
    error: null,         // {title, message, retry}
    requestId: 0,
    timer: null,
    controller: null,
    roleFilter: "All",
    search: "",
    sort: "Impact Score",
    services: [],
    teamIndex: 0,
    teamDialogOpen: false,
  };

  // --------------------------------------------------------------- helpers
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  /** Read a design token so inline styles follow the active theme. */
  function token(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback || "";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function num(n) {
    return Number(n || 0).toLocaleString("en-US");
  }

  function fmtDuration(seconds) {
    const s = Number(seconds) || 0;
    if (s < 60) return Math.round(s) + " s";
    if (s < 3600) return Math.round(s / 60) + " min";
    if (s < 86400) return (s / 3600).toFixed(1) + " h";
    return (s / 86400).toFixed(1) + " d";
  }

  function plural(n, word) {
    return num(n) + " " + word + (n === 1 ? "" : "s");
  }

  function fmtGrowth(row) {
    if (!row.count_earlier) return "new";
    return "×" + Number(row.growth_ratio || 0).toFixed(1);
  }

  function parseIso(iso) {
    if (!iso) return null;
    // Service returns naive ISO timestamps (UTC-normalised) — treat as UTC.
    const hasZone = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso);
    const d = new Date(hasZone ? iso : iso + "Z");
    return isNaN(d.getTime()) ? null : d;
  }

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  /** HH:MM:SS in UTC (matches the pipeline's UTC-normalised timestamps). */
  function fmtClock(iso) {
    const d = parseIso(iso);
    if (!d) return "—";
    return pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + ":" + pad(d.getUTCSeconds());
  }

  function fmtClockMs(iso) {
    const d = parseIso(iso);
    if (!d) return "—";
    return fmtClock(iso) + "." + String(d.getUTCMilliseconds()).padStart(3, "0");
  }

  function fmtDateClock(iso) {
    const d = parseIso(iso);
    if (!d) return "—";
    return (
      d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate()) +
      " " + fmtClock(iso)
    );
  }

  function secondsBetween(aIso, bIso) {
    const a = parseIso(aIso);
    const b = parseIso(bIso);
    if (!a || !b) return 0;
    return (b.getTime() - a.getTime()) / 1000;
  }

  /** Escape first, then wrap <PLACEHOLDER> tokens in chips (as app.py did). */
  function templateHtml(template) {
    return escapeHtml(template).replace(PLACEHOLDER_RE, function (m, token) {
      return '<span class="ll-chip">&lt;' + token + '&gt;</span>';
    });
  }

  function colourFor(clusterId) {
    const data = W.data;
    if (!data) return token(OTHER_COLOUR_TOKEN, OTHER_COLOUR_FALLBACK);
    const idx = data.incidents.findIndex((i) => i.cluster_id === clusterId);
    return idx >= 0 && idx < PALETTE.length ? PALETTE[idx] : token(OTHER_COLOUR_TOKEN, OTHER_COLOUR_FALLBACK);
  }

  function downloadBlob(filename, text, mime) {
    const blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  function csvCell(value) {
    const s = String(value == null ? "" : value);
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  // ---------------------------------------------------------------- charts
  function chartsAvailable() {
    return typeof window.vegaEmbed === "function";
  }

  function renderChart(host, spec) {
    if (!host) return;
    if (!chartsAvailable()) {
      host.innerHTML = "";
      host.appendChild(
        el("div", "chart-fallback",
          "Chart library unavailable (offline or blocked CDN). All figures and tables below still work.")
      );
      return;
    }
    try {
      window.vegaEmbed(host, spec, {
        actions: false,
        renderer: "canvas",
        config: { background: "transparent" },
      }).catch(function () {
        host.innerHTML = "";
        host.appendChild(el("div", "chart-fallback", "Chart could not be rendered for this dataset."));
      });
    } catch (err) {
      host.innerHTML = "";
      host.appendChild(el("div", "chart-fallback", "Chart could not be rendered for this dataset."));
    }
  }

  function timelineSpec(data) {
    const rows = data.timeline.map((r) => ({
      bucket: r.bucket,
      bucket_end: r.bucket_end,
      series: r.series,
      lines: r.lines,
      y0: r.y0,
      y1: r.y1,
    }));
    const incidents = data.incidents || [];
    const domain = incidents.slice(0, 10).map((i) => shortLabel(i));
    domain.push("Other groups");
    const range = incidents.slice(0, 10).map((i, idx) => PALETTE[idx % PALETTE.length]);
    range.push(token(OTHER_COLOUR_TOKEN, OTHER_COLOUR_FALLBACK));

    const layers = [
      {
        mark: { type: "rect", opacity: 0.92, cornerRadiusTopLeft: 2, cornerRadiusTopRight: 2 },
        encoding: {
          x: { field: "bucket", type: "temporal", title: null,
               axis: { format: "%H:%M", labelColor: token("--ll-muted-2", "#64748B"), grid: false } },
          x2: { field: "bucket_end" },
          y: {
            field: "y0", type: "quantitative", title: "lines per " + (data.window ? data.window.bucket_label : "bucket"),
            axis: { labelColor: token("--ll-muted-2", "#64748B"),
                    titleColor: token("--ll-muted", "#475569"),
                    gridColor: token("--ll-surface-3", "#F1F5F9") },
          },
          y2: { field: "y1" },
          color: {
            field: "series", type: "nominal",
            scale: { domain: domain, range: range },
            legend: { title: null, orient: "bottom", columns: 2, labelLimit: 320,
                    labelColor: token("--ll-ink-body", "#334155") },
          },
          tooltip: [
            { field: "bucket", type: "temporal", title: "Time", format: "%H:%M:%S" },
            { field: "series", type: "nominal", title: "Group" },
            { field: "lines", type: "quantitative", title: "Lines" },
          ],
        },
      },
    ];

    const trigger = (incidents.find((i) => i.role === "trigger") || {}).onset;
    if (trigger) {
      layers.push({
        data: { values: [{ t: trigger }] },
        mark: { type: "rule", color: token("--ll-trigger", "#E11D48"), strokeDash: [6, 4], size: 2 },
        encoding: { x: { field: "t", type: "temporal" } },
      });
      layers.push({
        data: { values: [{ t: trigger, label: "⚡ likely trigger" }] },
        mark: { type: "text", align: "left", dx: 5, dy: -2, color: token("--ll-trigger", "#E11D48"),
                fontSize: 11, fontWeight: "bold", baseline: "top" },
        encoding: {
          x: { field: "t", type: "temporal" },
          y: { value: 0 },
          text: { field: "label", type: "nominal" },
        },
      });
    }

    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: rows },
      layer: layers,
      width: "container",
      height: 300,
      autosize: { type: "fit", contains: "padding", resize: true },
    };
  }

  function sparklineSpec(points, colour, onset) {
    const values = points.map((p) => ({ bucket: p.t, lines: p.lines }));
    const layers = [
      {
        mark: {
          type: "area",
          interpolate: "step-after",
          color: colour,
          opacity: 0.28,
          line: { color: colour, strokeWidth: 1.8 },
        },
        encoding: {
          x: { field: "bucket", type: "temporal", axis: null },
          y: { field: "lines", type: "quantitative", axis: null },
          tooltip: [
            { field: "bucket", type: "temporal", title: "Time", format: "%H:%M:%S" },
            { field: "lines", type: "quantitative", title: "Lines" },
          ],
        },
      },
    ];
    if (onset) {
      layers.push({
        data: { values: [{ t: onset }] },
        mark: { type: "rule", color: token("--ll-trigger", "#E11D48"), strokeDash: [3, 3], opacity: 0.65 },
        encoding: { x: { field: "t", type: "temporal" } },
      });
    }
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: values },
      layer: layers,
      width: "container",
      height: 84,
      autosize: { type: "fit", contains: "padding", resize: true },
    };
  }

  function shortLabel(incident, width) {
    const text = "#" + incident.rank + " " + (incident.services[0] || "?") + ": " + incident.template;
    const limit = width || 48;
    return text.length <= limit ? text : text.slice(0, limit - 1) + "…";
  }

  // ---------------------------------------------------------------- sidebar
  function readControls() {
    const weights = {};
    ["count", "severity", "services", "growth", "start"].forEach((k) => {
      weights[k] = parseFloat($("#w-" + k).value);
    });
    const methodInput = document.querySelector('input[name="method"]:checked');
    return {
      text: W.text,
      min_severity: $("#min-severity").value,
      method: methodInput ? methodInput.value : "drain",
      similarity: parseFloat($("#similarity").value),
      knock_on_minutes: parseInt($("#knock-on").value, 10),
      weights: weights,
    };
  }

  function serverSignature() {
    const c = readControls();
    return JSON.stringify([c.min_severity, c.method, c.similarity, c.knock_on_minutes, c.weights]);
  }

  function setLoading(isLoading, label) {
    W.loading = isLoading;
    const strip = $("#loading-strip");
    strip.classList.toggle("show", isLoading);
    if (label) $("#loading-text").textContent = label;
    strip.setAttribute("aria-busy", isLoading ? "true" : "false");
  }

  function showError(title, message, retry) {
    W.error = { title, message, retry };
    const slot = $("#error-slot");
    slot.innerHTML = "";
    const box = el("div", "banner banner-error");
    box.setAttribute("role", "alert");
    const body = el("div");
    const strong = el("strong", null, title);
    body.appendChild(strong);
    body.appendChild(document.createTextNode(message || ""));
    box.appendChild(body);

    if (retry) {
      const actions = el("div", "banner-actions");
      const btn = el("button", "btn btn-sm", "Retry");
      btn.type = "button";
      btn.addEventListener("click", () => {
        clearError();
        analyse({ force: true });
      });
      actions.appendChild(btn);
      box.appendChild(actions);
    }
    slot.appendChild(box);
  }

  function clearError() {
    W.error = null;
    $("#error-slot").innerHTML = "";
  }

  // ------------------------------------------------------------ data loading
  function loadSource(text, name) {
    W.text = text;
    W.name = name;
    W.data = null;
    W.roleFilter = "All";
    W.search = "";
    W.services = [];
    clearError();
    analyse({ force: true });
  }

  function goHome() {
    if (W.controller) W.controller.abort();
    if (W.timer) clearTimeout(W.timer);
    W.text = null;
    W.name = null;
    W.data = null;
    W.services = [];
    W.search = "";
    W.roleFilter = "All";
    clearError();
    setLoading(false);
    render();
  }

  function analyse(opts) {
    if (!W.text) return;
    const options = opts || {};
    if (W.controller) W.controller.abort();
    if (W.timer) clearTimeout(W.timer);

    const run = function () {
      const payload = readControls();
      if (!payload.text) return;
      const controller = new AbortController();
      W.controller = controller;
      const requestId = ++W.requestId;
      setLoading(true, "Parsing and grouping logs…");
      clearError();

      fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })
        .then(async (resp) => {
          let body = null;
          try {
            body = await resp.json();
          } catch (e) {
            body = null;
          }
          if (!resp.ok) {
            const detail = body && body.detail
              ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail))
              : "The server returned HTTP " + resp.status + ".";
            throw new Error(detail);
          }
          return body;
        })
        .then((data) => {
          if (requestId !== W.requestId) return;
          W.data = data;
          W.error = null;
          W.services = W.services.filter((s) => {
            const all = allServices();
            return all.indexOf(s) !== -1;
          });
          setLoading(false);
          render();
        })
        .catch((err) => {
          if (err && err.name === "AbortError") return;
          if (requestId !== W.requestId) return;
          setLoading(false);
          const message =
            err && err.message === "Failed to fetch"
              ? "Could not reach the LogLens API. Check your connection, then retry."
              : err.message;
          showError("Analysis failed", message, true);
          if (!W.data) render();
        });
    };

    if (options.force) run();
    else W.timer = setTimeout(run, 300);
  }

  function queueReanalysis() {
    if (!W.text) return;
    analyse({ force: false });
  }

  // --------------------------------------------------------------- rendering
  function render() {
    renderFooter();
    const view = $("#view-slot");
    view.innerHTML = "";

    if (!W.text) {
      renderLanding(view);
      return;
    }
    if (!W.data) {
      if (!W.loading && !W.error) {
        view.appendChild(el("div", "chart-fallback", "Preparing analysis…"));
      }
      return;
    }
    renderResults(view, W.data);
  }

  function renderLanding(view) {
    const hero = el("div", "ll-hero ll-fade");
    hero.innerHTML =
      '<div class="ll-hero-badge">● Offline · Rule-Free · 10,000 Lines in ~0.3 s</div>' +
      "<h1>Find the signal in <span>10,000 log lines</span> at 3 a.m.</h1>" +
      "<p>LogLens collapses noisy raw logs into a handful of ranked incidents, pinpoints the likely " +
      "root-cause trigger, and traces cascading knock-on failures — completely locally.</p>" +
      '<div class="hero-ctas">' +
      '<button type="button" class="btn btn-primary btn-lg" id="hero-load-sample">▶ Load 10,000-Line Demo Log</button>' +
      '<button type="button" class="btn btn-lg" id="hero-load-mini">⚡ Try 22-Line Mini Cascade</button>' +
      "</div>";
    view.appendChild(hero);

    const steps = [
      ["01", "var(--ll-sev-info-line)", "var(--ll-sev-info-fg)", "Tolerant Ingest",
        "Extracts timestamps, severities & services across ISO, syslog, and Apache layouts without crashing on malformed lines."],
      ["02", "var(--ll-brand-soft)", "var(--ll-brand-ink)", "Rule-Free Grouping",
        "Masks IDs, IPs, durations & UUIDs, then runs Drain template mining to collapse thousands of lines into clean families."],
      ["03", "var(--ll-sev-warn-bg)", "var(--ll-sev-warn-fg)", "Transparent Ranking",
        "Scores every group 0–100 across 5 explainable factors with live-tunable weights and per-card point breakdowns."],
      ["04", "var(--ll-trigger-soft-2)", "var(--ll-trigger-ink)", "Trigger & Cascade",
        "Flags the earliest sharp onset as the likely trigger and links downstream services as timed knock-on effects."],
    ];
    const grid = el("div", "steps-grid");
    steps.forEach((s) => {
      const card = el("div", "ll-step-card ll-fade");
      card.innerHTML =
        '<div class="ll-step-num" style="background:' + s[1] + ";color:" + s[2] + ';">' + s[0] + "</div>" +
        '<div class="ll-step-title">' + escapeHtml(s[3]) + "</div>" +
        '<div class="ll-step-desc">' + escapeHtml(s[4]) + "</div>";
      grid.appendChild(card);
    });
    view.appendChild(grid);

    const loadSample = $("#hero-load-sample", view);
    if (loadSample) loadSample.addEventListener("click", loadSampleLog);
    const loadMini = $("#hero-load-mini", view);
    if (loadMini) loadMini.addEventListener("click", loadMiniStory);
  }

  function allServices() {
    const set = new Set();
    (W.data && W.data.incidents ? W.data.incidents : []).forEach((inc) => {
      inc.services.forEach((s) => set.add(s));
    });
    return Array.from(set).sort();
  }

  function renderResults(view, data) {
    if (data.error) {
      renderEmptyState(view, data);
      return;
    }
    const stats = data.stats;
    const incidents = data.incidents || [];
    const background = incidents.filter((i) => i.role === "background");
    const realIncidents = incidents.filter((i) => i.role !== "background");
    const trigger = incidents.find((i) => i.role === "trigger") || null;
    const knockOns = incidents
      .filter((i) => i.role === "knock-on")
      .sort((a, b) => (a.lag_s || 0) - (b.lag_s || 0));
    const minSev = $("#min-severity").value;
    const knockWindow = parseInt($("#knock-on").value, 10);

    // ---- summary banner
    const noisePct = (1 - realIncidents.length / Math.max(stats.total_lines, 1)) * 100;
    const extra = background.length ? " <span class=\"banner-extra\">(+" + plural(background.length, "background noise group") + ")</span>" : "";
    const totalGroups = plural(incidents.length, "group");
    const banner = el("div", "ll-banner ll-fade");
    banner.innerHTML =
      '<div class="ll-banner-pills">' +
      '<span class="ll-banner-pill">✓ Analysis Complete · ' + Number(stats.seconds).toFixed(2) + " s</span>" +
      '<span class="ll-banner-pill green">' + noisePct.toFixed(2) + "% noise reduced</span>" +
      "</div>" +
      "<h2>" + plural(stats.total_lines, "line") + " → " + plural(realIncidents.length, "incident") + extra + "</h2>" +
      "<p><code>" + escapeHtml(W.name || "log") + "</code> · " +
      plural(stats.candidate_count, "line") + " at " + escapeHtml(minSev) + "+ collapsed from " +
      plural(stats.n_unique, "distinct message") + " into " + totalGroups + ".</p>";
    view.appendChild(banner);

    // ---- KPI cards
    const kpis = [
      ["Lines in file", num(stats.total_lines), "raw input"],
      ["Parsed", num(stats.parsed), "+" + num(stats.continuation) + " stack lines"],
      ["Skipped", num(stats.skipped), "no timestamp"],
      [minSev + "+ lines", num(stats.candidate_count), num(stats.n_unique) + " distinct"],
      ["Services", String(stats.services_detected_count), "detected"],
      ["Time span", fmtDuration(data.window ? data.window.span_s : 0),
        data.window ? fmtClock(data.window.t0) + " → " + fmtClock(data.window.t1) : "—"],
    ];
    const kpiGrid = el("div", "kpi-grid");
    kpis.forEach((k) => {
      const card = el("div", "ll-kpi-card ll-fade");
      card.innerHTML =
        '<div class="ll-kpi-label">' + escapeHtml(k[0]) + "</div>" +
        '<div class="ll-kpi-val">' + escapeHtml(k[1]) + "</div>" +
        '<div class="ll-kpi-sub">' + escapeHtml(k[2]) + "</div>";
      kpiGrid.appendChild(card);
    });
    view.appendChild(kpiGrid);

    // ---- cascade strip
    if (trigger) {
      const cascade = el("div", "ll-cascade ll-fade");
      const text = el("div", "ll-cascade-text");
      text.innerHTML =
        '<strong style="color:var(--ll-trigger-ink);">' + escapeHtml(trigger.services.join(", ")) + "</strong> started failing first at " +
        "<code>" + fmtClock(trigger.first_seen) + "</code> with <code>" + escapeHtml(trigger.template) + "</code> — " +
        "followed by <strong>" + knockOns.length + "</strong> probable knock-on group" + (knockOns.length === 1 ? "" : "s") +
        " within " + knockWindow + " min.";
      cascade.innerHTML = '<div class="ll-cascade-title"><span class="ll-pulse-dot"></span>Likely Root-Cause Trigger &amp; Cascade</div>';
      cascade.appendChild(text);

      const flow = el("div", "ll-cascade-flow");
      const triggerNode = el("span", "ll-node-trigger");
      triggerNode.innerHTML =
        "⚡ " + escapeHtml(trigger.services[0] || "?") +
        ' <span class="node-time">' + fmtClock(trigger.first_seen) + "</span>";
      flow.appendChild(triggerNode);
      knockOns.slice(0, 8).forEach((k) => {
        const arrow = el("span", "ll-arrow", "→");
        flow.appendChild(arrow);
        const node = el("span", "ll-node-knock");
        node.innerHTML =
          (k.lag_s != null ? '<span class="node-lag">+' + fmtDuration(k.lag_s) + "</span> " : "") +
          escapeHtml(k.services[0] || "?");
        flow.appendChild(node);
      });
      if (knockOns.length > 8) {
        flow.appendChild(el("span", "ll-arrow", "→"));
        flow.appendChild(el("span", "ll-node-knock", "+" + (knockOns.length - 8) + " more"));
      }
      cascade.appendChild(flow);
      view.appendChild(cascade);
    }

    // ---- notes
    if (data.notes && data.notes.length) {
      const notes = el("div", "notes-list");
      data.notes.forEach((n) => notes.appendChild(el("div", "note-caption", "ℹ️ " + n)));
      view.appendChild(notes);
    }

    // ---- timeline
    const timelineTitle = el("h2", "section-title",
      "Incident Volume Timeline — " + minSev + "+ lines per " + (data.window ? data.window.bucket_label : "bucket"));
    view.appendChild(timelineTitle);
    const chartCard = el("div", "card chart-card");
    const chartHost = el("div", "chart-host");
    chartHost.id = "timeline-chart";
    chartCard.appendChild(chartHost);
    view.appendChild(chartCard);
    if (data.timeline && data.timeline.length) {
      renderChart(chartHost, timelineSpec(data));
    } else {
      chartHost.appendChild(el("div", "chart-fallback", "No candidate lines to plot."));
    }

    // ---- explorer
    const explorerTitle = el("h2", "section-title");
    explorerTitle.innerHTML = "Ranked Incidents <span class=\"section-count\">(" + realIncidents.length + ")</span>";
    view.appendChild(explorerTitle);

    const bar = el("div", "explorer-bar");
    const roleBox = el("div", "pills");
    roleBox.id = "role-pills";
    roleBox.setAttribute("role", "group");
    roleBox.setAttribute("aria-label", "Filter by role");
    bar.appendChild(roleBox);

    const searchField = el("div", "explorer-field");
    searchField.innerHTML =
      '<label class="control-label" for="search-input"><span>Search templates</span></label>' +
      '<input type="search" id="search-input" class="ll-input" placeholder="Filter by keyword or service…" />';
    bar.appendChild(searchField);

    const sortField = el("div", "explorer-field");
    sortField.innerHTML =
      '<label class="control-label" for="sort-select"><span>Sort by</span></label>' +
      '<select id="sort-select" class="ll-select">' +
      "<option>Impact Score</option><option>Earliest First</option>" +
      "<option>Most Lines</option><option>Fastest Growth</option></select>";
    bar.appendChild(sortField);

    const svcField = el("div", "explorer-field");
    svcField.innerHTML =
      '<div class="control-label"><span>Filter by service</span></div>' +
      '<div class="multiselect">' +
      '<button type="button" class="multiselect-toggle" id="svc-toggle" aria-expanded="false" aria-haspopup="true">All services</button>' +
      '<div class="multiselect-menu" id="svc-menu" role="group" aria-label="Filter by service"></div>' +
      "</div>";
    bar.appendChild(svcField);

    view.appendChild(bar);

    const meta = el("div", "result-meta");
    meta.id = "result-meta";
    view.appendChild(meta);

    const list = el("div", "incident-list");
    list.id = "incident-list";
    view.appendChild(list);

    // populating + wiring
    const showBackground = $("#show-background").checked;
    const roles = ["All", "⚡ Trigger", "↳ Knock-on", "◦ Independent"].concat(showBackground ? ["〰 Background"] : []);
    roles.forEach((label) => {
      const btn = el("button", "pill", label);
      btn.type = "button";
      btn.dataset.role = label;
      btn.setAttribute("aria-pressed", String(label === W.roleFilter));
      if (!roles.includes(W.roleFilter)) W.roleFilter = "All";
      btn.addEventListener("click", () => {
        W.roleFilter = label;
        $$("#role-pills .pill").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.role === label)));
        renderIncidentList();
      });
      roleBox.appendChild(btn);
    });

    const searchInput = $("#search-input", searchField);
    searchInput.value = W.search;
    let searchTimer = null;
    searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        W.search = searchInput.value;
        renderIncidentList();
      }, 120);
    });

    const sortSelect = $("#sort-select", sortField);
    sortSelect.value = W.sort;
    sortSelect.addEventListener("change", () => {
      W.sort = sortSelect.value;
      renderIncidentList();
    });

    buildServiceMenu();

    renderIncidentList();
    renderExtras(view, data, incidents);
  }

  function buildServiceMenu() {
    const menu = $("#svc-menu");
    if (!menu) return;
    menu.innerHTML = "";
    const services = allServices();
    services.forEach((svc) => {
      const label = el("label", "multiselect-option");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = svc;
      box.checked = W.services.indexOf(svc) !== -1;
      box.addEventListener("change", () => {
        if (box.checked) {
          if (W.services.indexOf(svc) === -1) W.services.push(svc);
        } else {
          W.services = W.services.filter((s) => s !== svc);
        }
        updateServiceToggle();
        renderIncidentList();
      });
      label.appendChild(box);
      label.appendChild(document.createTextNode(svc));
      menu.appendChild(label);
    });
    if (!services.length) menu.appendChild(el("div", "note-caption", "No services detected."));
    const clear = el("button", "multiselect-clear", "Clear selection");
    clear.type = "button";
    clear.addEventListener("click", () => {
      W.services = [];
      $$("#svc-menu input").forEach((b) => (b.checked = false));
      updateServiceToggle();
      renderIncidentList();
    });
    menu.appendChild(clear);
    updateServiceToggle();

    const toggle = $("#svc-toggle");
    if (toggle && !toggle.dataset.wired) {
      toggle.dataset.wired = "1";
      toggle.addEventListener("click", () => {
        const open = menu.classList.toggle("open");
        toggle.setAttribute("aria-expanded", String(open));
      });
      document.addEventListener("click", (ev) => {
        if (!ev.target.closest || !ev.target.closest(".multiselect")) {
          menu.classList.remove("open");
          toggle.setAttribute("aria-expanded", "false");
        }
      });
    }
  }

  function updateServiceToggle() {
    const toggle = $("#svc-toggle");
    if (!toggle) return;
    toggle.textContent = W.services.length
      ? W.services.length + " service" + (W.services.length === 1 ? "" : "s") + " selected"
      : "All services";
  }

  function filteredIncidents() {
    const data = W.data;
    if (!data) return [];
    const showBackground = $("#show-background").checked;
    let rows = (data.incidents || []).filter((i) => showBackground || i.role !== "background");

    const roleMap = {
      "⚡ Trigger": "trigger",
      "↳ Knock-on": "knock-on",
      "◦ Independent": "independent",
      "〰 Background": "background",
    };
    if (W.roleFilter !== "All" && roleMap[W.roleFilter]) {
      rows = rows.filter((i) => i.role === roleMap[W.roleFilter]);
    }
    if (W.services.length) {
      rows = rows.filter((i) => i.services.some((s) => W.services.indexOf(s) !== -1));
    }
    const q = (W.search || "").trim().toLowerCase();
    if (q) {
      rows = rows.filter(
        (i) =>
          i.template.toLowerCase().indexOf(q) !== -1 ||
          i.services.some((s) => s.toLowerCase().indexOf(q) !== -1)
      );
    }
    const sorted = rows.slice();
    if (W.sort === "Earliest First") {
      sorted.sort((a, b) => secondsBetween(b.first_seen, a.first_seen));
    } else if (W.sort === "Most Lines") {
      sorted.sort((a, b) => b.count - a.count);
    } else if (W.sort === "Fastest Growth") {
      sorted.sort((a, b) => b.growth_ratio - a.growth_ratio);
    } else {
      sorted.sort((a, b) => b.score - a.score);
    }
    return sorted;
  }

  function renderIncidentList() {
    const list = $("#incident-list");
    if (!list || !W.data) return;
    const rows = filteredIncidents();
    const maxCards = Math.max(3, Math.min(50, parseInt($("#max-cards").value, 10) || 10));
    const meta = $("#result-meta");
    list.innerHTML = "";

    if (meta) {
      meta.textContent =
        "Showing " + Math.min(rows.length, maxCards) + " of " + rows.length + " matching groups.";
    }
    if (!rows.length) {
      const empty = el("div", "banner banner-info");
      empty.appendChild(el("div", null, "No incident groups match your current filter selection."));
      list.appendChild(empty);
      return;
    }

    const trigger = (W.data.incidents || []).find((i) => i.role === "trigger") || null;
    rows.slice(0, maxCards).forEach((incident) => {
      list.appendChild(buildIncidentCard(incident, trigger));
    });

    if (rows.length > maxCards) {
      const info = el("div", "banner banner-info");
      info.appendChild(el("div", null,
        "Showing the top " + maxCards + " of " + rows.length +
        " matching groups — raise the limit in the sidebar or use the table below."));
      list.appendChild(info);
    }

    // Charts are rendered after the nodes are in the document.
    rows.slice(0, maxCards).forEach((incident) => {
      const host = document.getElementById("spark-" + incident.cluster_id);
      if (host) {
        renderChart(host, sparklineSpec(incident.sparkline || [], colourFor(incident.cluster_id), incident.onset));
      }
    });
  }

  function scoreRingHtml(score, colour) {
    const pct = Math.max(0, Math.min(100, Number(score) || 0));
    const dash = 106.8;
    const offset = (dash * (1 - pct / 100)).toFixed(1);
    return (
      '<div class="score-ring">' +
      '<div class="score-ring-graphic">' +
      '<svg width="46" height="46" viewBox="0 0 44 44" aria-hidden="true">' +
      '<circle cx="22" cy="22" r="17" fill="none" stroke="' + token("--ll-border", "#E2E8F0") + '" stroke-width="3.6" />' +
      '<circle cx="22" cy="22" r="17" fill="none" stroke="' + colour + '" stroke-width="3.6" ' +
      'stroke-linecap="round" stroke-dasharray="' + dash + '" stroke-dashoffset="' + offset + '" ' +
      'transform="rotate(-90 22 22)" />' +
      "</svg>" +
      "<span>" + Math.round(pct) + "</span>" +
      "</div>" +
      '<div class="score-ring-label">' +
      '<div class="score-ring-title">Impact</div>' +
      '<div class="score-ring-sub">out of 100</div>' +
      "</div>" +
      "</div>"
    );
  }

  function buildIncidentCard(incident, triggerIncident) {
    const colour = colourFor(incident.cluster_id);
    const role = incident.role;
    const compact = role === "background";
    const card = el("article", "incident-card ll-fade" + (compact ? " compact" : ""));
    card.dataset.clusterId = String(incident.cluster_id);

    let badge = ROLE_BADGE[role] || role;
    if (role === "knock-on" && incident.lag_s != null) {
      badge += " (+" + fmtDuration(incident.lag_s) + ")";
    }
    const roleClass = ROLE_CLASS[role] || "ll-role-bg";

    const svcTags = incident.services
      .map((s) => '<span class="ll-svc-tag">' + escapeHtml(s) + "</span>")
      .join("");

    const head = el("div", "card-head");
    const headMain = el("div", "card-head-main");
    headMain.innerHTML =
      '<div class="card-topbar" style="background:' + colour + ';"></div>' +
      '<div class="card-badges">' +
      '<span class="card-rank">#' + incident.rank + "</span>" +
      '<span class="ll-badge ll-sev-' + escapeHtml(incident.max_severity) + '">' + escapeHtml(incident.max_severity) + "</span>" +
      svcTags +
      '<span class="ll-badge ' + roleClass + '">' + escapeHtml(badge) + "</span>" +
      "</div>" +
      '<div class="ll-template-box">' + templateHtml(incident.template) + "</div>";
    head.appendChild(headMain);
    const ring = el("div");
    ring.innerHTML = scoreRingHtml(incident.score, colour);
    head.appendChild(ring.firstChild);
    card.appendChild(head);

    // metrics + sparkline
    const metrics = el("div", "card-metrics");
    const items = [
      ["Lines", num(incident.count), null],
      ["Services", String(incident.n_services), incident.services.join(", ")],
      ["First seen", fmtClock(incident.first_seen), fmtDateClock(incident.first_seen)],
      ["Last seen", fmtClock(incident.last_seen), fmtDateClock(incident.last_seen)],
      ["Growth", fmtGrowth(incident), "rate in the recent window vs. the rate before it"],
    ];
    items.forEach((m) => {
      const box = el("div", "metric");
      if (m[2]) box.title = m[2];
      box.innerHTML =
        '<div class="metric-label">' + escapeHtml(m[0]) + "</div>" +
        '<div class="metric-value">' + escapeHtml(m[1]) + "</div>";
      metrics.appendChild(box);
    });
    const sparkBox = el("div", "metric metric-spark");
    const sparkHost = el("div", "chart-host");
    sparkHost.id = "spark-" + incident.cluster_id;
    sparkBox.appendChild(sparkHost);
    metrics.appendChild(sparkBox);
    card.appendChild(metrics);

    // role explanation
    const roleText = el("p", "card-role-text");
    if (role === "trigger") {
      roleText.innerHTML =
        "⚡ <strong>Likely trigger.</strong> " + escapeHtml(incident.role_detail) +
        " Later groups that began shortly after are marked as knock-on effects.";
    } else if (role === "knock-on" && triggerIncident) {
      roleText.innerHTML =
        "↳ <strong>Probable knock-on effect</strong> of #" + triggerIncident.rank +
        " (" + escapeHtml(triggerIncident.services[0] || "?") + "). " + escapeHtml(incident.role_detail);
    } else {
      roleText.textContent = incident.role_detail;
    }
    card.appendChild(roleText);

    if (compact) {
      card.appendChild(el("div", "note-caption", "Sample raw line (line " + num(incident.sample_line_no) + "):"));
      const code = el("pre", "code-block mt-8", incident.sample_raw);
      card.appendChild(code);
      return card;
    }

    // tabs
    const tabs = el("div", "tabs");
    const tablist = el("div", "tablist");
    tablist.setAttribute("role", "tablist");
    const panelWrap = el("div");
    const tabDefs = [
      ["Sample Raw Line", "sample"],
      ["Score Breakdown", "score"],
      ["All Raw Lines (" + num(incident.raw_lines_total) + ")", "raw"],
    ];
    const panels = {};

    tabDefs.forEach((def, idx) => {
      const tab = el("button", "tab", def[0]);
      tab.type = "button";
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", idx === 0 ? "true" : "false");
      tab.id = "tab-" + incident.cluster_id + "-" + def[1];
      tab.addEventListener("click", () => {
        $$(".tab", tablist).forEach((t) => t.setAttribute("aria-selected", "false"));
        tab.setAttribute("aria-selected", "true");
        Object.keys(panels).forEach((key) => panels[key].classList.toggle("active", key === def[1]));
      });
      tablist.appendChild(tab);

      const panel = el("div", "tab-panel" + (idx === 0 ? " active" : ""));
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id);
      panels[def[1]] = panel;
    });
    tabs.appendChild(tablist);
    tabs.appendChild(panelWrap);

    // panel: sample raw line
    panels.sample.appendChild(el("div", "note-caption", "Line " + num(incident.sample_line_no) + " of the input:"));
    panels.sample.appendChild(el("pre", "code-block mt-8", incident.sample_raw));

    // panel: score breakdown
    const scoreTable = el("div", "table-scroll");
    const st = document.createElement("table");
    st.className = "ll-table";
    st.innerHTML =
      "<thead><tr><th>Factor</th><th>Evidence</th><th>Normalised</th><th>Weight</th><th>Points</th></tr></thead><tbody>" +
      (incident.score_breakdown || [])
        .map(
          (r) =>
            "<tr><td>" + escapeHtml(r.Factor) + "</td><td>" + escapeHtml(r.Evidence) + "</td>" +
            '<td class="num">' + Number(r.Normalised).toFixed(2) + "</td>" +
            '<td class="num">' + Number(r.Weight).toFixed(2) + "</td>" +
            '<td class="num">' + Number(r.Points).toFixed(1) + "</td></tr>"
        )
        .join("") +
      "</tbody>";
    scoreTable.appendChild(st);
    panels.score.appendChild(scoreTable);
    panels.score.appendChild(el("div", "table-note",
      "Points = weight × normalised factor ÷ Σweights × 100; the five rows add up to the impact score."));

    // panel: all raw lines
    if (incident.raw_lines_total > incident.raw_lines.length) {
      panels.raw.appendChild(el("div", "table-note",
        "Showing the first " + num(incident.raw_lines.length) + " of " + num(incident.raw_lines_total) +
        " lines — download for the full set."));
    }
    const rawWrap = el("div", "table-scroll mt-8");
    const rt = document.createElement("table");
    rt.className = "ll-table";
    rt.innerHTML =
      "<thead><tr><th>line</th><th>time</th><th>sev</th><th>service</th><th>raw</th></tr></thead><tbody>" +
      (incident.raw_lines || [])
        .map(
          (r) =>
            '<tr><td class="num">' + num(r.line_no) + "</td>" +
            '<td class="mono">' + fmtClockMs(r.timestamp) + "</td>" +
            "<td>" + escapeHtml(r.severity) + "</td>" +
            '<td class="mono">' + escapeHtml(r.service) + "</td>" +
            '<td class="mono">' + escapeHtml(r.raw) + "</td></tr>"
        )
        .join("") +
      "</tbody>";
    rawWrap.appendChild(rt);
    panels.raw.appendChild(rawWrap);

    const dlWrap = el("div", "download-row");
    const dl = el("button", "btn btn-sm", "⬇ Download these lines (.log)");
    dl.type = "button";
    dl.addEventListener("click", () => {
      downloadBlob("incident_" + incident.rank + ".log", (incident.raw_lines || []).map((r) => r.raw).join("\n"), "text/plain;charset=utf-8");
    });
    dlWrap.appendChild(dl);
    panels.raw.appendChild(dlWrap);

    tabDefs.forEach((def) => panelWrap.appendChild(panels[def[1]]));
    card.appendChild(tabs);
    return card;
  }

  function renderExtras(view, data, incidents) {
    // ---- all-groups table + CSV
    const groups = el("details", "expander");
    const summary = el("summary");
    summary.textContent = "All groups as a table / CSV export";
    groups.appendChild(summary);

    const tableWrap = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "ll-table ll-table-wide";
    const head = "<thead><tr><th>rank</th><th>score</th><th>role</th><th>max severity</th><th>lines</th>" +
      "<th>services</th><th>service names</th><th>first seen</th><th>last seen</th><th>growth</th><th>template</th></tr></thead>";
    table.innerHTML =
      head +
      "<tbody>" +
      incidents
        .map(
          (r) =>
            '<tr><td class="num">' + r.rank + "</td>" +
            '<td class="num">' + Number(r.score).toFixed(1) + "</td>" +
            "<td>" + escapeHtml(r.role) + "</td>" +
            "<td>" + escapeHtml(r.max_severity) + "</td>" +
            '<td class="num">' + num(r.count) + "</td>" +
            '<td class="num">' + r.n_services + "</td>" +
            '<td class="mono">' + escapeHtml(r.services.join(", ")) + "</td>" +
            '<td class="mono">' + fmtClock(r.first_seen) + "</td>" +
            '<td class="mono">' + fmtClock(r.last_seen) + "</td>" +
            '<td class="num">' + Number(r.growth_ratio).toFixed(2) + "</td>" +
            '<td class="mono">' + escapeHtml(r.template) + "</td></tr>"
        )
        .join("") +
      "</tbody>";
    tableWrap.appendChild(table);
    groups.appendChild(tableWrap);

    const dlRow = el("div", "download-row");
    const csvBtn = el("button", "btn btn-sm", "⬇ Download incidents (.csv)");
    csvBtn.type = "button";
    csvBtn.addEventListener("click", () => {
      const header = ["rank", "score", "role", "max_severity", "count", "n_services", "services",
        "first_seen", "last_seen", "growth_ratio", "template"];
      const lines = [header.join(",")];
      incidents.forEach((r) => {
        lines.push([
          r.rank,
          Number(r.score).toFixed(1),
          r.role,
          r.max_severity,
          r.count,
          r.n_services,
          r.services.join(", "),
          r.first_seen,
          r.last_seen,
          Number(r.growth_ratio).toFixed(2),
          r.template,
        ].map(csvCell).join(","));
      });
      downloadBlob("loglens_incidents.csv", lines.join("\r\n"), "text/csv;charset=utf-8");
    });
    dlRow.appendChild(csvBtn);
    groups.appendChild(dlRow);
    view.appendChild(groups);

    // ---- parsing details
    const details = el("details", "expander");
    const dSummary = el("summary");
    dSummary.textContent = "Parsing details";
    details.appendChild(dSummary);

    const grid = el("div", "details-grid");
    const sevBox = el("div");
    sevBox.appendChild(el("div", "details-subtitle", "Lines by severity"));
    const sevTable = el("div", "table-scroll");
    const severityOrder = ["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"];
    const sevCounts = data.severity_counts || {};
    let sevRows = "";
    severityOrder.forEach((sev) => {
      if (Object.prototype.hasOwnProperty.call(sevCounts, sev)) {
        sevRows += "<tr><td>" + escapeHtml(sev) + '</td><td class="num">' + num(sevCounts[sev]) + "</td></tr>";
      }
    });
    Object.keys(sevCounts).forEach((sev) => {
      if (severityOrder.indexOf(sev) === -1) {
        sevRows += "<tr><td>" + escapeHtml(sev) + '</td><td class="num">' + num(sevCounts[sev]) + "</td></tr>";
      }
    });
    const sevEl = document.createElement("table");
    sevEl.className = "ll-table";
    sevEl.innerHTML = "<thead><tr><th>severity</th><th>lines</th></tr></thead><tbody>" + sevRows + "</tbody>";
    sevTable.appendChild(sevEl);
    sevBox.appendChild(sevTable);
    grid.appendChild(sevBox);

    const svcBox = el("div");
    svcBox.appendChild(el("div", "details-subtitle", "Lines by service"));
    const svcTable = el("div", "table-scroll");
    const svcEl = document.createElement("table");
    svcEl.className = "ll-table";
    const svcCounts = data.service_counts || {};
    svcEl.innerHTML =
      "<thead><tr><th>service</th><th>lines</th></tr></thead><tbody>" +
      Object.keys(svcCounts)
        .map((svc) => "<tr><td>" + escapeHtml(svc) + '</td><td class="num">' + num(svcCounts[svc]) + "</td></tr>")
        .join("") +
      "</tbody>";
    svcTable.appendChild(svcEl);
    svcBox.appendChild(svcTable);
    grid.appendChild(svcBox);

    details.appendChild(grid);

    const skipped = (data.stats && data.stats.skipped_samples) || [];
    if (skipped.length) {
      details.appendChild(el("div", "details-subtitle mt-16",
        "Skipped lines (" + num(data.stats.skipped) + " total, first " + skipped.length + " shown)"));
      details.appendChild(el("pre", "code-block mt-8",
        skipped.map((s) => "line " + s[0] + ": " + s[1]).join("\n")));
    }
    view.appendChild(details);
  }

  function renderEmptyState(view, data) {
    const empty = el("div", "banner " + (data.empty_reason === "no_severity_lines" ? "banner-warn" : "banner-error"));
    empty.setAttribute("role", "alert");
    const body = el("div");
    body.appendChild(el("strong", null, data.empty_reason === "no_severity_lines" ? "Nothing at this severity" : "Could not read this log"));
    body.appendChild(document.createTextNode(data.error || "No analysable lines were found."));
    empty.appendChild(body);
    view.appendChild(empty);

    const stats = data.stats || {};
    const kpis = [
      ["Lines received", num(stats.total_lines), "raw input"],
      ["Parsed", num(stats.parsed), "with timestamps"],
      ["Skipped", num(stats.skipped), "no timestamp"],
      ["Blank", num(stats.blank), "empty lines"],
    ];
    const kpiGrid = el("div", "kpi-grid");
    kpis.forEach((k) => {
      const card = el("div", "ll-kpi-card");
      card.innerHTML =
        '<div class="ll-kpi-label">' + escapeHtml(k[0]) + "</div>" +
        '<div class="ll-kpi-val">' + escapeHtml(k[1]) + "</div>" +
        '<div class="ll-kpi-sub">' + escapeHtml(k[2]) + "</div>";
      kpiGrid.appendChild(card);
    });
    view.appendChild(kpiGrid);

    const skipped = stats.skipped_samples || [];
    if (skipped.length) {
      const details = el("details", "expander");
      details.open = true;
      details.appendChild(el("summary", null, "Skipped lines (first " + skipped.length + " shown)"));
      details.appendChild(el("pre", "code-block mt-8", skipped.map((s) => s[0] + ": " + s[1]).join("\n")));
      view.appendChild(details);
    }

    const actions = el("div", "download-row");
    const sampleBtn = el("button", "btn btn-primary btn-sm", "Load the 10K sample log");
    sampleBtn.type = "button";
    sampleBtn.addEventListener("click", loadSampleLog);
    const homeBtn = el("button", "btn btn-sm", "Back to landing page");
    homeBtn.type = "button";
    homeBtn.addEventListener("click", goHome);
    actions.appendChild(sampleBtn);
    actions.appendChild(homeBtn);
    view.appendChild(actions);
  }

  // ---------------------------------------------------------------- footer
  function renderFooter() {
    const slot = $("#footer-slot");
    slot.innerHTML = "";
    const card = el("div", "ll-footer-card");
    card.innerHTML =
      '<div class="footer-grid">' +
      "<div>" +
      '<div class="footer-brand-row">' + LOGO_SVG +
      '<span class="footer-brand-name">Log<span>Lens</span></span></div>' +
      '<p class="footer-desc">Turning 10,000 noisy log lines into a handful of ranked, explained incidents ' +
      "in under a second. Built for fast, offline root-cause analysis.</p>" +
      '<a class="btn btn-sm" href="https://github.com/sakshamhada-tech/LogLens_Protothon" target="_blank" rel="noopener noreferrer">GitHub Repo ↗</a>' +
      "</div>" +
      "<div>" +
      '<div class="ll-footer-col-title">Explore</div>' +
      '<div class="footer-links">' +
      '<button type="button" class="btn btn-sm btn-ghost" id="ft-home">Landing Home</button>' +
      '<button type="button" class="btn btn-sm btn-ghost" id="ft-demo">10K Demo Log</button>' +
      '<button type="button" class="btn btn-sm btn-ghost" id="ft-about">About Us</button>' +
      "</div>" +
      "</div>" +
      "<div>" +
      '<div class="ll-footer-col-title">Core Pipeline</div>' +
      '<div class="footer-pipeline">' +
      "🔵 <code>parser.py</code> · Ingestion<br/>" +
      "🟣 <code>cluster.py</code> · Drain Mining<br/>" +
      "🔴 <code>rank.py</code> · Impact &amp; Trigger<br/>" +
      "🟢 <code>pytest</code> · 44 Passing Tests" +
      "</div>" +
      "</div>" +
      "<div>" +
      '<div class="ll-footer-col-title">Contact &amp; Team</div>' +
      '<div class="footer-links">' +
      '<button type="button" class="btn btn-sm btn-primary" id="ft-team">Meet Team ByteForce →</button>' +
      '<button type="button" class="btn btn-sm" id="ft-contact">Contact Us</button>' +
      "</div>" +
      "</div>" +
      "</div>" +
      '<div class="ll-footer-copy">' +
      "<span>&copy; 2026 <strong>LogLens</strong> · Team ByteForce (<code>2392608004-ByteForce</code>). All rights reserved.</span>" +
      "<span>Offline Local Engine · Zero Paid APIs</span>" +
      "</div>";
    slot.appendChild(card);

    const wire = (id, fn) => {
      const node = $("#" + id, card);
      if (node) node.addEventListener("click", fn);
    };
    wire("ft-home", goHome);
    wire("ft-demo", loadSampleLog);
    wire("ft-about", () => openDialog($("#dialog-about")));
    wire("ft-team", () => openTeamDialog());
    wire("ft-contact", () => openDialog($("#dialog-contact")));
  }

  // ---------------------------------------------------------------- modals
  function openDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }

  function closeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === "function") {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
  }

  function openTeamDialog() {
    W.teamDialogOpen = true;
    renderTeamDialog();
    openDialog($("#dialog-team"));
  }

  function renderTeamDialog() {
    const body = $("#team-dialog-body");
    if (!body) return;
    const member = TEAM_MEMBERS[W.teamIndex];
    body.innerHTML = "";

    const lead = el("div", "modal-lead-wrap");
    lead.innerHTML =
      '<span class="modal-pill">2392608004-ByteForce</span>' +
      '<p class="modal-lead">Select a team member below to view their role, contribution, and profiles.</p>';
    body.appendChild(lead);

    const segmented = el("div", "segmented");
    segmented.id = "team-segmented";
    segmented.setAttribute("role", "group");
    segmented.setAttribute("aria-label", "Select team member");
    TEAM_MEMBERS.forEach((m, idx) => {
      const btn = el("button", "pill", m.name.split(" ")[0]);
      btn.type = "button";
      btn.setAttribute("aria-pressed", String(idx === W.teamIndex));
      btn.addEventListener("click", () => {
        W.teamIndex = idx;
        renderTeamDialog();
      });
      segmented.appendChild(btn);
    });
    body.appendChild(segmented);

    const spotlight = el("div", "ll-spotlight");
    const ring = el("div", "ll-avatar-ring");
    ring.style.background = member.gradient;
    const img = document.createElement("img");
    img.className = "ll-avatar-img";
    img.alt = member.name;
    img.loading = "lazy";
    img.src = "/assets/team/" + member.photo;
    img.addEventListener("error", () => {
      const initials = el("div", "ll-avatar-init", member.initials);
      if (img.parentNode) img.parentNode.replaceChild(initials, img);
    });
    ring.appendChild(img);
    spotlight.appendChild(ring);

    const info = el("div", "spotlight-body");
    info.innerHTML =
      '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:6px;">' +
      '<span class="spotlight-name">' + escapeHtml(member.name) + "</span>" +
      '<span class="spotlight-usn">' + escapeHtml(member.usn) + "</span>" +
      "</div>" +
      '<span class="spotlight-role" style="background:' + member.pill_bg + ";color:" + member.pill_fg + ';">' +
      escapeHtml(member.role) + "</span>" +
      '<p class="spotlight-contrib">' + escapeHtml(member.contribution) + "</p>" +
      "<div>" +
      '<a class="ll-social-btn ll-btn-gh" href="' + escapeHtml(member.github) + '" target="_blank" rel="noopener noreferrer">GitHub Profile ↗</a>' +
      '<a class="ll-social-btn ll-btn-li" href="' + escapeHtml(member.linkedin) + '" target="_blank" rel="noopener noreferrer">LinkedIn Profile ↗</a>' +
      "</div>";
    spotlight.appendChild(info);
    body.appendChild(spotlight);

    const nav = el("div", "modal-nav");
    const prev = el("button", "btn btn-sm", "← Prev");
    prev.type = "button";
    prev.addEventListener("click", () => {
      W.teamIndex = (W.teamIndex - 1 + TEAM_MEMBERS.length) % TEAM_MEMBERS.length;
      renderTeamDialog();
    });
    const counter = el("div", "modal-count", W.teamIndex + 1 + " / " + TEAM_MEMBERS.length);
    const next = el("button", "btn btn-sm", "Next →");
    next.type = "button";
    next.addEventListener("click", () => {
      W.teamIndex = (W.teamIndex + 1) % TEAM_MEMBERS.length;
      renderTeamDialog();
    });
    nav.appendChild(prev);
    nav.appendChild(counter);
    nav.appendChild(next);
    body.appendChild(nav);
  }

  // ------------------------------------------------------------ data sources
  function loadSampleLog() {
    setLoading(true, "Downloading the 10,000-line sample log…");
    clearError();
    fetch("/sample_logs/sample.log", { cache: "no-cache" })
      .then((resp) => {
        if (!resp.ok) throw new Error("Could not download the sample log (HTTP " + resp.status + ").");
        return resp.text();
      })
      .then((text) => {
        setLoading(false);
        loadSource(text, "sample_logs/sample.log");
      })
      .catch((err) => {
        setLoading(false);
        showError("Sample log unavailable", err.message || "Could not download the sample log.", false);
      });
  }

  function loadMiniStory() {
    loadSource(MINI_DEMO_LOG, "mini_cascade.log");
  }

  function handleFile(file) {
    if (!file) return;
    const allowed = [".log", ".txt", ".text", ".out"];
    const lower = (file.name || "").toLowerCase();
    const hasAllowedExt = allowed.some((ext) => lower.endsWith(ext));
    if (!hasAllowedExt) {
      showError("Unsupported file", "Please choose a .log, .txt, .text or .out file.", false);
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      showError(
        "File too large",
        "This file is " + (file.size / 1024 / 1024).toFixed(1) +
        " MB. The hosted deployment accepts up to 4 MB per request — split the file and analyse it in parts.",
        false
      );
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      $("#file-name").hidden = false;
      $("#file-name").textContent = file.name + " · " + (file.size / 1024).toFixed(0) + " KB";
      loadSource(String(reader.result || ""), file.name);
    };
    reader.onerror = () => showError("Read failed", "The browser could not read this file.", false);
    reader.readAsText(file);
  }

  // ----------------------------------------------------------------- wiring
  function wireSidebar() {
    $("#sidebar-brand").innerHTML =
      LOGO_SVG +
      '<div><div class="sidebar-brand-name">Log<span style="color:var(--ll-brand);">Lens</span></div>' +
      '<div class="sidebar-brand-sub">Offline · Rule-Free</div></div>';
    $("#brand-logo").innerHTML = LOGO_SVG;

    $("#btn-load-sample").addEventListener("click", () => {
      closeMobileSidebar();
      loadSampleLog();
    });
    $("#btn-load-mini").addEventListener("click", () => {
      closeMobileSidebar();
      loadMiniStory();
    });

    const fileInput = $("#file-input");
    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files[0]) handleFile(fileInput.files[0]);
      closeMobileSidebar();
    });
    const drop = $("#file-drop");
    ["dragenter", "dragover"].forEach((evt) =>
      drop.addEventListener(evt, (e) => {
        e.preventDefault();
        drop.classList.add("dragover");
      })
    );
    ["dragleave", "drop"].forEach((evt) =>
      drop.addEventListener(evt, (e) => {
        e.preventDefault();
        drop.classList.remove("dragover");
      })
    );
    drop.addEventListener("drop", (e) => {
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) handleFile(file);
    });

    const paste = $("#paste-input");
    const pasteBtn = $("#btn-analyse-paste");
    paste.addEventListener("input", () => {
      pasteBtn.disabled = !paste.value.trim();
    });
    pasteBtn.addEventListener("click", () => {
      const text = paste.value;
      if (!text.trim()) return;
      closeMobileSidebar();
      loadSource(text, "pasted text");
    });

    // server-side controls: re-analyse on change (debounced)
    $("#min-severity").addEventListener("change", queueReanalysis);
    $$('input[name="method"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        $$(".radio-option").forEach((opt) => {
          const input = $("input", opt);
          opt.classList.toggle("is-selected", !!input && input.checked);
        });
        queueReanalysis();
      });
    });
    $("#similarity").addEventListener("input", (e) => {
      $("#similarity-value").textContent = Number(e.target.value).toFixed(2);
      queueReanalysis();
    });
    $("#knock-on").addEventListener("input", (e) => {
      const v = parseInt(e.target.value, 10);
      $("#knock-on-value").textContent = v + " min";
      queueReanalysis();
    });
    ["count", "severity", "services", "growth", "start"].forEach((k) => {
      const input = $("#w-" + k);
      input.addEventListener("input", (e) => {
        $("#w-" + k + "-value").textContent = Number(e.target.value).toFixed(2);
        queueReanalysis();
      });
    });

    // client-side controls: no re-analysis needed
    $("#max-cards").addEventListener("input", () => renderIncidentList());
    $("#max-cards").addEventListener("change", () => renderIncidentList());
    $("#show-background").addEventListener("change", () => render());

    $("#btn-back-home").addEventListener("click", () => {
      closeMobileSidebar();
      goHome();
    });

    // mobile drawer
    const toggle = $("#sidebar-toggle");
    const backdrop = $("#sidebar-backdrop");
    toggle.addEventListener("click", () => {
      const open = $("#sidebar").classList.toggle("open");
      backdrop.classList.toggle("show", open);
      toggle.setAttribute("aria-expanded", String(open));
    });
    backdrop.addEventListener("click", closeMobileSidebar);
  }

  function closeMobileSidebar() {
    $("#sidebar").classList.remove("open");
    $("#sidebar-backdrop").classList.remove("show");
    $("#sidebar-toggle").setAttribute("aria-expanded", "false");
  }


  // ----------------------------------------------------------------- theming
  const THEME_KEY = "ll-theme";

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }

  function storedTheme() {
    try {
      const v = localStorage.getItem(THEME_KEY);
      return v === "light" || v === "dark" ? v : null;
    } catch (e) {
      return null;
    }
  }

  function syncThemeToggle(theme) {
    const btn = $("#theme-toggle");
    if (!btn) return;
    const isDark = theme === "dark";
    btn.setAttribute("aria-pressed", isDark ? "true" : "false");
    btn.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
  }

  const REDUCED_MOTION = () =>
    !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  /* Timings, kept in sync with the llWipe* keyframes in style.css. */
  const WIPE_SWEEP_MS = 850;   // sheet travels across the viewport
  const WIPE_SETTLE_MS = 200;  // sheet dissolves off the freshly themed page

  /**
   * The theme swap itself. Charts bake their colours into the spec when it is
   * built, so a re-render is needed for them to pick up the new tokens.
   */
  function swapTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    syncThemeToggle(theme);
    if (W.text && W.data) render();
  }

  const WIPE_CLASSES = ["theme-wipe", "theme-wipe-to-dark", "theme-wipe-to-light", "theme-wipe-reveal"];
  let wipeStep = null;

  function endWipe() {
    if (wipeStep) { clearTimeout(wipeStep); wipeStep = null; }
    document.documentElement.classList.remove.apply(
      document.documentElement.classList, WIPE_CLASSES);
  }

  /**
   * Switch theme with the directional wipe: dark sweeps DOWN from the top,
   * light sweeps UP from the bottom.
   *
   * Two phases so the theme change is never visible as a snap:
   *   1. an opaque sheet in the destination colour sweeps in over the page;
   *   2. once it covers the viewport, the tokens are swapped underneath it and
   *      the sheet fades away to reveal the new theme.
   * Under prefers-reduced-motion the swap happens immediately, with no sheet.
   */
  function applyTheme(theme, opts) {
    const options = opts || {};
    const root = document.documentElement;

    if (!options.animate || REDUCED_MOTION()) {
      endWipe();
      swapTheme(theme);
      return;
    }

    endWipe();
    root.classList.add("theme-wipe");
    root.classList.add(theme === "dark" ? "theme-wipe-to-dark" : "theme-wipe-to-light");

    wipeStep = setTimeout(() => {
      // phase 2: the sheet now covers the viewport
      swapTheme(theme);
      root.classList.add("theme-wipe-reveal");
      wipeStep = setTimeout(endWipe, WIPE_SETTLE_MS + 40);
    }, WIPE_SWEEP_MS);
  }

  function setTheme(theme, persist, animate) {
    applyTheme(theme, { animate: animate });
    if (persist) {
      try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* private mode */ }
    }
  }

  function wireTheme() {
    const btn = $("#theme-toggle");
    if (!btn) return;
    syncThemeToggle(currentTheme());

    btn.addEventListener("click", () => {
      setTheme(currentTheme() === "dark" ? "light" : "dark", true, true);
    });

    // Follow the OS while the user has not made an explicit choice.
    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const onChange = (e) => {
        if (!storedTheme()) applyTheme(e.matches ? "dark" : "light", { animate: true });
      };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    }

    // Keep several open tabs in agreement.
    window.addEventListener("storage", (e) => {
      if (e.key === THEME_KEY && (e.newValue === "light" || e.newValue === "dark")) {
        applyTheme(e.newValue, { animate: false });
      }
    });
  }

  function wireModals() {
    $("#btn-team").addEventListener("click", openTeamDialog);
    $$("[data-close-dialog]").forEach((btn) => {
      btn.addEventListener("click", () => closeDialog(btn.closest("dialog")));
    });
    $$("dialog.ll-dialog").forEach((dialog) => {
      dialog.addEventListener("click", (e) => {
        if (e.target === dialog) closeDialog(dialog);
      });
    });
    const teamDialog = $("#dialog-team");
    teamDialog.addEventListener("close", () => {
      W.teamDialogOpen = false;
    });

    const form = $("#contact-form");
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = $("#contact-name").value.trim();
      const success = $("#contact-success");
      success.textContent = "Thanks " + (name || "there") +
        "! Your feedback has been noted for Team ByteForce.";
      success.hidden = false;
      form.reset();
    });
  }

  function init() {
    wireSidebar();
    wireModals();
    wireTheme();
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
