#!/usr/bin/env python3
"""Restore transcription for Douyin videos with missing/poor core_points via GLM API."""

import argparse
import json
import os
import re
import sys
import time
import io
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_SUB = os.path.join(BASE_DIR, "short-videos", "short-videos.json")
JSON_ROOT = os.path.join(BASE_DIR, "short-videos.json")

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
API_KEY = os.getenv("CLASSIFIER_API_KEY", "")
MODEL = "glm-4.7-flash"

PLACEHOLDER_PATTERNS = ["來源：小紅書平台", "來源：抖音", "自動下載失敗", "自動轉錄失敗"]
MIN_CORE_POINTS_LEN = 50


def clean_title(title: str) -> str:
    """Strip prefixes (e.g. '小紅書_'), date suffixes (_YYYYMMDD_HHMMSS), and hashtags."""
    t = re.sub(r"^小紅書_\s*", "", title)
    t = re.sub(r"_\d{8}_?\d{6}.*$", "", t)
    t = re.sub(r"#[\u4e00-\u9fff\w]+\s*", "", t)
    return t.strip()


def needs_restore(video: dict) -> bool:
    src = video.get("source", "").lower()
    if "抖音" not in src and "douyin" not in src:
        return False
    cp = video.get("core_points", "")
    if len(cp) < MIN_CORE_POINTS_LEN:
        return True
    return any(p in cp for p in PLACEHOLDER_PATTERNS)


def generate_content(topic: str, tags: list[str], source: str) -> str | None:
    """Call GLM API to generate detailed summary points for a video topic."""
    tags_str = "、".join(tags) if tags else source
    prompt = (
        f"你是一個短影音內容分析專家。根據以下影片主題，生成 5 個詳細的核心重點（繁體中文）。\n"
        f"每點一行，以數字開頭，每點不超過 50 字，內容要有深度和實用性。只輸出要點，不加前言後語。\n\n"
        f"影片主題：{topic}\n"
        f"標籤：{tags_str}\n"
        f"來源：{source}"
    )
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 500,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    for attempt in range(3):
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                print(f"    Rate limited, waiting {wait}s (attempt {attempt + 1}/3)")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except requests.RequestException as e:
            print(f"    API error: {e} (attempt {attempt + 1}/3)")
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    return None


def save_json(data: dict) -> None:
    """Save to both short-videos/ and root copies."""
    for path in (JSON_SUB, JSON_ROOT):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore Douyin video transcriptions")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    with open(JSON_SUB, "r", encoding="utf-8") as f:
        data = json.load(f)

    candidates = [(i, v) for i, v in enumerate(data["videos"]) if needs_restore(v)]
    print(f"Total videos: {len(data['videos'])}")
    print(f"Douyin videos needing restore: {len(candidates)}")

    if not candidates:
        print("Nothing to do.")
        return

    if args.dry_run:
        print("\n--- DRY RUN ---")
        for i, v in candidates:
            topic = clean_title(v.get("title", ""))
            print(f"  [{i}] {v.get('title', '')[:60]}")
            print(f"       topic: {topic[:60]}")
            print(f"       current cp ({len(v.get('core_points', ''))} chars): {v.get('core_points', '')[:80]}")
        print(f"\nWould restore {len(candidates)} videos.")
        return

    success = 0
    failed = 0
    for idx, (i, v) in enumerate(candidates, 1):
        topic = clean_title(v.get("title", ""))
        tags = v.get("tags", [])
        source = v.get("source", "")

        print(f"[{idx}/{len(candidates)}] {v.get('title', '')[:60]}")
        print(f"  Topic: {topic[:60]}")

        result = generate_content(topic, tags, source)
        if result:
            v["core_points"] = result
            v["note"] = (v.get("note", "") + "\n" if v.get("note", "") else "") + "✅ 內容由 GLM API 補齊"
            success += 1
            print(f"  OK ({len(result)} chars)")
        else:
            failed += 1
            print(f"  FAILED")

        if idx < len(candidates):
            time.sleep(2)

    save_json(data)
    print(f"\nDone. Restored: {success}, Failed: {failed}")


if __name__ == "__main__":
    main()
