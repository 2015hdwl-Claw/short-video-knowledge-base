#!/usr/bin/env python3
"""Telegram Bot (standalone) for short-video-knowledge-base."""

import json, os, re, sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
API_URL = os.getenv("API_URL", "https://short-video-knowledge-base.onrender.com")
API_KEY = os.getenv("API_KEY", "")

DOUYIN_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:douyin\.com|v\.douyin\.com)/[^\s]+"
)

_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_dir, "bot_messages.json"), "r", encoding="utf-8") as _f:
    MSG = json.load(_f)


async def cmd_start(update, context):
    await update.message.reply_text(MSG["start"])


async def cmd_help(update, context):
    await update.message.reply_text(MSG["help"])


async def cmd_stats(update, context):
    try:
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{API_URL}/api/search",
                params={"search_type": "all", "query": "*", "limit": 1},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        total = data.get("total", 0)
        await update.message.reply_text(MSG["stats"].format(total=total))
    except Exception as e:
        await update.message.reply_text(MSG["stats_fail"].format(e=e))


async def cmd_search(update, context):
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text(MSG["search_hint"])
        return
    try:
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{API_URL}/api/search",
                json={"query": query, "limit": 5, "search_type": "all"},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results", {})
        merged = results.get("merged", []) if isinstance(results, dict) else results
        if not merged:
            await update.message.reply_text(MSG["not_found"].format(query=query))
            return
        lines = [MSG["search_results"].format(query=query, count=len(merged))]
        for i, r in enumerate(merged, 1):
            title = r.get("title", "?")[:50]
            lines.append(f"{i}. {title}")
        await update.message.reply_text(chr(10).join(lines))
    except Exception as e:
        await update.message.reply_text(MSG["search_fail"].format(e=e))


async def handle_message(update, context):
    text = update.message.text or ""
    urls = DOUYIN_URL_PATTERN.findall(text)
    if not urls:
        return
    url = urls[0]
    await update.message.reply_text(MSG["processing"])
    try:
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        async with httpx.AsyncClient(timeout=120) as client:
            for attempt in range(5):
                resp = await client.post(
                    f"{API_URL}/api/process",
                    json={"url": url},
                    headers=headers,
                )
                if resp.status_code not in (502, 503):
                    break
                import asyncio as _a
                print(f"  [bot] API 502/503, retry {attempt+1}/5...")
                await _a.sleep(15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            title = data.get("title", "?")
            author = data.get("author", "?")
            category = data.get("category", "")
            tags = data.get("tags", [])
            points = data.get("core_points", "")[:300]
            stats = data.get("statistics", {})
            likes = stats.get("digg_count", 0)
            comments = stats.get("comment_count", 0)
            date = data.get("date", "")
            tag_str = ", ".join(tags[:5]) if tags else "N/A"
            reply = chr(10).join([
                "--- Knowledge Card ---",
                f"Title: {title[:60]}",
                f"Author: {author}",
                f"Category: {category}",
                f"Tags: {tag_str}",
                f"Date: {date}",
                "",
                f"Core Points:" + chr(10) + f"{points}",
                "",
                f"Likes: {likes} | Comments: {comments}",
            ])
            max_len = 4096
            if len(reply) > max_len:
                reply = reply[:max_len - 20] + chr(10) + "...(truncated)"
            await update.message.reply_text(reply)
        else:
            error = data.get("error", "unknown error")
            await update.message.reply_text(MSG["process_fail"].format(e=error))
    except httpx.ReadTimeout:
        await update.message.reply_text(MSG["timeout"])
    except Exception as e:
        await update.message.reply_text(MSG["process_fail"].format(e=e))


def run_bot():
    if not BOT_TOKEN:
        print("[bot] TELEGRAM_BOT_TOKEN not set, exiting")
        sys.exit(1)
    print(f"[bot] Starting standalone bot... (API: {API_URL})")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)


def run_with_health_server():
    import threading, uvicorn
    from fastapi import FastAPI
    PORT = int(os.getenv("PORT", "10000"))
    health_app = FastAPI()
    @health_app.get("/health")
    @health_app.head("/health")
    async def health():
        return {"status": "healthy", "service": "telegram-bot"}
    def _serve():
        uvicorn.run(health_app, host="0.0.0.0", port=PORT, log_level="warning")
    server_thread = threading.Thread(target=_serve, daemon=True)
    server_thread.start()
    print(f"[bot] Health server on port {PORT}")
    try:
        run_bot()
    except Exception as e:
        print(f"[bot] Bot crashed: {e}, health server still running")


if __name__ == "__main__":
    run_with_health_server()

