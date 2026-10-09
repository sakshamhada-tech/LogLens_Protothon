"""
parser.py — tolerant log-line parser for LogLens.

Turns raw text into a tidy pandas DataFrame with one row per log record:

    line_no | timestamp | severity | service | message | raw

Design goals
------------
* **Tolerant, not strict.** Real logs are messy. We look for a timestamp
  anywhere near the start of the line (ISO-8601, syslog, Apache/CLF, epoch),
  then peel optional "header" tokens off the front of the remainder:
  ``[service]``, ``service:``, ``level=error``, bare ``ERROR`` words,
  ``logger - `` names and so on. Whatever is left is the message.
* **Never crash.** A line that does not yield a timestamp is either attached
  to the previous record (stack-trace continuation lines) or skipped and
  counted, so the caller can report "N lines skipped".
* **No per-application rules.** Nothing here knows about any particular
  service or error text; it only knows common log *layouts*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

import pandas as pd

# --------------------------------------------------------------------------- #
# Severity handling
# --------------------------------------------------------------------------- #

#: Canonical severity levels, lowest to highest.
SEVERITY_ORDER = ["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]
SEVERITY_RANK = {name: i for i, name in enumerate(SEVERITY_ORDER)}

#: Spelling variants seen in the wild -> canonical level.
SEVERITY_ALIASES = {
    "TRACE": "TRACE", "VERBOSE": "TRACE", "FINEST": "TRACE", "FINER": "TRACE",
    "DEBUG": "DEBUG", "DBG": "DEBUG", "FINE": "DEBUG",
    "INFO": "INFO", "INF": "INFO", "INFORMATION": "INFO", "NOTICE": "INFO",
    "WARN": "WARN", "WARNING": "WARN", "WRN": "WARN",
    "ERROR": "ERROR", "ERR": "ERROR", "SEVERE": "ERROR",
    "CRITICAL": "CRITICAL", "CRIT": "CRITICAL", "FATAL": "CRITICAL",
    "EMERG": "CRITICAL", "EMERGENCY": "CRITICAL", "ALERT": "CRITICAL",
    "PANIC": "CRITICAL",
}

_SEVERITY_WORDS = "|".join(sorted(SEVERITY_ALIASES, key=len, reverse=True))

# A severity word at the head of the remaining text, followed by a separator.
_RE_SEVERITY_HEAD = re.compile(
    rf"(?P<val>{_SEVERITY_WORDS})(?=[\s:\]\-|,]|$)", re.IGNORECASE
)
# A severity word anywhere in the line (fallback when no header match).
_RE_SEVERITY_ANY = re.compile(
    rf"(?<![A-Za-z])(?P<val>{_SEVERITY_WORDS})(?![A-Za-z])", re.IGNORECASE
)
# key=value style levels, e.g. level=error, severity="WARN"
_RE_LEVEL_KV = re.compile(
    r"\b(?:level|lvl|severity|loglevel|log_level)=[\"']?(?P<val>[A-Za-z]+)",
    re.IGNORECASE,
)


def normalise_severity(token: Optional[str]) -> Optional[str]:
    """Map a raw level token ("warning", "ERR", "Fatal") to a canonical level."""
    if not token:
        return None
    return SEVERITY_ALIASES.get(token.strip().upper())


# --------------------------------------------------------------------------- #
# Timestamp handling
# --------------------------------------------------------------------------- #

_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"

#: (kind, regex). We search every pattern and keep the *earliest* match in the
#: line, so a timestamp mentioned later inside the message is not mistaken for
#: the record's own timestamp.
_TIMESTAMP_PATTERNS = [
    # 2026-10-09T03:00:01.123Z  /  2026-10-09 03:00:01,123  /  ...+05:30
    ("iso", re.compile(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?"
        r"(?:\s?(?:Z|[+-]\d{2}:?\d{2}))?"
    )),
    # Oct  9 03:00:01  (classic syslog, no year)
    ("syslog", re.compile(rf"(?:{_MONTHS})\s+\d{{1,2}}\s+\d{{2}}:\d{{2}}:\d{{2}}(?:\.\d+)?")),
    # 09/Oct/2026:03:00:01 +0000  (Apache / nginx access logs)
    ("clf", re.compile(rf"\d{{2}}/(?:{_MONTHS})/\d{{4}}:\d{{2}}:\d{{2}}:\d{{2}}(?:\s[+-]\d{{4}})?")),
    # 1760000401 or 1760000401.123 or 1760000401123 — only at line start
    ("epoch", re.compile(r"^\[?(?P<e>\d{13}|\d{10}(?:\.\d{1,6})?)\]?(?=\s)")),
]


def _to_naive_utc(dt: datetime) -> datetime:
    """Drop timezone info after converting to UTC, so all timestamps compare."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_timestamp(kind: str, text: str, default_year: int) -> Optional[datetime]:
    """Convert a matched timestamp string to a naive UTC datetime (or None)."""
    try:
        if kind == "iso":
            cleaned = text.replace(",", ".").replace(" Z", "Z")
            cleaned = re.sub(r"\s([+-]\d{2}:?\d{2})$", r"\1", cleaned)
            return _to_naive_utc(datetime.fromisoformat(cleaned))
        if kind == "syslog":
            cleaned = re.sub(r"\s+", " ", text.split(".")[0])
            return datetime.strptime(f"{default_year} {cleaned}", "%Y %b %d %H:%M:%S")
        if kind == "clf":
            fmt = "%d/%b/%Y:%H:%M:%S %z" if " " in text else "%d/%b/%Y:%H:%M:%S"
            return _to_naive_utc(datetime.strptime(text, fmt))
        if kind == "epoch":
            value = float(text.strip("[]"))
            if value > 1e11:          # milliseconds
                value /= 1000.0
            return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None
    return None


def find_timestamp(line: str):
    """Return (kind, match) for the earliest timestamp in the line, or None."""
    best = None
    for kind, pattern in _TIMESTAMP_PATTERNS:
        m = pattern.search(line)
        if m and (best is None or m.start() < best[1].start()):
            best = (kind, m)
    return best


# --------------------------------------------------------------------------- #
# Header token handling (service / level words between timestamp and message)
# --------------------------------------------------------------------------- #

_RE_BRACKET = re.compile(r"\[(?P<val>[^\]]{1,80})\]")
_RE_SERVICE_COLON = re.compile(r"(?P<val>[A-Za-z][A-Za-z0-9._\-]{0,63})(?:\[\d+\])?:\s+")
_RE_LOGGER_DASH = re.compile(r"(?P<val>[A-Za-z][A-Za-z0-9._\-]{0,63})\s+-\s+")
_RE_SERVICE_KV = re.compile(
    r"\b(?:service|svc|app|application|component|logger|source|container)"
    r"=[\"']?(?P<val>[A-Za-z0-9._\-/]+)",
    re.IGNORECASE,
)
_RE_SYSLOG_HOST_PROG = re.compile(
    r"(?P<host>[A-Za-z0-9][\w.\-]*)\s+(?P<prog>[A-Za-z][\w.\-/]*)(?:\[\d+\])?:\s+"
)
_RE_SERVICE_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9._\-/]{0,63}$")
_RE_IGNORABLE_BRACKET = re.compile(
    r"^(?:pid\s*)?\d+$|^(?:main|thread|worker)$|(?:thread|exec|worker|pool)-?\d+$",
    re.IGNORECASE,
)
_RE_LEADING_SEP = re.compile(r"^(?:\s*[|:]\s*|\s+-\s+|\s+)")
_RE_MSG_KV = re.compile(r'^(?:msg|message)=(?:"(?P<q>(?:[^"\\]|\\.)*)"|(?P<u>\S+))\s*')
_RE_CONTINUATION = re.compile(
    r"^(?:\s+|at\s|Caused by|Traceback|File\s\"|\.\.\.|\t|\^|[A-Za-z_.]+(?:Error|Exception)\b)"
)


def _strip_sep(text: str) -> str:
    """Remove a leading separator (' | ', ' - ', ':' or whitespace)."""
    while True:
        m = _RE_LEADING_SEP.match(text)
        if not m or m.end() == 0:
            return text
        text = text[m.end():]


def _looks_like_service(token: str) -> bool:
    """Heuristic: lowercase-start or contains '-', '_', '.', '/' or a digit.

    Message words at the start of a sentence are usually capitalised
    ("Timeout: ..."), whereas service names are conventionally lowercase or
    dashed ("payment-svc:", "com.acme.DbPool").
    """
    if not _RE_SERVICE_LIKE.match(token) or normalise_severity(token):
        return False
    return token[0].islower() or any(c in token for c in "-_./0123456789")


def split_header(rest: str, ts_kind: str):
    """Peel service / severity tokens off the front of ``rest``.

    Returns (severity, service, message). Each token type is only consumed
    once, so a message such as ``ERROR Error handling request`` keeps its
    second "Error" word.
    """
    severity: Optional[str] = None
    service: Optional[str] = None
    text = _strip_sep(rest)

    if ts_kind == "syslog" and service is None:
        m = _RE_SYSLOG_HOST_PROG.match(text)
        if m and not normalise_severity(m.group("prog")):
            service = m.group("prog")
            text = _strip_sep(text[m.end():])

    for _ in range(6):  # at most a handful of header tokens
        before = text

        # 1) [bracketed] token: level, service, or droppable metadata
        m = _RE_BRACKET.match(text)
        if m:
            inner = m.group("val").strip()
            sev = normalise_severity(inner)
            if sev and severity is None:
                severity = sev
            elif sev:
                break  # second level word: belongs to the message
            elif _RE_IGNORABLE_BRACKET.match(inner):
                pass   # [1234], [main], [pool-2-thread-1] -> metadata, drop
            elif service is None and _RE_SERVICE_LIKE.match(inner):
                service = inner
            else:
                break  # something like "[order failed]" -> message content
            text = _strip_sep(text[m.end():])
            continue

        # 2) key=value tokens: service=payment-svc, level=error
        m = _RE_SERVICE_KV.match(text)
        if m:
            service = service or m.group("val")
            text = _strip_sep(text[m.end():])
            continue
        m = _RE_LEVEL_KV.match(text)
        if m:
            severity = severity or normalise_severity(m.group("val"))
            text = _strip_sep(text[m.end():])
            continue

        # 3) bare level word: ERROR / WARN: / Warning -
        if severity is None:
            m = _RE_SEVERITY_HEAD.match(text)
            if m:
                severity = normalise_severity(m.group("val"))
                text = _strip_sep(text[m.end():])
                continue

        # 4) "payment-svc: msg" or "com.acme.DbPool - msg"
        if service is None:
            m = _RE_SERVICE_COLON.match(text) or _RE_LOGGER_DASH.match(text)
            if m and _looks_like_service(m.group("val")):
                service = m.group("val")
                text = _strip_sep(text[m.end():])
                continue

        if text == before:
            break

    return severity, service, text.strip()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


@dataclass
class ParseStats:
    """Counters describing how the input was handled."""
    total_lines: int = 0        # every line in the input (incl. blank)
    parsed: int = 0             # became a record
    continuation: int = 0       # attached to the previous record (stack traces)
    skipped: int = 0            # no timestamp -> dropped
    blank: int = 0
    skipped_samples: list = field(default_factory=list)


@dataclass
class ParseResult:
    df: pd.DataFrame
    stats: ParseStats


COLUMNS = ["line_no", "timestamp", "severity", "service", "message", "raw"]


def parse_line(line: str, default_year: int) -> Optional[dict]:
    """Parse a single line. Returns a record dict or None if unparseable."""
    found = find_timestamp(line)
    if not found:
        return None
    kind, m = found
    ts = parse_timestamp(kind, m.group(0), default_year)
    if ts is None:
        return None

    prefix = line[: m.start()]
    rest = line[m.end():]
    # Bracketed timestamps: "[2026-10-09T03:00:01Z] ..." -> drop the closing "]"
    if prefix.rstrip().endswith("[") and rest.lstrip().startswith("]"):
        prefix = prefix.rstrip()[:-1]
        rest = rest.lstrip()[1:]

    severity, service, message = split_header(rest, kind)

    # logfmt: msg="..." -> use the quoted text as the message body
    mm = _RE_MSG_KV.match(message)
    if mm:
        body = mm.group("q") if mm.group("q") is not None else mm.group("u")
        message = (body + " " + message[mm.end():]).strip()

    # A service name may precede the timestamp, e.g. docker-compose output
    # ("payment-svc_1  | 2026-...") or "[payment-svc] 2026-...".
    if service is None:
        candidate = prefix.strip().strip("[]|<>- \t")
        if candidate and _RE_SERVICE_LIKE.match(candidate) and not normalise_severity(candidate):
            service = re.sub(r"_\d+$", "", candidate)  # strip compose replica suffix

    # Fallbacks: look anywhere in the line for level/service hints.
    if severity is None:
        kv = _RE_LEVEL_KV.search(line)
        severity = normalise_severity(kv.group("val")) if kv else None
    if severity is None:
        any_sev = _RE_SEVERITY_ANY.search(message)
        severity = normalise_severity(any_sev.group("val")) if any_sev else None
    if service is None:
        kv = _RE_SERVICE_KV.search(line)
        service = kv.group("val") if kv else None

    return {
        "timestamp": ts,
        "severity": severity or "INFO",
        "service": service or "unknown",
        "message": message,
        "raw": line,
    }


def parse_lines(lines: Iterable[str], default_year: Optional[int] = None) -> ParseResult:
    """Parse an iterable of raw lines into a ParseResult."""
    default_year = default_year or datetime.now().year
    stats = ParseStats()
    records: list[dict] = []

    for idx, raw in enumerate(lines, start=1):
        stats.total_lines += 1
        line = raw.rstrip("\r\n")
        if not line.strip():
            stats.blank += 1
            continue

        record = parse_line(line, default_year)
        if record is not None:
            record["line_no"] = idx
            records.append(record)
            stats.parsed += 1
            continue

        # Stack-trace / continuation line -> glue to the previous record.
        if records and _RE_CONTINUATION.match(line):
            records[-1]["raw"] += "\n" + line
            stats.continuation += 1
            continue

        stats.skipped += 1
        if len(stats.skipped_samples) < 10:
            stats.skipped_samples.append((idx, line[:200]))

    df = pd.DataFrame.from_records(records, columns=COLUMNS)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["sev_rank"] = df["severity"].map(SEVERITY_RANK).fillna(SEVERITY_RANK["INFO"]).astype(int)
    else:
        df["sev_rank"] = pd.Series(dtype=int)
    return ParseResult(df=df, stats=stats)


def parse_text(text: str, default_year: Optional[int] = None) -> ParseResult:
    """Convenience wrapper: parse a whole file's contents."""
    return parse_lines(text.splitlines(), default_year=default_year)


if __name__ == "__main__":  # tiny manual check: python parser.py file.log
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "sample_logs/sample.log"
    with open(path, encoding="utf-8", errors="replace") as fh:
        result = parse_text(fh.read())
    print(result.stats)
    print(result.df.head(10).to_string())
