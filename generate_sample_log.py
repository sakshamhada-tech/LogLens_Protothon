#!/usr/bin/env python3
"""
generate_sample_log.py — build a realistic multi-service log for the LogLens demo.

    python generate_sample_log.py                      # 10,000 lines -> sample_logs/sample.log
    python generate_sample_log.py --lines 20000 --seed 7 --out my.log

Story line (60 minutes of logs from five services)
--------------------------------------------------
* 02:30 - 03:30 UTC: normal traffic. ~80 % of lines are INFO request logs plus a
  steady trickle of harmless WARN/ERROR noise (slow queries, cache misses,
  invalid JWTs, SMTP retries) that has been there all along.
* 02:52:00 **root cause**: the primary database behind ``payment-svc`` starts
  timing out. Within ~4 minutes the failure cascades:

    payment-svc      ERROR  Database connection timeout ...        (t + 0 s)
    checkout-svc     ERROR  Upstream timeout calling payment-svc   (t + 18 s)
    payment-svc      WARN   Connection pool exhausted ...          (t + 25 s)
    api-gateway      ERROR  502 Bad Gateway from checkout-svc      (t + 40 s)
    checkout-svc +   WARN   Request queue saturated ...            (t + 70 s / 110 s)
      api-gateway
    notification-svc ERROR  Failed to publish event order.paid     (t + 95 s)
    payment-svc      CRITICAL Circuit breaker OPEN for db-primary  (t + 3 min)
    inventory-svc    WARN   Reservation hold expired ...           (t + 4 min)

Each service logs in its own format (bracketed, "service:" and logfmt) and a
few deliberately unparseable lines (banners, a stack trace) are sprinkled in
to exercise the tolerant parser. Everything is seeded, so the output is
reproducible.
"""

from __future__ import annotations

import argparse
import math
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

SERVICES = ["api-gateway", "checkout-svc", "payment-svc", "inventory-svc", "notification-svc"]


# --------------------------------------------------------------------------- #
# Per-service line formats (deliberately different, like a real aggregation)
# --------------------------------------------------------------------------- #

def format_line(service: str, ts: datetime, level: str, msg: str) -> str:
    iso_ms = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
    if service == "api-gateway":                       # "service:" style, comma millis
        return f"{ts.strftime('%Y-%m-%d %H:%M:%S')},{ts.microsecond // 1000:03d} {level} {service}: {msg}"
    if service == "notification-svc":                  # logfmt
        return f'ts={ts.strftime("%Y-%m-%dT%H:%M:%SZ")} level={level.lower()} service={service} msg="{msg}"'
    return f"{iso_ms} {level} [{service}] {msg}"       # bracketed service


# --------------------------------------------------------------------------- #
# Message factories
# --------------------------------------------------------------------------- #

class Factory:
    """Random-but-plausible message content."""

    def __init__(self, rng: random.Random):
        self.r = rng

    def oid(self) -> int:            return self.r.randint(100000, 999999)
    def cid(self) -> int:            return self.r.randint(1000, 99999)
    def sku(self) -> str:            return f"sku-{self.r.randint(1000, 9999)}"
    def ms(self, lo=5, hi=250):      return self.r.randint(lo, hi)
    def uid(self) -> str:            return str(uuid.UUID(int=self.r.getrandbits(128)))
    def hexid(self, n=12) -> str:    return f"{self.r.getrandbits(n * 4):0{n}x}"
    def ip(self) -> str:             return f"10.0.{self.r.randint(1, 4)}.{self.r.randint(10, 60)}"

    # -- normal INFO traffic -------------------------------------------------
    def info(self, service: str) -> str:
        r = self.r
        if service == "api-gateway":
            return r.choice([
                lambda: f"GET /api/orders/{self.oid()} 200 {self.ms()}ms",
                lambda: f"POST /checkout 201 {self.ms(40, 600)}ms",
                lambda: f"GET /api/products/{self.sku()} 200 {self.ms()}ms",
                lambda: f"GET /api/cart/{self.uid()} 200 {self.ms()}ms",
                lambda: f"Health check OK (uptime {r.randint(1000, 999999)}s)",
            ])()
        if service == "checkout-svc":
            return r.choice([
                lambda: f"Order {self.oid()} created for customer {self.cid()} ({r.randint(1, 6)} items, total {r.randint(5, 900)}.{r.randint(0, 99):02d} USD)",
                lambda: f"Cart {self.uid()} updated ({r.randint(1, 9)} items)",
                lambda: f"Applied coupon {r.choice(['SAVE10', 'WELCOME', 'FREESHIP', 'VIP20'])} to order {self.oid()}",
            ])()
        if service == "payment-svc":
            return r.choice([
                lambda: f"Processed payment txn_{self.hexid(10)} for order {self.oid()} in {self.ms(80, 400)}ms",
                lambda: f"Card tokenised for customer {self.cid()} (bin={r.randint(400000, 559999)})",
                lambda: f"Refund {self.uid()} issued for order {self.oid()}",
            ])()
        if service == "inventory-svc":
            return r.choice([
                lambda: f"Reserved {r.randint(1, 5)} units of {self.sku()} for order {self.oid()}",
                lambda: f"Stock level for {self.sku()} is {r.randint(0, 500)}",
                lambda: f"Released reservation {self.uid()} (order {self.oid()} fulfilled)",
            ])()
        return r.choice([  # notification-svc
            lambda: f"Sent order confirmation email to user{r.randint(1, 99999)}@example.com (order {self.oid()})",
            lambda: f"Push notification delivered to device {self.hexid(16)}",
            lambda: f"Published event order.created (partition {r.randint(0, 11)}, offset {r.randint(10**6, 10**7)})",
        ])()

    # -- steady background noise (present the whole hour) --------------------
    def background(self):
        """(service, level, message, rate-per-minute) generators."""
        r = self.r
        return [
            ("inventory-svc", "WARN", lambda: f"Slow query took {r.randint(1000, 2900)}ms: SELECT * FROM stock WHERE sku = '{self.sku()}'", 1.5),
            ("checkout-svc", "WARN", lambda: f"Cache miss for key cart:{self.uid()} (ttl expired)", 2.0),
            ("api-gateway", "ERROR", lambda: f"Invalid JWT token for user u{r.randint(10**4, 10**6)}: signature mismatch", 0.4),
            ("notification-svc", "WARN", lambda: f"Retrying connection to smtp-relay (attempt {r.randint(1, 3)}/3)", 0.5),
        ]

    # -- the incident ----------------------------------------------------------
    def incident(self):
        """(service, level, message, start-offset-s, ramp-s, plateau-per-minute)."""
        r = self.r
        return [
            ("payment-svc", "ERROR",
             lambda: f"Database connection timeout after {r.choice([5000, 5001, 5003, 5010, 5021])}ms (pool=primary, host={self.ip()}:5432)",
             0, 180, 26),
            ("checkout-svc", "ERROR",
             lambda: f"Upstream timeout calling payment-svc POST /v1/charge (order={self.oid()}) after {r.randint(10000, 10050)}ms",
             18, 180, 20),
            ("payment-svc", "WARN",
             lambda: f"Connection pool exhausted: 50/50 in use, {r.randint(8, 40)} requests waiting",
             25, 120, 7),
            ("api-gateway", "ERROR",
             lambda: f"502 Bad Gateway from checkout-svc for POST /checkout (req={self.hexid(8)}) in {r.randint(10010, 10090)}ms",
             40, 180, 18),
            # the same symptom in two services -> one group spanning both
            ("checkout-svc", "WARN",
             lambda: f"Request queue saturated: 200/200 worker threads busy, {r.randint(20, 300)} requests queued",
             70, 240, 3),
            ("api-gateway", "WARN",
             lambda: f"Request queue saturated: 200/200 worker threads busy, {r.randint(20, 300)} requests queued",
             110, 240, 3),
            ("notification-svc", "ERROR",
             lambda: f"Failed to publish event order.paid (order {self.oid()}): producer timeout after 3000ms",
             95, 240, 7),
            ("payment-svc", "CRITICAL",
             lambda: f"Circuit breaker OPEN for db-primary (failures={r.randint(50, 80)}, next retry in 30s)",
             180, 1, 0.35),
            ("inventory-svc", "WARN",
             lambda: f"Reservation hold expired for order {self.oid()} - payment never confirmed, releasing {r.randint(1, 5)} units of {self.sku()}",
             240, 300, 5),
        ]


# --------------------------------------------------------------------------- #
# Event generation
# --------------------------------------------------------------------------- #

def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's algorithm — fine for the small rates used here."""
    if lam <= 0:
        return 0
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def stream(rng, start, end, rate_per_min, start_offset=0.0, ramp_s=1.0, force_first=False):
    """Timestamps of a Poisson process whose rate ramps up linearly after start_offset.

    With ``force_first`` the first event lands (almost) exactly at the offset, so
    the order in which the incident's streams begin is unambiguous.
    """
    out = []
    t = start + timedelta(seconds=start_offset)
    if force_first and t < end:
        out.append(t + timedelta(seconds=rng.random() * 2))
    while t < end:
        elapsed = (t - start).total_seconds() - start_offset
        rate = rate_per_min * min(1.0, max(0.15, elapsed / max(ramp_s, 1.0)))
        for _ in range(poisson(rng, rate)):
            out.append(t + timedelta(seconds=rng.random() * 60))
        t += timedelta(minutes=1)
    return [x for x in out if x < end]


STACK_TRACE = (
    "java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 5000ms.\n"
    "    at com.zaxxer.hikari.pool.HikariPool.createTimeoutException(HikariPool.java:696)\n"
    "    at com.acme.payment.db.ChargeRepository.insert(ChargeRepository.java:88)\n"
    "Caused by: java.net.SocketTimeoutException: connect timed out"
)


def generate(lines: int, seed: int, start: datetime, duration_min: int, incident_at_min: int) -> list[str]:
    rng = random.Random(seed)
    f = Factory(rng)
    end = start + timedelta(minutes=duration_min)
    incident_start = start + timedelta(minutes=incident_at_min)
    events: list[tuple[datetime, str]] = []  # (timestamp, formatted line(s))

    # 1) incident streams (root cause + knock-on effects)
    first_root_error = None
    for service, level, make, offset, ramp, plateau in f.incident():
        for ts in stream(rng, incident_start, end, plateau, offset, ramp, force_first=True):
            events.append((ts, format_line(service, ts, level, make())))
            if offset == 0 and (first_root_error is None or ts < first_root_error):
                first_root_error = ts
    # attach a stack trace to the very first root-cause line
    for i, (ts, line) in enumerate(events):
        if ts == first_root_error:
            events[i] = (ts, line + "\n" + STACK_TRACE)
            break

    # 2) steady background noise across the whole window
    for service, level, make, rate in f.background():
        for ts in stream(rng, start, end, rate):
            events.append((ts, format_line(service, ts, level, make())))

    # 3) a few lines the parser should skip (not crash on)
    banners = [
        (start + timedelta(seconds=1), "===== log export: 5 services, cluster prod-eu-1 ====="),
        (start + timedelta(minutes=duration_min // 2), "--- logrotate: compressed previous segment ---"),
    ]
    events.extend(banners)

    # 4) fill the remainder with normal INFO traffic so the file has exactly `lines` lines
    used = sum(line.count("\n") + 1 for _, line in events)
    n_info = max(lines - used, 0)
    weights = [0.34, 0.2, 0.18, 0.16, 0.12]  # api-gateway is chattiest
    for _ in range(n_info):
        service = rng.choices(SERVICES, weights)[0]
        ts = start + timedelta(seconds=rng.random() * duration_min * 60)
        events.append((ts, format_line(service, ts, "INFO", f.info(service))))

    events.sort(key=lambda e: e[0])
    out = [line for _, line in events]
    # trim (only if the incident alone exceeded the budget) and report
    text = "\n".join(out).split("\n")[:lines]
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", type=int, default=10000, help="total number of lines (default 10000)")
    ap.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    ap.add_argument("--out", default="sample_logs/sample.log", help="output path")
    ap.add_argument("--start", default="2026-10-09T02:30:00", help="window start (UTC, ISO format)")
    ap.add_argument("--duration", type=int, default=60, help="window length in minutes")
    ap.add_argument("--incident-at", type=int, default=22, help="minutes into the window when the DB starts failing")
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start)
    text = generate(args.lines, args.seed, start, args.duration, args.incident_at)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(text) + "\n", encoding="utf-8")

    incident = start + timedelta(minutes=args.incident_at)
    print(f"wrote {len(text):,} lines to {out}")
    print(f"window   : {start:%Y-%m-%d %H:%M} -> {start + timedelta(minutes=args.duration):%H:%M} UTC")
    print(f"root cause: payment-svc database timeouts starting {incident:%H:%M:%S}, cascading to "
          f"checkout-svc, api-gateway, notification-svc and inventory-svc")


if __name__ == "__main__":
    main()
