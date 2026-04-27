#!/usr/bin/env python3
"""Telegram Bot (standalone) for short-video-knowledge-base.

Runs independently from the API server. Receives Douyin video URLs
via Telegram, calls the Render API to process them, and replies.

Deploy as a separate Render service to avoid OOM on the API server.
"""

import asyncio
import json
import os
import re
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import assistant

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
API_URL = os.getenv("API_URL", "https://short-video-knowledge-base.onrender.com")
API_KEY = os.getenv("API_KEY", "")

CLASSIFIER_API_KEY = os.getenv("CLASSIFIER_API_KEY", "")
CLASSIFIER_BASE_URL = os.getenv("CLASSIFIER_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "glm-4.7-flash")

DOUYIN_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:douyin\.com|v\.douyin\.com)/[^\s]+"
)

_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_dir, "bot_messages.json"), "r", encoding="utf-8") as _f:
    MSG = json.load(_f)

_conversation_state: dict = {}
DISCUSSION_WINDOW = 300  # seconds: treat input as discussion within this window after AI analysis

NL = "\n"


def _m(key, **kw):
    t = MSG.get(key, key)
    for k, v in kw.items():
        t = t.replace("{" + k + "}", str(v))
    return t


# --- AI analysis via GLM ---

async def _analyze_note(text):
    prompt = (
        "You are a personal AI assistant. Analyze the following user note."
        + NL
        + 'Return JSON with exactly these keys:{"category": "Work|Study|Tech|Life|Finance|Health|Other", "tags": ["tag1","tag2"], "analysis": "深入分析回饋，2-3段，使用繁體中文"}'
        + NL
        + NL
        + "User note:"
        + NL
        + text
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                CLASSIFIER_BASE_URL + "chat/completions",
                headers={
                    "Authorization": "Bearer " + CLASSIFIER_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "model": CLASSIFIER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        print(f"  [bot] AI analysis error: {e}")
        return {"category": "Other", "tags": [], "analysis": ""}


async def _continue_discussion(text, note_content, history):
    messages = [
        {
            "role": "system",
            "content": (
                "你是使用者的個人 AI 助手。使用者正在針對一則筆記進行討論。"
                "請用繁體中文回覆，給予深入、有見地的分析與建議。"
            ),
        },
        {"role": "user", "content": "原始筆記:" + NL + note_content},
    ]
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["text"]})
    messages.append({"role": "user", "content": text})

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                CLASSIFIER_BASE_URL + "chat/completions",
                headers={
                    "Authorization": "Bearer " + CLASSIFIER_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "model": CLASSIFIER_MODEL,
                    "messages": messages,
                    "temperature": 0.7,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [bot] Discussion error: {e}")
        return "AI 回覆失敗，請稍後再試。"


# --- Video commands ---

async def cmd_start(update, context):
    await update.message.reply_text(MSG.get("start", "Hello!"))


async def cmd_help(update, context):
    await update.message.reply_text(MSG.get("help", "Help"))


async def cmd_stats(update, context):
    try:
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                API_URL + "/api/search",
                params={"search_type": "all", "query": "*", "limit": 1},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        total = data.get("total", 0)
        await update.message.reply_text(_m("stats", total=total))
    except Exception as e:
        await update.message.reply_text(_m("stats_fail", e=e))


async def cmd_search(update, context):
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text(MSG.get("search_hint", ""))
        return
    try:
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                API_URL + "/api/search",
                json={"query": query, "limit": 5, "search_type": "all"},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results", {})
        merged = results.get("merged", []) if isinstance(results, dict) else results
        if not merged:
            await update.message.reply_text(_m("not_found", query=query))
            return
        lines = [_m("search_results", query=query, count=len(merged))]
        for i, r in enumerate(merged, 1):
            title = r.get("title", "?")[:50]
            lines.append(str(i) + ". " + title)
        await update.message.reply_text(NL.join(lines))
    except Exception as e:
        await update.message.reply_text(_m("search_fail", e=e))


# --- Note commands ---

async def cmd_notes(update, context):
    category = " ".join(context.args) if context.args else None
    notes = assistant.list_notes(category=category, limit=20)
    if not notes:
        await update.message.reply_text(MSG.get("note_empty", "No notes found"))
        return
    lines = [_m("note_list_header", count=len(notes))]
    for n in notes:
        tags = " ".join("#" + str(t) for t in n.get("tags", [])[:3])
        line = _m(
            "note_list_item",
            id=n["id"],
            category=n.get("category", "?"),
            tags=tags,
            content=n.get("content", "")[:60],
        )
        lines.append(line)
    await update.message.reply_text(NL.join(lines))


async def cmd_note_help(update, context):
    await update.message.reply_text(MSG.get("note_help", ""))


async def cmd_delete(update, context):
    if not context.args:
        await update.message.reply_text(MSG.get("note_delete_hint", ""))
        return
    try:
        note_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(MSG.get("note_delete_hint", ""))
        return
    note = assistant.get_note(note_id)
    if not note:
        await update.message.reply_text(_m("not_found", query="#" + str(note_id)))
        return
    confirm = _m("note_delete_confirm", id=note_id)
    confirm += NL + note.get("content", "")[:80]
    context.user_data["pending_delete"] = note_id
    await update.message.reply_text(confirm)


# --- Handlers ---

async def handle_video(update, context, url):
    await update.message.reply_text(MSG.get("processing", "Processing..."))
    try:
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        for attempt in range(5):
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    API_URL + "/api/process",
                    json={"url": url},
                    headers=headers,
                )
            if resp.status_code not in (502, 503):
                break
            print(f"  [bot] API 502/503, retry {attempt+1}/5...")
            await asyncio.sleep(15)
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
            tag_str = ", ".join(str(t) for t in tags[:5]) if tags else "N/A"
            reply = NL.join([
                "--- Knowledge Card ---",
                "Title: " + str(title)[:60],
                "Author: " + str(author),
                "Category: " + str(category),
                "Tags: " + tag_str,
                "Date: " + str(date),
                "",
                "Core Points:",
                str(points),
                "",
                "Likes: " + str(likes) + " | Comments: " + str(comments),
            ])
            max_len = 4096
            if len(reply) > max_len:
                reply = reply[: max_len - 20] + NL + "...(truncated)"
            await update.message.reply_text(reply)
        else:
            error = data.get("error", "unknown error")
            await update.message.reply_text("Processing failed: " + str(error))
    except httpx.ReadTimeout:
        await update.message.reply_text(MSG.get(
            "timeout",
            "Processing timeout (90s), API server may be waking up. Try again later.",
        ))
    except Exception as e:
        await update.message.reply_text(_m("process_fail", e=e))


async def handle_note(update, context):
    text = (update.message.text or "").strip()
    if not text:
        return
    chat_id = update.message.chat_id
    await update.message.reply_text(MSG.get("processing", "Processing..."))

    ai = await _analyze_note(text)
    note = assistant.add_note(
        content=text,
        chat_id=chat_id,
        ai_analysis=ai.get("analysis", ""),
        category=ai.get("category", "Other"),
        tags=ai.get("tags", []),
    )

    reply = _m("note_saved", id=note["id"])
    reply += NL + "[" + note["category"] + "]"
    if note.get("tags"):
        reply += " #" + " #".join(str(t) for t in note["tags"][:5])
    if ai.get("analysis"):
        _conversation_state[chat_id] = {
            "note_id": note["id"],
            "note_content": text,
            "history": [],
        }
        reply += NL + NL + "--- " + MSG.get("note_ai_header", "AI Analysis:") + " ---" + NL
        reply += ai["analysis"]
        reply += NL + NL + MSG.get("note_discuss_hint", "Reply to continue discussing")
    max_len = 4096
    if len(reply) > max_len:
        reply = reply[: max_len - 20] + NL + "...(truncated)"
    await update.message.reply_text(reply)


async def handle_discussion(update, context):
    text = (update.message.text or "").strip()
    chat_id = update.message.chat_id
    state = _conversation_state.get(chat_id)
    if not state:
        return

    history = state["history"]
    history.append({"role": "user", "text": text})
    ai_reply = await _continue_discussion(text, state["note_content"], history)
    history.append({"role": "assistant", "text": ai_reply})

    max_len = 4096
    if len(ai_reply) > max_len:
        ai_reply = ai_reply[: max_len - 20] + NL + "...(truncated)"
    await update.message.reply_text(ai_reply)

    assistant.append_discussion(state["note_id"], text, ai_reply)


async def handle_message(update, context):
    text = update.message.text or ""

    # 1. Douyin URL
    urls = DOUYIN_URL_PATTERN.findall(text)
    if urls:
        await handle_video(update, context, urls[0])
        return

    chat_id = update.message.chat_id

    # 2. Reply to bot message -> always treat as discussion
    is_reply_to_bot = (
        update.message.reply_to_message
        and update.message.reply_to_message.from_user
        and update.message.reply_to_message.from_user.is_bot
    )

    # 3. Check discussion window (time-based or reply-based)
    in_discussion = False
    if is_reply_to_bot or chat_id in _conversation_state:
        in_discussion = True
    else:
        # No in-memory state — check notes.json for recent note with AI analysis
        notes = assistant.list_notes(limit=1)
        if notes and notes[0].get("source") == "telegram" and notes[0].get("ai_analysis"):
            import time as _time
            from datetime import datetime, timezone, timedelta
            tz = timezone(timedelta(hours=8))
            note_time_str = notes[0].get("date", "") + "T" + notes[0].get("time", "00:00")
            try:
                note_time = datetime.strptime(note_time_str, "%Y-%m-%dT%H:%M").replace(tzinfo=tz)
                elapsed = _time.time() - note_time.timestamp()
                if elapsed < DISCUSSION_WINDOW:
                    in_discussion = True
                    _conversation_state[chat_id] = {
                        "note_id": notes[0].get("id", 0),
                        "note_content": notes[0].get("content", ""),
                        "history": [{"role": "assistant", "text": notes[0]["ai_analysis"]}],
                    }
            except (ValueError, OSError):
                pass

    if in_discussion:
        if chat_id not in _conversation_state:
            notes = assistant.list_notes(limit=1)
            if notes and notes[0].get("source") == "telegram":
                _conversation_state[chat_id] = {
                    "note_id": notes[0].get("id", 0),
                    "note_content": notes[0].get("content", ""),
                    "history": [],
                }
                ai = notes[0].get("ai_analysis", "")
                if ai:
                    _conversation_state[chat_id]["history"].append(
                        {"role": "assistant", "text": ai}
                    )
        if chat_id in _conversation_state:
            await handle_discussion(update, context)
            return

    # 4. Pending delete confirmation
    pending = context.user_data.get("pending_delete")
    if pending and text.strip().lower() in ("y", "yes", "是", "刪", "確認"):
        if assistant.delete_note(pending):
            await update.message.reply_text(_m("note_deleted", id=pending))
        context.user_data["pending_delete"] = None
        return
    context.user_data["pending_delete"] = None

    # 5. Not URL, not command, not discussion -> treat as note
    await handle_note(update, context)


# --- Bot startup ---

def run_bot():
    if not BOT_TOKEN:
        print("[bot] TELEGRAM_BOT_TOKEN not set, exiting")
        sys.exit(1)

    print(f"[bot] Starting standalone bot... (API: {API_URL})")
    assistant.sync_from_github()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("notes", cmd_notes))
    app.add_handler(CommandHandler("note_help", cmd_note_help))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.post_init = _post_init
    app.post_shutdown = _post_shutdown
    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"[bot] Polling error: {e}")


async def _periodic_sync():
    while True:
        await asyncio.sleep(600)
        print("  [bot] Periodic sync to GitHub...")
        try:
            await asyncio.to_thread(assistant.sync_all)
        except Exception as e:
            print(f"  [bot] Periodic sync error: {e}")


async def _post_init(application):
    application.create_task(_periodic_sync())


async def _post_shutdown(application):
    pass


def run_with_health_server():
    import threading
    import uvicorn
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

    max_retries = 3
    for attempt in range(max_retries):
        try:
            run_bot()
            break
        except Exception as e:
            err_str = str(e)
            if "Conflict" in err_str and attempt < max_retries - 1:
                print(f"[bot] Conflict (instance overlap), retrying in 10s... ({attempt+1}/{max_retries})")
                import time as _time
                _time.sleep(10)
                continue
            print(f"[bot] Bot crashed: {e}, health server still running")


if __name__ == "__main__":
    run_with_health_server()
