#!/usr/bin/env python3
"""Fetch Douyin video metadata using DouK-Downloader encryption modules."""

import asyncio, json, os, re, sys, time
from pathlib import Path

# Fix Windows console encoding for CJK characters
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from urllib.parse import urlencode, quote

REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_CRYPTO = REPO_ROOT / "tools" / "douyin-downloader"
_TMP = os.environ.get("TEMP", os.environ.get("TMP", "/tmp"))
DOUNIK_PATH = os.environ.get("DOUNIK_PATH", str(_LOCAL_CRYPTO) if _LOCAL_CRYPTO.is_dir() else os.path.join(_TMP, "DouK-Downloader"))
sys.path.insert(0, os.path.abspath(DOUNIK_PATH))

import httpx
from src.encrypt.aBogus import ABogus

REPO = Path(__file__).resolve().parent.parent
JSON_PATH = REPO / "short-videos" / "short-videos.json"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
API_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

DEFAULT_PARAMS = {
    "device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web",
    "update_version_code": "170400", "pc_client_type": "1", "pc_libra_divert": "Windows",
    "support_h265": "1", "support_dash": "1", "version_code": "290100",
    "version_name": "29.1.0", "cookie_enabled": "true", "screen_width": "1536",
    "screen_height": "864", "browser_language": "zh-CN", "browser_platform": "Win32",
    "browser_name": "Chrome", "browser_version": "139.0.0.0", "browser_online": "true",
    "engine_name": "Blink", "engine_version": "139.0.0.0", "os_name": "Windows",
    "os_version": "10", "cpu_core_num": "16", "device_memory": "8", "platform": "PC",
    "downlink": "10", "effective_type": "4g", "round_trip_time": "200",
    "uifid": "", "msToken": "",
}

HEADERS = {
    "Accept": "*/*", "Accept-Encoding": "*/*",
    "Referer": "https://www.douyin.com/?recommend=1", "User-Agent": USER_AGENT,
}

RE_DETAIL_LINK = re.compile(r"\S*?https://www\.douyin\.com/(?:video|note|slides)/([0-9]{19})\S*?")
RE_DETAIL_SHARE = re.compile(r"\S*?https://www\.iesdouyin\.com/share/(?:video|note|slides)/([0-9]{19})/\S*?")
RE_ACCOUNT_MODAL = re.compile(r"\S*?https://www\.douyin\.com/user/[A-Za-z0-9_-]+(?:\S*?\bmodal_id=(\d{19}))?")
RE_DETAIL_SEARCH = re.compile(r"\S*?https://www\.douyin\.com/search/\S+?modal_id=(\d{19})\S*?")
RE_DETAIL_DISCOVER = re.compile(r"\S*?https://www\.douyin\.com/discover\S*?modal_id=(\d{19})\S*?")
RE_CHANNEL = re.compile(r"\S*?https://www\.douyin\.com/channel/\d+?\?modal_id=(\d{19})\S*?")
RE_AWEME_ID = re.compile(r"\b(\d{19})\b")
RATE_LIMIT_SEC = 1.5


def get_cookie():
    cookie = os.getenv("DOUYIN_COOKIE", "")
    if not cookie:
        env_file = REPO / ".env"
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DOUYIN_COOKIE="):
                        cookie = line.split("=", 1)[1].strip()
                        break
    return cookie


async def resolve_short_url(url, cookie):
    """Follow redirects for short share links (v.douyin.com) to get full URL."""
    headers = dict(HEADERS, Cookie=cookie)
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, verify=False) as c:
            resp = await c.get(url, headers=headers)
            # The final URL after redirects contains the aweme_id
            final_url = str(resp.url)
            if final_url != url:
                return final_url
            # Try parsing response body for video ID
            text = resp.text
            m = RE_AWEME_ID.search(text)
            if m:
                return m.group(1)
    except Exception:
        pass
    return url


def extract_aweme_id(text):
    patterns = [
        (RE_DETAIL_LINK, 1), (RE_DETAIL_SHARE, 1), (RE_ACCOUNT_MODAL, 2),
        (RE_DETAIL_SEARCH, 1), (RE_DETAIL_DISCOVER, 1), (RE_CHANNEL, 1),
    ]
    for pattern, group in patterns:
        m = pattern.search(text)
        if m and m.group(group):
            return m.group(group)
    m = RE_AWEME_ID.search(text)
    return m.group(1) if m else None


def sign_params(params, ab):
    encoded = urlencode(params, safe="=", quote_via=quote)
    signature = ab.get_value(encoded, "GET")
    return encoded + "&a_bogus=" + signature


def extract_metadata(detail):
    if not detail:
        return {}
    author = detail.get("author", {})
    stats = detail.get("statistics", {})
    desc = detail.get("desc", "")
    tags = re.findall(r"#([^#\s]+)#?", desc)
    return {
        "title": desc[:80].strip(),
        "author": author.get("nickname", ""),
        "author_uid": author.get("uid", ""),
        "author_sec_uid": author.get("sec_uid", ""),
        "core_points": desc.strip(),
        "tags": tags if tags else None,
        "statistics": {
            "digg_count": stats.get("digg_count", 0),
            "comment_count": stats.get("comment_count", 0),
            "collect_count": stats.get("collect_count", 0),
            "share_count": stats.get("share_count", 0),
            "play_count": stats.get("play_count", 0),
        },
        "create_time": detail.get("create_time", 0),
        "aweme_id": detail.get("aweme_id", ""),
        "desc_full": desc,
    }


async def fetch_single(client, aweme_id, cookie, ab):
    params = DEFAULT_PARAMS.copy()
    params["aweme_id"] = aweme_id
    params["version_code"] = "190500"
    params["version_name"] = "19.5.0"
    signed = sign_params(params, ab)
    url = API_URL + "?" + signed
    headers = dict(HEADERS, Cookie=cookie)
    try:
        resp = await client.get(url, headers=headers, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        detail = data.get("aweme_detail")
        if not detail:
            print(f"  Warning: No aweme_detail for {aweme_id}")
            return None
        return extract_metadata(detail)
    except httpx.HTTPStatusError as e:
        print(f"  HTTP {e.response.status_code} for {aweme_id}")
        return None
    except httpx.RequestError as e:
        print(f"  Request error for {aweme_id}: {e}")
        return None


async def fetch_and_update(url_or_id, cookie, ab, videos, dry_run=False):
    aweme_id = extract_aweme_id(url_or_id)
    # If regex didn't match, try resolving short URL via HTTP redirect
    if not aweme_id and url_or_id.startswith("http"):
        print(f"  Resolving short URL: {url_or_id[:50]}...")
        resolved = await resolve_short_url(url_or_id, cookie)
        aweme_id = extract_aweme_id(resolved)
    if not aweme_id:
        print(f"  Cannot extract aweme_id from: {url_or_id}")
        return None
    print(f"  Resolved: {url_or_id[:50]}... -> aweme_id={aweme_id}")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, verify=False) as client:
        meta = await fetch_single(client, aweme_id, cookie, ab)
    if not meta:
        return None
    print(f"  Title: {meta['title'][:60]}")
    print(f"  Author: {meta['author']}")
    if meta.get("tags"):
        tag_str = ", ".join(meta["tags"][:5])
        print(f"  Tags: {tag_str}")
    stats = meta.get("statistics", {})
    likes = stats.get("digg_count", 0)
    comments = stats.get("comment_count", 0)
    print(f"  Likes: {likes}, Comments: {comments}")
    if dry_run:
        print(f"  DRY RUN -- not updating JSON")
        return meta
    updated = False
    for v in videos:
        fname = v.get("file", "")
        if aweme_id in fname or aweme_id in v.get("url", ""):
            _apply_metadata(v, meta)
            updated = True
            break
    if not updated:
        for v in videos:
            if not v.get("url") and _title_similar(v.get("title", ""), meta["title"]):
                _apply_metadata(v, meta)
                updated = True
                break
    if updated:
        print(f"  Updated video in JSON")
    else:
        print(f"  No matching video found in JSON")
    return meta


def _apply_metadata(video, meta):
    if meta.get("core_points"):
        video["core_points"] = meta["core_points"]
    if meta.get("author"):
        source = video.get("source", "")
        if " - " in source:
            prefix = source.split(" - ")[0]
            video["source"] = prefix + " - " + meta["author"]
        else:
            video["source"] = chr(25234)+chr(38899) + " - " + meta["author"]
    if meta.get("tags"):
        video["tags"] = meta["tags"]
    if meta.get("desc_full"):
        video["note"] = meta["desc_full"][:200]
    if meta.get("create_time"):
        from datetime import datetime
        dt = datetime.fromtimestamp(meta["create_time"])
        video["date"] = dt.strftime("%Y-%m-%d")


def _title_similar(t1, t2):
    def chinese_chars(s):
        return set(re.findall(r"[\u4e00-\u9fff]", s))
    c1, c2 = chinese_chars(t1), chinese_chars(t2)
    if not c1 or not c2:
        return False
    return len(c1 & c2) / max(len(c1), len(c2)) > 0.6


def load_json():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    for path in [JSON_PATH, REPO / "short-videos.json"]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved: {JSON_PATH}")


def get_missing_content_videos(videos):
    missing = []
    for v in videos:
        cp = v.get("core_points", "").strip()
        fname = v.get("file", "")
        if not fname.startswith("douyin-"):
            continue
        if not cp or len(cp) < 50:
            missing.append(v)
    return missing


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch Douyin video metadata via DouK-Downloader encryption")
    parser.add_argument("url", nargs="?", help="Douyin share URL or aweme_id")
    parser.add_argument("--url-file", help="File with URLs (one per line)")
    parser.add_argument("--missing", action="store_true", help="Auto-detect videos missing content")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--cookie", help="Douyin cookie (or set DOUYIN_COOKIE env)")
    parser.add_argument("--output", help="Output JSON file for results")
    args = parser.parse_args()

    cookie = args.cookie or get_cookie()
    if not cookie:
        print("Error: No cookie set. Use --cookie or DOUYIN_COOKIE env var")
        sys.exit(1)

    ab = ABogus()
    urls = []
    if args.url:
        urls.append(args.url)
    if args.url_file:
        with open(args.url_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)

    data = None
    if args.missing or (not urls):
        data = load_json()
        missing = get_missing_content_videos(data["videos"])
        if not missing:
            print("All Douyin videos have content!")
            return
        print(f"Found {len(missing)} videos missing content")
        for v in missing:
            fname = v.get("file", "")
            m = re.search(r"(\d{19})", fname)
            if m:
                urls.append(m.group(1))

    if not urls:
        parser.print_help()
        sys.exit(1)

    print(f"Processing {len(urls)} video(s)\n")
    if data is None:
        data = load_json()

    results = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url[:60]}...")
        meta = asyncio.run(fetch_and_update(url, cookie, ab, data["videos"], dry_run=args.dry_run))
        if meta:
            results.append(meta)
        if i < len(urls):
            time.sleep(RATE_LIMIT_SEC)
        print()

    if results and args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"Results saved to {args.output}")

    if not args.dry_run and results:
        save_json(data)

    print(f"\nDone -- fetched {len(results)}/{len(urls)} video(s)")


if __name__ == "__main__":
    main()
