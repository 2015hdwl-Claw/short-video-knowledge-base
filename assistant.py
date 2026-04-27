#!/usr/bin/env python3
"""Assistant data persistence with GitHub sync for notes.

Notes are stored in two places (compatible with admin.html):
1. notes.json — index file the admin page reads via fetch()
2. raw/notes/*.md — individual Markdown files

Both sync to GitHub so the admin page on GitHub Pages can display them.
"""

import base64
import json
import os
import re
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
NOTES_JSON_PATH = os.path.join(REPO_DIR, "notes.json")
RAW_NOTES_DIR = os.path.join(REPO_DIR, "raw", "notes")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "2015hdwl-Claw/short-video-knowledge-base")


def _gh_headers():
    return {
        "Authorization": "Bearer " + GITHUB_TOKEN,
        "User-Agent": "svkb-bot",
        "Content-Type": "application/json",
    }


def _gh_get(path):
    api_url = "https://api.github.com/repos/" + GITHUB_REPO + "/contents/" + path
    resp = httpx.get(api_url, headers=_gh_headers(), timeout=15)
    return resp


def _gh_put(path, body):
    api_url = "https://api.github.com/repos/" + GITHUB_REPO + "/contents/" + path
    resp = httpx.put(api_url, headers=_gh_headers(), timeout=30, json=body)
    return resp


def _gh_encode(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _gh_decode(b64):
    return base64.b64decode(b64).decode("utf-8")


def _now():
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz)


def _now_str():
    return _now().strftime("%Y-%m-%d")
_Now = _now_str


def _now_time():
    return _now().strftime("%H:%M")


def _now_timestamp():
    return _now().strftime("%Y-%m-%d_%H%M%S")


def _slug(text):
    t = re.sub(r'[^\w\s-]', '', text[:60]).strip().lower()
    t = re.sub(r'[\s]+', '-', t)
    return t or "note"


# --- notes.json operations (local + GitHub sync) ---

def _load_notes_json():
    if os.path.exists(NOTES_JSON_PATH):
        with open(NOTES_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_notes_json(notes):
    os.makedirs(os.path.dirname(NOTES_JSON_PATH), exist_ok=True)
    with open(NOTES_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


def _sync_notes_json_to_github(notes):
    if not GITHUB_TOKEN:
        return False
    try:
        resp = _gh_get("notes.json")
        sha = resp.json().get("sha", "") if resp.status_code == 200 else ""
        content = _gh_encode(json.dumps(notes, ensure_ascii=False, indent=2))
        resp = _gh_put("notes.json", {
            "message": "Update notes.json",
            "content": content,
            "sha": sha,
        })
        if resp.status_code in (200, 201):
            print("  [assistant] notes.json synced to GitHub")
            return True
        print(f"  [assistant] notes.json sync failed: {resp.status_code}")
        return False
    except Exception as e:
        print(f"  [assistant] notes.json sync error: {e}")
        return False


def _push_md_to_github(rel_path, md_content):
    if not GITHUB_TOKEN:
        return False
    try:
        resp = _gh_get(rel_path)
        sha = resp.json().get("sha", "") if resp.status_code == 200 else ""
        resp = _gh_put(rel_path, {
            "message": "Add note: " + os.path.basename(rel_path),
            "content": _gh_encode(md_content),
            "sha": sha,
        })
        if resp.status_code in (200, 201):
            print(f"  [assistant] Pushed {rel_path} to GitHub")
            return True
        print(f"  [assistant] Push {rel_path} failed: {resp.status_code}")
        return False
    except Exception as e:
        print(f"  [assistant] Push {rel_path} error: {e}")
        return False


def sync_from_github():
    if not GITHUB_TOKEN:
        return False
    pulled = False
    try:
        resp = _gh_get("notes.json")
        if resp.status_code == 200:
            content = _gh_decode(resp.json()["content"])
            with open(NOTES_JSON_PATH, "w", encoding="utf-8") as f:
                f.write(content)
            print("  [assistant] Pulled notes.json from GitHub")
            pulled = True
        elif resp.status_code == 404:
            print("  [assistant] No remote notes.json, starting fresh")
    except Exception as e:
        print(f"  [assistant] Pull notes.json error: {e}")

    if not os.path.exists(RAW_NOTES_DIR):
        os.makedirs(RAW_NOTES_DIR, exist_ok=True)
    try:
        resp = _gh_get("raw/notes")
        if resp.status_code == 200:
            for item in resp.json():
                if item["type"] != "file" or not item["name"].endswith(".md"):
                    continue
                local_path = os.path.join(REPO_DIR, item["path"])
                if os.path.exists(local_path):
                    continue
                content = _gh_decode(item["content"])
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(content)
            print("  [assistant] Synced raw/notes/ from GitHub")
            pulled = True
    except Exception as e:
        print(f"  [assistant] Pull raw/notes error: {e}")

    return pulled


def sync_all():
    """Push all local notes.json + raw/notes/*.md to GitHub in one batch.
    Call this on startup and periodically (not on every note write).
    """
    notes = _load_notes_json()
    if notes:
        _sync_notes_json_to_github(notes)
    if os.path.exists(RAW_NOTES_DIR):
        for fpath in sorted(RAW_NOTES_DIR.glob("*.md")):
            rel_path = "raw/notes/" + fpath.name
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            _push_md_to_github(rel_path, content)


# --- Public API ---

def add_note(content, chat_id, ai_analysis=None, category="", tags=None):
    notes = _load_notes_json()
    date = _now_str()
    time = _now_time()
    timestamp = _now_timestamp()
    slug = _slug(content)
    filename = f"{timestamp}_{slug}.md"
    rel_path = "raw/notes/" + filename

    tags_list = tags or []
    tags_str = ", ".join(tags_list) if tags_list else ""

    md_lines = [
        "# 隨身筆記",
        "",
        "**日期**：" + date,
        "**時間**：" + time,
        "**來源**：telegram",
        "**分類**：" + (category or "Other"),
        "**標籤**：" + tags_str,
        "",
        "---",
        "",
        content,
    ]
    if ai_analysis:
        md_lines += ["", "---", "", "**AI 分析**：", "", ai_analysis]
    md_content = "\n".join(md_lines)

    os.makedirs(RAW_NOTES_DIR, exist_ok=True)
    local_path = os.path.join(REPO_DIR, rel_path)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    entry = {
        "file": rel_path,
        "date": date,
        "time": time,
        "source": "telegram",
        "category": category or "Other",
        "tags": tags_list,
        "content": content,
        "ai_analysis": ai_analysis or "",
        "reminder": None,
    }
    notes.append(entry)
    _save_notes_json(notes)
    print(f"  [assistant] Note #{entry['id']} saved locally")

    # Don't push immediately — batch sync to avoid deploy loop

    entry["id"] = len(notes)
    return entry


def list_notes(category=None, search_query=None, limit=20):
    notes = _load_notes_json()
    if category:
        notes = [n for n in notes if n.get("category", "").lower() == category.lower()]
    if search_query:
        q = search_query.lower()
        notes = [n for n in notes if q in n.get("content", "").lower() or q in " ".join(n.get("tags", [])).lower()]
    notes = list(reversed(notes))
    for i, n in enumerate(notes):
        n["id"] = len(_load_notes_json()) - i
    return notes[:limit]


def delete_note(note_id):
    notes = _load_notes_json()
    if note_id < 1 or note_id > len(notes):
        return False
    removed = notes.pop(note_id - 1)
    _save_notes_json(notes)
    rel_path = removed.get("file", "")
    if rel_path:
        try:
            resp = _gh_get(rel_path)
            if resp.status_code == 200:
                sha = resp.json().get("sha", "")
                httpx.delete(
                    "https://api.github.com/repos/" + GITHUB_REPO + "/contents/" + rel_path,
                    headers=_gh_headers(),
                    timeout=15,
                    json={"message": "Delete note: " + os.path.basename(rel_path), "sha": sha},
                )
        except Exception as e:
            print(f"  [assistant] Delete {rel_path} error: {e}")
    return True


def get_note(note_id):
    notes = _load_notes_json()
    if note_id < 1 or note_id > len(notes):
        return None
    n = notes[note_id - 1]
    n["id"] = note_id
    return n


def append_discussion(note_id, user_text, ai_reply):
    notes = _load_notes_json()
    if note_id < 1 or note_id > len(notes):
        return False
    note = notes[note_id - 1]
    existing = note.get("ai_analysis", "")
    discussion = (
        existing
        + "\n\n---\n\n**Q:** " + user_text + "\n\n**A:** " + ai_reply
    )
    note["ai_analysis"] = discussion
    _save_notes_json(notes)

    rel_path = note.get("file", "")
    if rel_path:
        local_path = os.path.join(REPO_DIR, rel_path)
        if os.path.exists(local_path):
            with open(local_path, "a", encoding="utf-8") as f:
                f.write("\n\n---\n\n**Q:** " + user_text + "\n\n**A:** " + ai_reply)
    return True
