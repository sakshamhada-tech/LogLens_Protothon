"""
dev.py — local development launcher (NOT deployed).

Runs the same FastAPI app Vercel runs, and additionally serves ``public/``
as static files so the UI and the API live on one origin — the same
arrangement Vercel gives you in production (static hosting + function).

    python dev.py            # http://127.0.0.1:8000

For a production-faithful environment use ``vercel dev`` instead.
"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

from api.index import app

PUBLIC_DIR = Path(__file__).resolve().parent / "public"

# Mounted last, so the /api routes registered in api/index.py match first.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
