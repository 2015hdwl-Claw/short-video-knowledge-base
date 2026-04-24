#!/usr/bin/env python3
"""Telegram Bot (standalone) for short-video-knowledge-base.

Runs independently from the API server. Receives Douyin video URLs
via Telegram, calls the Render API to process them, and replies.

Deploy as a separate Render service to avoid OOM on the API server.
"""

import os
import re
import sys

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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "短影音知識庫 Bot

"
        "直接貼上抖音連結，我會自動分析並建立知識卡片。

"
        "指令：
"
        "/stats - 知識庫統計
"
        "/search <關鍵字> - 搜尋知識庫
"
        "/help - 使用說明"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "使用方式：

"
        "1. 貼上抖音影片連結
"
        "   支援格式：douyin.com/... 或 v.douyin.com/...

"
        "2. Bot 自動處理（約 10-30 秒）

"
        "指令：
"
        "/stats - 查看知識庫統計
"
        "/search <關鍵字> - 搜尋知識庫"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{API_URL}/api/search", 
                params={"search_type": "all", "query": "*", "limit": 1}, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        total = data.get("total", 0)
        await update.message.reply_text(f"知識庫目前有 {total} 筆資料")
    except Exception as e:
        await update.message.reply_text(f"查詢失敗：{e}")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("請提供搜尋關鍵字
用法：/search AI 教學")
        return

    try:
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{API_URL}/api/search",
                json={"query": query, "limit": 5, "search_type": "all"}, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            await update.reply_text(f"找不到與「{query}」相關的內容")
            return

        lines = [f"搜尋「{query}」結果（{len(results)} 筆）：
"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "?")[:50]
            lines.append(f"{i}. {title}")
        await update.message.reply_text("
".join(lines))
    except Exception as e:
        await update.message.reply_text(f"搜尋失敗：{e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = DOUYIN_URL_PATTERN.findall(text)

    if not urls:
        return

    url = urls[0]
    await update.message.reply_text("處理中，請稍候...")

    try:
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{API_URL}/api/process",
                json={"url": url}, headers=headers)

        if resp.status_code == 429:
            await update.message.reply_text("處理逾時（90秒），請稍後再試。")
            return

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

            reply = "
".join([
                "--- Knowledge Card ---",
                f"Title: {title[:60]}",
                f"Author: {author}",
                f"Category: {category}",
                f"Tags: {', '.join(tags[:5]) if tags else 'N/A'}",
                f"Date: {date}",
                "",
                f"Core Points:
{points}",
                "",
                f"Likes: {likes} | Comments: {comments}",
            ])
            max_len = 4096
            if len(reply) > max_len:
                reply = reply[:max_len - 20] + "
...(已截斷)"
            await update.message.reply_text(reply)
        else:
            error = data.get("error", "未知錯誤")
            await update.message.reply_text(f"處理失敗：{error}")
    except httpx.ReadTimeout:
        await update.message.reply_text("處理逾時（90秒），API 伺服器可能正在喚醒，請稍後再試。")
    except Exception as e:
        await update.message.reply_text(f"處理失敗：{e}")


def main():
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


if __name__ == "__main__":
    main()
