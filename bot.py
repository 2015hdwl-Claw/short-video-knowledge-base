#!/usr/bin/env python3
"""Telegram Bot for short-video-knowledge-base.

Receives Douyin video URLs via Telegram, processes them through
the knowledge pipeline, and replies with knowledge cards.

Integrated into FastAPI via background thread polling.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))
from pipeline import process_url, _load_json

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

DOUYIN_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:douyin\.com|v\.douyin\.com)/[^\s]+"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "短影音知識庫 Bot\n\n"
        "直接貼上抖音連結，我會自動分析並建立知識卡片。\n\n"
        "指令：\n"
        "/stats - 知識庫統計\n"
        "/search <關鍵字> - 搜尋知識庫\n"
        "/help - 使用說明"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "使用方式：\n\n"
        "1. 貼上抖音影片連結\n"
        "   支援格式：douyin.com/... 或 v.douyin.com/...\n\n"
        "2. Bot 自動處理（約 10-30 秒）\n"
        "   - 擷取影片資訊\n"
        "   - 語音轉文字 / 關鍵幀分析\n"
        "   - LLM 產生摘要\n"
        "   - 分類並存入知識庫\n\n"
        "指令：\n"
        "/stats - 查看知識庫統計\n"
        "/search <關鍵字> - 搜尋知識庫"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = _load_json()
        videos = data.get("videos", [])
        total = len(videos)

        cat_counts = {}
        for v in videos:
            cat = v.get("category", "未分類")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        lines = [f"知識庫統計：共 {total} 部影片\n"]
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}：{count}")
        lines.append(f"\n最近新增：")
        for v in videos[-3:]:
            title = v.get("title", "?")[:40]
            date = v.get("date", "")
            lines.append(f"  [{date}] {title}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"讀取知識庫失敗：{e}")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("請提供搜尋關鍵字\n用法：/search AI 教學")
        return

    try:
        from search import search_all
        results = search_all(query, limit=5)

        if not results:
            await update.message.reply_text(f"找不到與「{query}」相關的內容")
            return

        lines = [f"搜尋「{query}」結果（{len(results)} 筆）：\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "?")[:50]
            source = r.get("source", "video")
            score = r.get("score", 0)
            lines.append(f"{i}. [{source}] {title}")

        await update.message.reply_text("\n".join(lines))
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
        result = await process_url(url)

        if result.success:
            reply = result.to_line_reply()
            max_len = 4096
            if len(reply) > max_len:
                reply = reply[:max_len - 20] + "\n...(已截斷)"
            await update.message.reply_text(reply)
        else:
            error_msg = result.error or "未知錯誤"
            if "Cookie expired" in error_msg or "Cookie" in error_msg:
                await update.message.reply_text(
                    "Cookie 已過期，請管理員更新 DOUYIN_COOKIE。"
                )
            else:
                await update.message.reply_text(f"處理失敗：{error_msg}")
    except Exception as e:
        await update.message.reply_text(f"處理失敗：{e}")


def build_bot_application():
    if not BOT_TOKEN:
        return None
    print("[bot] Building Telegram bot application...")
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("search", cmd_search))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application


async def start_bot(application):
    if not application:
        return
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    print("[bot] Telegram bot polling started")


async def stop_bot(application):
    if not application:
        return
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
