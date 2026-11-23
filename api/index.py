"""
api/index.py — LogLens FastAPI app for Vercel's Python runtime.

Thin layer: request validation + JSON serialization only. All pipeline logic
lives in ``loglens/`` (imported from the repo root, which is added to sys.path
below so the import works both locally and on Vercel).

Routes
    GET  /api/health   -> {"status": "ok"}
    POST /api/analyze  -> ranked incidents as JSON
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `import loglens` work on Vercel (root is the cwd, but be explicit)
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from typing import Literal  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from loglens.rank import DEFAULT_WEIGHTS  # noqa: E402
from loglens.service import analyze  # noqa: E402

#: Vercel's request body limit is ~4.5 MB; stay safely below it.
MAX_TEXT_BYTES = 4_000_000

app = FastAPI(
    title="LogLens API",
    description="Turn thousands of raw log lines into a handful of ranked incidents.",
    version="2.0.0",
)

TFIDF_UNAVAILABLE = "TF-IDF grouping is not available in this deployment; use Drain."


class NormaliseApiPath(BaseHTTPMiddleware):
    """Keep routes working whether Vercel forwards the original path or the
    rewritten destination.

    ``vercel.json`` rewrites ``/api/(.*)`` -> ``/api/index`` so the function
    sees the original path (``/api/analyze``). Depending on how the platform
    resolves the rewrite, the function may instead receive the destination
    path (``/api/index``). The routes below are also registered under
    ``/api/index/...`` so both work; this middleware maps the destination path
    back to the canonical one so a single handler serves both.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.scope.get("path", "")
        if path.startswith("/api/index"):
            suffix = path[len("/api/index"):]
            if suffix:
                new_path = "/api" + suffix
            else:
                # The rewrite dropped the original sub-path entirely: route by
                # method (GET is the health probe, POST is the analysis call).
                new_path = "/api/health" if request.method == "GET" else "/api/analyze"
            request.scope["path"] = new_path
            if request.scope.get("raw_path"):
                request.scope["raw_path"] = new_path.encode("utf-8")
        return await call_next(request)


app.add_middleware(NormaliseApiPath)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class Weights(BaseModel):
    count: float = Field(default=DEFAULT_WEIGHTS["count"], ge=0.0, le=1.0)
    severity: float = Field(default=DEFAULT_WEIGHTS["severity"], ge=0.0, le=1.0)
    services: float = Field(default=DEFAULT_WEIGHTS["services"], ge=0.0, le=1.0)
    growth: float = Field(default=DEFAULT_WEIGHTS["growth"], ge=0.0, le=1.0)
    start: float = Field(default=DEFAULT_WEIGHTS["start"], ge=0.0, le=1.0)


class AnalyzeRequest(BaseModel):
    text: str = Field(default="", description="Raw log text")
    min_severity: Literal["WARN", "ERROR", "INFO", "DEBUG"] = "WARN"
    method: Literal["drain", "tfidf"] = "drain"
    similarity: float = Field(default=0.5, ge=0.3, le=0.9)
    knock_on_minutes: int = Field(default=5, ge=1, le=30)
    weights: Weights = Field(default_factory=Weights)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze_endpoint(payload: AnalyzeRequest):
    """Validate, run the pipeline, return JSON. Never raises a 500 for bad logs."""
    if len(payload.text.encode("utf-8", errors="replace")) > MAX_TEXT_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "detail": (
                    "Log text is larger than 4 MB, which exceeds this deployment's request limit. "
                    "Please split the file and analyse it in parts."
                )
            },
        )

    if payload.method == "tfidf":
        # scikit-learn is intentionally not installed in the Vercel bundle.
        try:
            import sklearn  # noqa: F401
        except ImportError:
            return JSONResponse(status_code=400, content={"detail": TFIDF_UNAVAILABLE})

    try:
        return analyze(
            text=payload.text,
            min_severity=payload.min_severity,
            method=payload.method,
            similarity=payload.similarity,
            knock_on_minutes=payload.knock_on_minutes,
            weights=payload.weights.model_dump(),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse(
            status_code=500,
            content={"detail": f"Analysis failed unexpectedly: {type(exc).__name__}: {exc}"},
        )


@app.exception_handler(Exception)
def unexpected_error(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    """Return JSON (not an HTML error page) for anything unhandled."""
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal error: {type(exc).__name__}"},
    )
