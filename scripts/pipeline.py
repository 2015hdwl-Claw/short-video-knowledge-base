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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glm_limiter import rate_limited_call, PROVIDERS, _get_client

API_KEY = os.getenv("CLASSIFIER_API_KEY", "")
BASE_URL = os.getenv("CLASSIFIER_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MODEL = os.getenv("CLASSIFIER_MODEL", "glm-4.7-flash")
CLIENT = _get_client("glm_cn")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = os.getenv("GROQ_MODEL", "whisper-large-v3-turbo")

ADMIN_URL = "https://2015hdwl-claw.github.io/short-video-knowledge-base/admin.html"
RATE_LIMIT = 1.5
WIKI_CONCEPTS = REPO / "wiki" / "concepts"
WIKI_INDEX = REPO / "wiki" / "index.md"


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
    has_subtitle: bool = False

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


def _generate_summary(title, tags, source, url, subtitle=""):
    if not CLIENT:
        return ""
    topic = re.sub(r"^[\u5c0f\u7d05\u66f8_]+", "", title)
    topic = re.sub(r"_\d{8}_\d{6}_\d+$", "", topic).strip()
    tag_str = ", ".join(tags) if tags else "none"

    if subtitle:
        prompt = (
            "Based on the following short video transcript, generate a detailed summary "
            "in Traditional Chinese.\n"
            "Structure:\n"
            "1. 一句話總結（under 30 chars）\n"
            "2. 5-8 個核心要點，每點 40-80 字，包含具體數據或方法\n"
            "3. 可執行的建議（1-2 點）\n\n"
            "Title: " + topic + "\n"
            "Tags: " + tag_str + "\n"
            "Author: " + source + "\n"
            "Transcript:\n" + subtitle[:3000] + "\n\n"
            "Output only the summary, no other explanation:"
        )
    else:
        prompt = (
            "Based on the following short video information, generate a knowledge summary "
            "in Traditional Chinese.\n"
            "The video has no transcript available, so infer likely content from title and tags.\n\n"
            "Structure:\n"
            "1. One-line summary (under 30 chars)\n"
            "2. 3-5 key takeaways, each 30-60 chars, specific and actionable\n"
            "3. Target audience\n\n"
            "Title: " + topic + "\n"
            "Tags: " + tag_str + "\n"
            "Author: " + source + "\n\n"
            "Output only the summary:"
        )
    try:
        resp = rate_limited_call(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800 if subtitle else 500,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("  Summary API error: " + str(e), file=sys.stderr)
        return ""


def _classify_category(tags, title, core_points):
    VALID_CATS = {"AI", "教育", "個人成長", "財經", "健康", "心理學", "科技", "創業"}
    tag_str = ", ".join(tags) if tags else ""
    prompt = (
        "將這支短影音分類到以下其中一個類別（只能選一個）：\n"
        "AI、教育、個人成長、財經、健康、心理學、科技、創業\n\n"
        "標題: " + title[:80] + "\n"
        "標籤: " + tag_str + "\n"
        "摘要: " + core_points[:100] + "\n\n"
        "只回覆類別名稱，不要加其他文字："
    )
    try:
        resp = rate_limited_call(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0,
        )
        cat = resp.choices[0].message.content.strip()
        if cat in VALID_CATS:
            return cat
        for v in VALID_CATS:
            if v in cat or cat in v:
                return v
        return "個人成長"
    except Exception:
        return "個人成長"


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
        video = detail.get("video", {})

        return {
            "aweme_id": aweme_id,
            "title": desc[:80].strip(),
            "author": author.get("nickname", ""),
            "tags": tags if tags else [],
            "core_points": desc.strip(),
            "desc_full": desc,
            "video_url": video.get("play_addr", {}).get("url_list", [""])[0],
            "duration": video.get("duration", 0),
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


def _fetch_subtitles(url):
    """Extract subtitles from video using yt-dlp (--skip-download, no Whisper needed)."""
    try:
        import tempfile
        import yt_dlp

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["zh", "zh-Hans", "zh-TW", "zh-CN", "en"],
                "skip_download": True,
                "outtmpl": tmpdir + "/sub",
                "quiet": True,
                "no_warnings": True,
                "extractor_args": {"douyin": {"player_client": ["web"]}},
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            for f in sorted(Path(tmpdir).iterdir()):
                if f.suffix in (".srt", ".vtt", ".srv1", ".srv2", ".srv3"):
                    text = _parse_subtitle_file(f)
                    if text and len(text) > 20:
                        return text
    except Exception as e:
        print("  Subtitle extraction failed: " + str(e), file=sys.stderr)
    return ""


def _download_audio(video_url, max_size_mb=25):
    """Download video audio from Douyin API URL.

    Uses the video_url from Douyin API (aBogus signed).
    Returns temp file path or None on failure.
    """
    import tempfile
    import httpx

    if not video_url:
        return None

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        audio_path = Path(tmp.name)

    try:
        with httpx.Client(timeout=120, follow_redirects=True, verify=False) as client:
            resp = client.get(video_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.douyin.com/",
            })
            resp.raise_for_status()
            audio_path.write_bytes(resp.content)

        size_mb = audio_path.stat().st_size / 1024 / 1024
        if size_mb < 0.001:
            print("  Audio download failed or empty", file=sys.stderr)
            audio_path.unlink(missing_ok=True)
            return None
        if size_mb > max_size_mb:
            print(f"  Audio too large ({size_mb:.1f}MB > {max_size_mb}MB), skipping Groq", file=sys.stderr)
            audio_path.unlink(missing_ok=True)
            return None

        print(f"  Audio downloaded: {size_mb:.1f}MB")
        return audio_path
    except Exception as e:
        print("  Audio download failed: " + str(e), file=sys.stderr)
        audio_path.unlink(missing_ok=True)
        return None


def _transcribe_groq(audio_path, duration_ms=0):
    """Transcribe audio file using Groq Whisper API.

    Uses whisper-large-v3-turbo for fast, accurate Chinese transcription.
    Falls back to local faster-whisper if Groq is unavailable.
    """
    if not audio_path or not GROQ_API_KEY:
        return ""

    if duration_ms and duration_ms > 600000:
        print(f"  Video too long ({duration_ms/1000:.0f}s), skipping transcription", file=sys.stderr)
        return ""

    try:
        import httpx

        with open(audio_path, "rb") as f:
            files = {"file": ("audio.mp4", f, "audio/mp4")}
            data = {
                "model": GROQ_MODEL,
                "language": "zh",
                "temperature": "0.0",
                "response_format": "json",
            }
            resp = httpx.post(
                f"{GROQ_BASE_URL}/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files=files, data=data, timeout=60,
            )

        if resp.status_code == 429:
            print("  Groq rate limited, retrying after pause...", file=sys.stderr)
            import time
            time.sleep(5)
            with open(audio_path, "rb") as f:
                files = {"file": ("audio.mp4", f, "audio/mp4")}
                resp = httpx.post(
                    f"{GROQ_BASE_URL}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files=files, data=data, timeout=60,
                )

        resp.raise_for_status()
        result = resp.json()
        text = result.get("text", "").strip()

        if text:
            print(f"  Groq Whisper done: {len(text)} chars")
            return text
        print("  Groq returned empty text", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"  Groq failed: {e}", file=sys.stderr)
        return ""


def _transcribe_whisper_local(audio_path, duration_ms=0):
    """Fallback: transcribe audio with local faster-whisper (tiny model, CPU)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("  faster-whisper not installed, skipping local fallback", file=sys.stderr)
        return ""

    if not audio_path:
        return ""
    if duration_ms and duration_ms > 600000:
        return ""

    try:
        print("  Running local Whisper (tiny, Chinese)...")
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(
            str(audio_path), language="zh", beam_size=3,
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        print(f"  Local Whisper done: {len(text)} chars")
        return text
    except Exception as e:
        print(f"  Local Whisper failed: {e}", file=sys.stderr)
        return ""


def _parse_subtitle_file(path):
    """Parse SRT/VTT subtitle file to plain text."""
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.strip().split("\n")
    texts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\d+$", line):
            continue
        if re.match(r"[\d:,.\-]+ --> [\d:,.\-]+$", line):
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "#")):
            continue
        cleaned = re.sub(r"<[^>]+>", "", line)
        if cleaned and len(cleaned) > 1:
            texts.append(cleaned)
    return " ".join(texts)


def _extract_keyframes(video_url, max_frames=5):
    """Download video and extract keyframes using ffmpeg.

    Returns list of frame file paths, or empty list on failure.
    """
    try:
        import tempfile
        import subprocess
        import httpx

        if not video_url:
            return []

        print("  Downloading video for keyframe extraction...")
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "video.mp4"
            with httpx.Client(timeout=60, follow_redirects=True, verify=False) as client:
                resp = client.get(video_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.douyin.com/",
                })
                resp.raise_for_status()
                video_path.write_bytes(resp.content)

            if video_path.stat().st_size < 1000:
                print("  Video download failed", file=sys.stderr)
                return []

            print(f"  Video: {video_path.stat().st_size/1024/1024:.1f}MB")

            # Get video duration
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                capture_output=True, text=True, timeout=15,
            )
            try:
                duration = float(probe.stdout.strip())
            except ValueError:
                duration = 60

            # Calculate frame intervals
            interval = max(1, int(duration / (max_frames + 1)))
            frames = []
            for i in range(max_frames):
                ts = i * interval
                frame_path = Path(tmpdir) / f"frame_{i}.jpg"
                result = subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(ts), "-i", str(video_path),
                     "-frames:v", "1", "-q:v", "4",
                     "-vf", "scale=640:-1",
                     str(frame_path)],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0 and frame_path.exists():
                    frames.append(frame_path)

            print(f"  Extracted {len(frames)} keyframes")
            return frames
    except FileNotFoundError:
        print("  ffmpeg not found", file=sys.stderr)
        return []
    except Exception as e:
        print("  Keyframe extraction failed: " + str(e), file=sys.stderr)
        return []


def _analyze_keyframes(frame_paths, title=""):
    """Send keyframes to GLM-4V for content analysis."""
    if not frame_paths or not CLIENT:
        return ""
    try:
        import base64

        content_parts = [{"type": "text", "text": (
            "Analyze these keyframes from a short video. "
            "Extract ALL visible text (titles, subtitles, bullet points, captions). "
            "Describe what is being presented (slides, demo, talking head, etc.).\n"
            "Output a detailed content summary in Traditional Chinese, structured as:\n"
            "1. 一句話總結\n"
            "2. 影片中的可見文字（逐字提取）\n"
            "3. 畫面內容描述\n"
            "4. 3-5 個核心要點（每點 40-80 字）\n\n"
            "Video title: " + title + "\n"
        )}]
        for fp in frame_paths:
            b64 = base64.b64encode(fp.read_bytes()).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })

        print(f"  Sending {len(frame_paths)} frames to GLM-4V...")
        resp = rate_limited_call(
            messages=[{"role": "user", "content": content_parts}],
            max_tokens=1000,
            temperature=0.3,
        )
        text = resp.choices[0].message.content.strip()
        print(f"  GLM-4V analysis: {len(text)} chars")
        return text
    except Exception as e:
        print("  GLM-4V analysis failed: " + str(e), file=sys.stderr)
        return ""


def _fill_content(meta):
    title = meta.get("title", "")
    tags = meta.get("tags", [])
    author = meta.get("author", "")
    url = meta.get("url", "")
    video_url = meta.get("video_url", "")
    duration = meta.get("duration", 0)

    content = ""
    source = ""

    if url:
        # Priority 1: yt-dlp subtitles (fastest, rare)
        print("  [1] Trying yt-dlp subtitles...")
        content = _fetch_subtitles(url)
        if content:
            source = "subtitle"
            print("  Subtitle found: " + content[:50] + "...")

        # Priority 2: GLM-4V keyframe analysis (3-5s, most videos)
        if not content and video_url:
            print("  [2] Trying GLM-4V keyframe analysis...")
            frames = _extract_keyframes(video_url)
            if frames:
                content = _analyze_keyframes(frames, title)
                if content:
                    source = "keyframe_vlm"
                    print("  GLM-4V success: " + content[:50] + "...")

        # Priority 3: Groq Whisper API (fast, accurate)
        if not content and video_url:
            print("  [3] Downloading audio for transcription...")
            audio_path = _download_audio(video_url)
            if audio_path:
                content = _transcribe_groq(audio_path, duration)
                if content:
                    source = "groq_whisper"
                    print("  Groq success: " + content[:50] + "...")

        # Priority 4: Local Whisper fallback (slow, tiny model)
        if not content and audio_path:
            print("  [4] Trying local Whisper fallback...")
            content = _transcribe_whisper_local(audio_path, duration)
            if content:
                source = "whisper_local"
                print("  Local Whisper success: " + content[:50] + "...")

        # Cleanup temp audio
        if audio_path:
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass

    if content:
        meta["_subtitle"] = True
        meta["_subtitle_text"] = content
        meta["_content_source"] = source

    summary = _generate_summary(title, tags, author, url, content)
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
    _trigger_wiki_rebuild()
    return True


def _trigger_wiki_rebuild():
    try:
        from rebuild_concepts import build_concept_page, build_index, load_videos, CONCEPT_MAP
        videos = load_videos()
        concept_counts = {}
        for cn_name, cfg in CONCEPT_MAP.items():
            filename, description, tags, categories = cfg
            content, count = build_concept_page(cn_name, filename, description, tags, categories, videos)
            concept_counts[cn_name] = count
            out_path = Path(WIKI_CONCEPTS) / (filename + ".md")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        index_content = build_index(concept_counts)
        Path(WIKI_INDEX).write_text(index_content, encoding="utf-8")
        print("Wiki rebuilt automatically")
    except Exception as e:
        print("Wiki rebuild skipped: " + str(e), file=sys.stderr)


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

    print("[1/4] Fetching metadata...")
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

    print("[2/4] Extracting content (subtitle → keyframe → whisper)...")
    print("[3/4] Generating summary...")
    summary = _fill_content(meta)
    result.core_points = summary
    result.has_subtitle = bool(meta.get("_subtitle", False))

    if dry_run:
        result.success = True
        return result

    print("[4/4] Saving...")
    ok = _save_video(meta, summary)
    if ok:
        result.success = True
        data = _load_json()
        for v in data.get("videos", []):
            if result.aweme_id and result.aweme_id in v.get("file", ""):
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
