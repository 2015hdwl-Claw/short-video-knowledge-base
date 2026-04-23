"""Short Video Knowledge Base API.

Exposes pipeline.py as HTTP endpoints for external triggers.

Endpoints:
    POST /api/process       - Process a single video URL
    POST /api/process/missing - Batch process videos missing content
    POST /api/query         - Knowledge query engine
    POST /api/search        - BM25 search
    POST /api/rebuild-wiki  - Trigger wiki rebuild
    POST /api/weekly-digest - Trigger weekly digest
    GET  /api/export        - Export Obsidian vault as tar.gz
    POST /api/webhook/weekly-digest - cron-job.org webhook
    GET  /health            - Health check
"""

import asyncio
import io
import os
import sys
import tarfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))

from pipeline import process_url, process_missing, PipelineResult

ADMIN_URL = "https://2015hdwl-claw.github.io/short-video-knowledge-base/admin.html"
API_KEY = os.getenv("API_KEY", "")
TIMEOUT_DEFAULT = 60
TIMEOUT_WIKI_REBUILD = 120
TIMEOUT_DEFAULT = 60
TIMEOUT_WIKI_REBUILD = 120
WIKI_DIR = REPO / "wiki"

app = FastAPI(title="Short Video Knowledge Base API", version="2.0.0")


# --- Auth middleware ---

@app.middleware("http")
async def api_auth(request: Request, call_next):
    """API key auth for protected endpoints. /api/process is exempt (Telegram bot)."""
    if request.url.path.startswith("/api/") and request.url.path != "/api/process":
        if request.url.path == "/api/webhook/weekly-digest":
            # Webhook uses X-Webhook-Secret header
            secret = os.getenv("WEBHOOK_SECRET", "")
            if not secret:
                return JSONResponse(status_code=401, content={"detail": "WEBHOOK_SECRET not configured"})
            if secret:
                hdr = request.headers.get("X-Webhook-Secret", "")
                if hdr != secret:
                    return JSONResponse(status_code=401, content={"detail": "Invalid webhook secret"})
        else:
            key = request.headers.get("X-API-Key", "")
            if not API_KEY:
                return JSONResponse(status_code=401, content={"detail": "API_KEY not configured"})
            if key != API_KEY:
                return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)


# --- Request models ---

class ProcessRequest(BaseModel):
    url: str
    cookie: str = ""
    dry_run: bool = False


class QueryRequest(BaseModel):
    question: str
    limit: int = 10


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    search_type: str = "all"  # all | videos | wiki


# --- Routes ---

@app.get("/")
async def root():
    return RedirectResponse(ADMIN_URL)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "short-video-knowledge-base", "version": "2.0.0"}


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
    results = await asyncio.wait_for(asyncio.to_thread(process_missing, cookie, dry_run=dry_run), timeout=TIMEOUT_DEFAULT)
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


@app.post("/api/query")
async def api_query(req: QueryRequest):
    """Knowledge query engine: BM25 retrieval + LLM synthesis."""
    from query_engine import query_knowledge_base
    result = await asyncio.wait_for(asyncio.to_thread(
        query_knowledge_base, req.question, req.limit
    ), timeout=TIMEOUT_DEFAULT)
    return {"success": True, **result}


@app.post("/api/search")
async def api_search(req: SearchRequest):
    """BM25 search across videos and/or wiki."""
    from search import search_videos, search_wiki, search_all
    results = {}
    if req.search_type in ("all", "videos"):
        results["videos"] = await asyncio.to_thread(
            search_videos, req.query, req.limit
        )
    if req.search_type in ("all", "wiki"):
        results["wiki"] = await asyncio.to_thread(
            search_wiki, req.query, req.limit
        )
    if req.search_type == "all":
        merged = await asyncio.wait_for(asyncio.to_thread(search_all, req.query, req.limit), timeout=TIMEOUT_DEFAULT)
        results["merged"] = merged
    return {"success": True, "results": results}


@app.post("/api/rebuild-wiki")
async def api_rebuild_wiki(v2: bool = False):
    """Trigger wiki rebuild."""
    def _rebuild():
        from rebuild_concepts import main as rebuild_main
        import argparse
        args = argparse.Namespace(v2=v2, push=False, json=False)
        rebuild_main()
        # Count pages
        concepts_dir = WIKI_DIR / "concepts"
        pages = list(concepts_dir.glob("*.md")) if concepts_dir.exists() else []
        return len(pages)

    pages_rebuilt = await asyncio.wait_for(asyncio.to_thread(_rebuild), timeout=TIMEOUT_WIKI_REBUILD)
    return {"success": True, "pages_rebuilt": pages_rebuilt}


@app.post("/api/weekly-digest")
async def api_weekly_digest():
    """Trigger weekly digest generation."""
    def _digest():
        from weekly_digest import generate_weekly_digest
        return generate_weekly_digest(dry_run=False)

    result = await asyncio.wait_for(asyncio.to_thread(_digest), timeout=TIMEOUT_DEFAULT)
    return {"success": True, **result}


@app.get("/api/export")
async def api_export():
    """Export wiki directory as a tar.gz download."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if WIKI_DIR.exists():
            for fpath in WIKI_DIR.rglob("*"):
                if fpath.is_file():
                    tar.add(str(fpath), arcname=str(fpath.relative_to(REPO)))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={"Content-Disposition": "attachment; filename=wiki-export.tar.gz"},
    )


@app.post("/api/webhook/weekly-digest")
async def api_webhook_weekly_digest():
    """Webhook endpoint for cron-job.org to trigger weekly digest."""
    def _run():
        from weekly_digest import generate_weekly_digest
        return generate_weekly_digest(dry_run=False)

    result = await asyncio.wait_for(asyncio.to_thread(_run), timeout=TIMEOUT_DEFAULT)
    return {"success": True, "digest_path": result.get("digest_path"), "new_count": result.get("new_count", 0), "total": result.get("total", 0)}
