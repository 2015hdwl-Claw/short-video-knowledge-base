#!/usr/bin/env python3
"""Batch generate core_points for videos without content using GLM API."""

import io
import json
import os
import re
import sys
import time

from openai import OpenAI

# Force UTF-8 on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# --- Paths (relative to this script) ---
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH_SUBDIR = os.path.join(REPO, "short-videos", "short-videos.json")
JSON_PATH_ROOT = os.path.join(REPO, "short-videos.json")

# --- API config via env vars ---
API_KEY = os.getenv("CLASSIFIER_API_KEY", "")
BASE_URL = os.getenv("CLASSIFIER_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MODEL = os.getenv("CLASSIFIER_MODEL", "glm-4.7-flash")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# Rate limit delay between API calls (seconds)
RATE_LIMIT_DELAY = int(os.getenv("RATE_LIMIT_DELAY", "5"))


def extract_topic(title: str) -> str:
    """Extract meaningful topic from title by removing prefix/suffix noise."""
    cleaned = re.sub(r"^小紅書_", "", title)
    cleaned = re.sub(r"^抖音_", "", cleaned)
    cleaned = re.sub(r"_\d{8}_\d{6}_\d{2}$", "", cleaned)
    return cleaned.strip()


def generate_summary(title: str, tags: list, source: str, url: str) -> str | None:
    """Generate core_points from title/tags using GLM API."""
    topic = extract_topic(title)
    tag_str = ", ".join(tags) if tags else "none"

    prompt = (
        "Based on the following short video topic, generate 3-5 core points "
        "in Traditional Chinese.\n"
        "Each point on its own line, starting with a number. "
        "Concise and impactful, each point under 40 characters.\n\n"
        f"Topic: {topic}\n"
        f"Tags: {tag_str}\n"
        f"Source: {source}\n\n"
        "Output only the 3-5 bullet points, no other explanation:"
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,
        )
        content = resp.choices[0].message.content.strip()
        return content
    except Exception as e:
        print(f"  API error: {e}", file=sys.stderr)
        return None


def save_json(data: dict) -> None:
    """Write JSON to both locations (subdir copy + root copy)."""
    for path in (JSON_PATH_SUBDIR, JSON_PATH_ROOT):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Saved: {path}")


def main() -> None:
    with open(JSON_PATH_SUBDIR, "r", encoding="utf-8") as f:
        data = json.load(f)

    videos = data.get("videos", [])

    need_content = []
    for i, v in enumerate(videos):
        cp = v.get("core_points", "").strip()
        if not cp or cp == "short video analysis report" or len(cp) < 20:
            need_content.append(i)

    print(f"Videos needing content: {len(need_content)}")

    if not need_content:
        print("Nothing to do.")
        return

    generated = 0
    failed = 0

    for rank, idx in enumerate(need_content, 1):
        v = videos[idx]
        title = v.get("title", "")
        tags = v.get("tags", [])
        source = v.get("source", "")
        url = v.get("url", "")

        print(f"[{rank}/{len(need_content)}] {title[:60]}...", flush=True)

        result = generate_summary(title, tags, source, url)
        if result:
            v["core_points"] = result
            generated += 1
            print(f"  OK", flush=True)
        else:
            failed += 1
            print(f"  SKIP", flush=True)

        if rank < len(need_content):
            print(f"  Waiting {RATE_LIMIT_DELAY}s...", flush=True)
            time.sleep(RATE_LIMIT_DELAY)

    save_json(data)

    print(f"\nDone. Generated: {generated}, Failed: {failed}")


if __name__ == "__main__":
    main()
