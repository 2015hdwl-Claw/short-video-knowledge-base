#!/usr/bin/env python3
"""Unified pipeline: URL -> metadata -> content -> save -> reply.

CLI:  python pipeline.py <url> [--dry-run] [--line-format]
Module: from pipeline import process_url, PipelineResult
"""

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from openai import OpenAI

REPO = Path(__file__).resolve().parent.parent
JSON_PATHS = [REPO / "short-videos.json", REPO / "short-videos" / "short-videos.json"]

API_KEY = os.getenv("CLASSIFIER_API_KEY", "")
BASE_URL = os.getenv("CLASSIFIER_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MODEL = os.getenv("CLASSIFIER_MODEL", "glm-4.7-flash")
CLIENT = OpenAI(api_key=API_KEY, base_url=BASE_URL) if API_KEY else None

ADMIN_URL = "https://2015hdwl-claw.github.io/short-video-knowledge-base/admin.html"
RATE_LIMIT = 1.5


@dataclass
class PipelineResult:
    success: bool = False
    url: str = ""
    aweme_id: str = ""
    title: str = ""
    author: str = ""
    tags: list = field(default_factory=list)
    category: str = ""
    core_points: str = ""
    date: str = ""
    statistics: dict = field(default_factory=dict)
    error: str = ""

    COOKIE_EXPIRED_HINT = (
        "\n\nCookie expired!\n"
        "1. Open douyin.com in browser and log in\n"
        "2. F12 > Application > Cookies > douyin.com\n"
        "3. Select All > Copy\n"
        "4. Update DOUYIN_COOKIE in Render Dashboard"
    )

    def to_line_reply(self) -> str:
        if not self.success:
            if "Cookie expired" in self.error or "Cookie" in self.error:
                return "Cookie expired or invalid." + self.COOKIE_EXPIRED_HINT
            return "Error: " + self.error
        tags_str = ", ".join(self.tags[:5]) if self.tags else "N/A"
        points = self.core_points.strip().split("\n")[:5]
        points_str = "\n".join(points) if points else "(No summary)"
        likes = self.statistics.get("digg_count", 0)
        comments = self.statistics.get("comment_count", 0)
        return "\n".join([
            "--- Knowledge Card ---",
            "Title: " + self.title[:60],
            "Author: " + self.author,
            "Category: " + self.category,
            "Tags: " + tags_str,
            "Date: " + self.date,
            "",
            "Core Points:",
            points_str,
            "",
            "Likes: " + str(likes) + " | Comments: " + str(comments),
            "Admin: " + ADMIN_URL,
        ])


def _load_json() -> dict:
    for p in JSON_PATHS:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return {"videos": []}


def _save_json(data: dict) -> None:
    for p in JSON_PATHS:
        parent = p.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def _generate_summary(title, tags, source, url):
    if not CLIENT:
        return ""
    topic = re.sub(r"^[\u5c0f\u7d05\u66f8_]+", "", title)
    topic = re.sub(r"_\d{8}_\d{6}_\d+$", "", topic).strip()
    tag_str = ", ".join(tags) if tags else "none"
    prompt = (
        "Based on the following short video topic, generate 3-5 core points "
        "in Traditional Chinese.\n"
        "Each point on its own line, starting with a number. "
        "Concise and impactful, each point under 40 characters.\n\n"
        "Topic: " + topic + "\n"
        "Tags: " + tag_str + "\n"
        "Source: " + source + "\n\n"
        "Output only the 3-5 bullet points, no other explanation:"
    )
    try:
        resp = CLIENT.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("  Summary API error: " + str(e), file=sys.stderr)
        return ""


def _classify_category(tags, title, core_points):
    if not CLIENT:
        return "Other"
    tag_str = ", ".join(tags) if tags else ""
    prompt = (
        "Classify this short video into ONE of these categories:\n"
        "AI, Education, Personal Growth, Finance, Health, Psychology, Other\n\n"
        "Title: " + title[:80] + "\n"
        "Tags: " + tag_str + "\n"
        "Summary: " + core_points[:100] + "\n\n"
        "Reply with ONLY the category name, nothing else:"
    )
    try:
        resp = CLIENT.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0,
        )
        cat = resp.choices[0].message.content.strip()
        for v in ["AI", "Education", "Personal Growth", "Finance", "Health", "Psychology"]:
            if v.lower() in cat.lower():
                return v
        return cat if cat else "Other"
    except Exception:
        return "Other"


async def _fetch_metadata(url_or_id, cookie):
    try:
        from urllib.parse import urlencode, quote

        crypto_path = os.environ.get("DOUNIK_PATH", "")
        if not crypto_path:
            local = REPO / "tools" / "douyin-downloader"
            if local.is_dir():
                crypto_path = str(local)
        if not crypto_path:
            print("  No crypto modules found", file=sys.stderr)
            return None

        if crypto_path not in sys.path:
            sys.path.insert(0, os.path.abspath(crypto_path))
        from src.encrypt.aBogus import ABogus
        import httpx

        ab = ABogus()

        patterns = [
            re.compile(r"https://www\.douyin\.com/(?:video|note|slides)/([0-9]{19})"),
            re.compile(r"https://www\.iesdouyin\.com/share/(?:video|note|slides)/([0-9]{19})"),
            re.compile(r"https://www\.douyin\.com/user/[A-Za-z0-9_-]+.*modal_id=(\d{19})"),
            re.compile(r"\b(\d{19})\b"),
        ]
        aweme_id = None
        for pat in patterns:
            m = pat.search(url_or_id)
            if m:
                aweme_id = m.group(1)
                break

        if not aweme_id and url_or_id.startswith("http"):
            try:
                async with httpx.AsyncClient(timeout=10, follow_redirects=True, verify=False) as c:
                    resp = await c.get(url_or_id, headers={
                        "User-Agent": "Mozilla/5.0",
                        "Cookie": cookie,
                    })
                    for pat in patterns:
                        m = pat.search(str(resp.url))
                        if m:
                            aweme_id = m.group(1)
                            break
            except Exception:
                pass

        if not aweme_id:
            print("  Cannot extract aweme_id", file=sys.stderr)
            return None

        params = {
            "device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web",
            "aweme_id": aweme_id, "version_code": "190500", "version_name": "19.5.0",
        }
        encoded = urlencode(params, safe="=", quote_via=quote)
        signature = ab.get_value(encoded, "GET")
        signed_url = "https://www.douyin.com/aweme/v1/web/aweme/detail/?" + encoded + "&a_bogus=" + signature

        async with httpx.AsyncClient(timeout=15, follow_redirects=True, verify=False) as client:
            resp = await client.get(signed_url, headers={
                "Accept": "*/*",
                "Referer": "https://www.douyin.com/?recommend=1",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Cookie": cookie,
            })

            # Detect cookie expiry
            if resp.status_code in (401, 403):
                print("  Cookie expired (HTTP " + str(resp.status_code) + ")", file=sys.stderr)
                return {"_cookie_expired": True}

            resp.raise_for_status()
            data = resp.json()

        # Check API-level error codes indicating cookie issues
        api_code = data.get("status_code", 0)
        if api_code in (2151, 2154, 2193):
            print("  Cookie expired (API code " + str(api_code) + ")", file=sys.stderr)
            return {"_cookie_expired": True}

        detail = data.get("aweme_detail")
        if not detail:
            print("  No aweme_detail (possibly expired cookie)", file=sys.stderr)
            return {"_cookie_expired": True}

        author = detail.get("author", {})
        stats = detail.get("statistics", {})
        desc = detail.get("desc", "")
        tags = re.findall(r"#([^#\s]+)#?", desc)

        return {
            "aweme_id": aweme_id,
            "title": desc[:80].strip(),
            "author": author.get("nickname", ""),
            "tags": tags if tags else [],
            "core_points": desc.strip(),
            "desc_full": desc,
            "statistics": {
                "digg_count": stats.get("digg_count", 0),
                "comment_count": stats.get("comment_count", 0),
                "collect_count": stats.get("collect_count", 0),
                "share_count": stats.get("share_count", 0),
                "play_count": stats.get("play_count", 0),
            },
            "create_time": detail.get("create_time", 0),
            "url": url_or_id,
        }
    except Exception as e:
        print("  Fetch error: " + str(e), file=sys.stderr)
        return None


def _fill_content(meta):
    title = meta.get("title", "")
    tags = meta.get("tags", [])
    author = meta.get("author", "")
    summary = _generate_summary(title, tags, author, meta.get("url", ""))
    return summary if summary else meta.get("desc_full", "")[:200]


def _save_video(meta, summary):
    data = _load_json()
    videos = data.get("videos", [])
    aweme_id = meta.get("aweme_id", "")
    title = meta.get("title", "")
    author = meta.get("author", "")
    category = _classify_category(meta.get("tags", []), title, summary)

    entry = {
        "title": title,
        "source": author,
        "category": category,
        "core_points": summary,
        "tags": meta.get("tags", []),
        "url": meta.get("url", ""),
        "date": "",
        "advice": "",
        "audience": "",
        "note": meta.get("desc_full", "")[:200] if meta.get("desc_full") else "",
        "file": "raw/videos/douyin-" + aweme_id + ".md" if aweme_id else "",
    }

    ct = meta.get("create_time", 0)
    if ct:
        try:
            entry["date"] = datetime.fromtimestamp(ct).strftime("%Y-%m-%d")
        except Exception:
            pass

    updated = False
    for i, v in enumerate(videos):
        if aweme_id and aweme_id in v.get("file", ""):
            entry["file"] = v.get("file", entry["file"])
            videos[i] = entry
            updated = True
            break
        if meta.get("url") and v.get("url") == meta.get("url"):
            videos[i] = entry
            updated = True
            break
    if not updated:
        videos.append(entry)

    data["videos"] = videos
    _save_json(data)
    return True


async def process_url(url, cookie="", dry_run=False):
    """Full pipeline: fetch metadata -> generate summary -> save to JSON."""
    result = PipelineResult(url=url)
    if not cookie:
        env_file = REPO / ".env"
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DOUYIN_COOKIE="):
                        cookie = line.split("=", 1)[1].strip()
                        break
        if not cookie:
            cookie = os.getenv("DOUYIN_COOKIE", "")

    print("[1/3] Fetching metadata...")
    meta = await _fetch_metadata(url, cookie)
    if not meta:
        result.error = "Failed to fetch metadata"
        return result
    if meta.get("_cookie_expired"):
        result.error = (
            "Cookie expired or invalid.\n"
            "How to update:\n"
            "1. Open douyin.com in browser and log in\n"
            "2. F12 -> Application -> Cookies -> www.douyin.com -> Select All\n"
            "3. Copy and update DOUYIN_COOKIE in Render Dashboard"
        )
        return result

    result.aweme_id = meta.get("aweme_id", "")
    result.title = meta.get("title", "")
    result.author = meta.get("author", "")
    result.tags = meta.get("tags", [])
    result.statistics = meta.get("statistics", {})
    print("  Title: " + result.title[:50])
    print("  Author: " + result.author)

    print("[2/3] Generating summary...")
    summary = _fill_content(meta)
    result.core_points = summary

    if dry_run:
        result.success = True
        return result

    print("[3/3] Saving...")
    ok = _save_video(meta, summary)
    if ok:
        result.success = True
        data = _load_json()
        for v in data.get("videos", []):
            if aweme_id and aweme_id in v.get("file", ""):
                result.category = v.get("category", "")
                result.date = v.get("date", "")
                break
        print("  Saved. Category: " + result.category)
    else:
        result.error = "Failed to save"

    return result


def process_missing(cookie="", dry_run=False):
    """Batch process videos missing content."""
    data = _load_json()
    videos = data.get("videos", [])
    missing = [v for v in videos
               if not v.get("core_points", "").strip() or len(v.get("core_points", "")) < 20]
    if not missing:
        print("All videos have content.")
        return []
    print("Found " + str(len(missing)) + " videos missing content")
    results = []
    for i, v in enumerate(missing):
        url = v.get("url", "")
        if not url:
            continue
        print("\n[" + str(i + 1) + "/" + str(len(missing)) + "] " + v.get("title", "")[:50])
        result = asyncio.run(process_url(url, cookie, dry_run=dry_run))
        results.append(result)
        if i < len(missing) - 1:
            time.sleep(RATE_LIMIT)
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Short video knowledge pipeline")
    parser.add_argument("url", nargs="?", help="Douyin URL or aweme_id")
    parser.add_argument("--missing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cookie", help="Douyin cookie")
    parser.add_argument("--line-format", action="store_true", help="LINE reply format")
    args = parser.parse_args()

    cookie = args.cookie or os.getenv("DOUYIN_COOKIE", "")

    if args.missing:
        results = process_missing(cookie, dry_run=args.dry_run)
        for r in results:
            if args.line_format:
                print(r.to_line_reply())
            else:
                print("  " + ("OK" if r.success else "FAIL: " + r.error))
    elif args.url:
        result = asyncio.run(process_url(args.url, cookie, dry_run=args.dry_run))
        if args.line_format:
            print(result.to_line_reply())
        else:
            print("\n" + ("Success" if result.success else "Error: " + result.error))
            print("Title: " + result.title)
            print("Author: " + result.author)
            print("Category: " + result.category)
            print("Points: " + result.core_points[:100])
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
