"""Short Video Knowledge Base API.

Exposes pipeline.py as HTTP endpoints for external triggers.

Endpoints:
    POST /api/process       - Process a single video URL
    POST /api/process/missing - Batch process videos missing content
    GET  /health            - Health check
"""

import asyncio
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))

from pipeline import process_url, process_missing, PipelineResult

ADMIN_URL = "https://2015hdwl-claw.github.io/short-video-knowledge-base/admin.html"

app = FastAPI(title="Short Video Knowledge Base API", version="1.0.0")


class ProcessRequest(BaseModel):
    url: str
    cookie: str = ""
    dry_run: bool = False


@app.get("/")
async def root():
    return RedirectResponse(ADMIN_URL)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "short-video-knowledge-base"}


@app.post("/api/process")
async def api_process(req: ProcessRequest):
    cookie = req.cookie or os.getenv("DOUYIN_COOKIE", "")
    result = await process_url(req.url, cookie=cookie, dry_run=req.dry_run)
    if not result.success and result.error:
        return {"success": False, "error": result.error}
    return {
        "success": result.success,
        "aweme_id": result.aweme_id,
        "title": result.title,
        "author": result.author,
        "category": result.category,
        "tags": result.tags,
        "core_points": result.core_points,
        "date": result.date,
        "has_subtitle": result.has_subtitle,
        "statistics": result.statistics,
    }


@app.post("/api/process/missing")
async def api_process_missing(dry_run: bool = False):
    cookie = os.getenv("DOUYIN_COOKIE", "")
    results = await asyncio.to_thread(process_missing, cookie, dry_run=dry_run)
    return {
        "processed": len(results),
        "results": [
            {
                "success": r.success,
                "title": r.title,
                "error": r.error,
            }
            for r in results
        ],
    }
