#!/usr/bin/env python3
"""Assistant data persistence with GitHub sync for notes, reminders, contacts."""

import base64
import json
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assistant.json")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "2015hdwl-Claw/short-video-knowledge-base")
GITHUB_DB_KEY = "assistant.json"


def load_data():
    if not os.path.exists(DB_PATH):
        return {"notes": [], "reminders": [], "contacts": []}
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def sync_to_github():
    if not GITHUB_TOKEN or not os.path.exists(DB_PATH):
        return False
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_DB_KEY}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "User-Agent": "svkb-bot"}
    try:
        resp = httpx.get(api_url, headers=headers, timeout=15)
        sha = resp.json().get("sha", "") if resp.status_code == 200 else ""
        content = base64.b64encode(open(DB_PATH, "rb").read()).decode("ascii")
        resp = httpx.put(api_url, headers=headers, timeout=30, json={
            "message": "Update assistant.json",
            "content": content,
            "sha": sha,
        })
        if resp.status_code in (200, 201):
            print("  [assistant] Synced to GitHub")
            return True
        else:
            print(f"  [assistant] Sync failed: {resp.status_code}")
            return False
    except Exception as e:
        print(f"  [assistant] Sync error: {e}")
        return False


def sync_from_github():
    if not GITHUB_TOKEN:
        return False
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_DB_KEY}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "User-Agent": "svkb-bot"}
    try:
        resp = httpx.get(api_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            with open(DB_PATH, "w", encoding="utf-8") as f:
                f.write(content)
            print("  [assistant] Pulled from GitHub")
            return True
        elif resp.status_code == 404:
            print("  [assistant] No remote DB, starting fresh")
            return False
    except Exception as e:
        print(f"  [assistant] Pull error: {e}")
        return False


# Note operations

def add_note(content, chat_id, ai_analysis=None, category="", tags=None):
    data = load_data()
    note_id = len(data["notes"]) + 1
    note = {
        "id": note_id,
        "content": content,
        "category": category,
        "tags": tags or [],
        "ai_analysis": ai_analysis or "",
        "created_at": _now(),
        "chat_id": chat_id,
        "source": "telegram",
    }
    data["notes"].append(note)
    save_data(data)
    sync_to_github()
    return note


def list_notes(category=None, search_query=None, limit=20):
    data = load_data()
    notes = data["notes"]
    if category:
        notes = [n for n in notes if n.get("category", "").lower() == category.lower()]
    if search_query:
        q = search_query.lower()
        notes = [n for n in notes if q in n.get("content", "").lower() or q in " ".join(n.get("tags", [])).lower()]
    return list(reversed(notes[-limit:]))


def delete_note(note_id):
    data = load_data()
    before = len(data["notes"])
    data["notes"] = [n for n in data["notes"] if n["id"] != note_id]
    if len(data["notes"]) < before:
        save_data(data)
        sync_to_github()
        return True
    return False


def get_note(note_id):
    data = load_data()
    for n in data["notes"]:
        if n["id"] == note_id:
            return n
    return None


def _now():
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S")

