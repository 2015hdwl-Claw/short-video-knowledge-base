#!/usr/bin/env python3
"""Weekly digest generator for the short-video knowledge base.

Reads recent videos, insights, and lint contradictions, then uses LLM
for a short trend summary and rule-based formatting for the full report.

CLI:
    python scripts/weekly_digest.py
    python scripts/weekly_digest.py --dry-run
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
JSON_PATH = REPO / "short-videos" / "short-videos.json"
WIKI_DIR = REPO / "wiki"
INSIGHTS_DIR = WIKI_DIR / "insights"
LINT_REPORT = WIKI_DIR / "lint-report.md"
DIGESTS_DIR = WIKI_DIR / "digests"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glm_limiter import rate_limited_call


def _load_videos():
    """Load all videos from short-videos.json."""
    if not JSON_PATH.exists():
        return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("videos", [])


def _filter_recent_videos(videos, days=7):
    """Return videos added within the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [v for v in videos if v.get("date", "") >= cutoff]


def _load_recent_insights(days=7):
    """Return list of recent insight titles."""
    if not INSIGHTS_DIR.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    insights = []
    for fp in sorted(INSIGHTS_DIR.glob("*.md")):
        if fp.name[:10] >= cutoff:
            content = fp.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("# "):
                    insights.append(line[2:].strip())
                    break
            else:
                insights.append(fp.stem)
    return insights


def _load_contradictions():
    """Extract contradiction entries from lint-report.md."""
    if not LINT_REPORT.exists():
        return []
    content = LINT_REPORT.read_text(encoding="utf-8")
    contradictions = []
    capture = False
    for line in content.splitlines():
        if "觀點差異" in line and line.startswith("##"):
            capture = True
            continue
        if line.startswith("## ") and capture:
            capture = False
            continue
        if capture and line.strip().startswith("**"):
            contradictions.append(line.strip().lstrip("* ").rstrip("*"))
    return contradictions[:10]


def _compute_stats(videos):
    """Compute category distribution and total counts."""
    cats = Counter(v.get("category", "未分類") for v in videos)
    all_tags = []
    for v in videos:
        all_tags.extend(v.get("tags", []))
    return {
        "total": len(videos),
        "category_dist": dict(cats.most_common()),
        "top_tags": Counter(all_tags).most_common(10),
    }


def _get_week_range():
    """Return (week_start, week_end, week_label) for current week."""
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    iso = week_start.isocalendar()
    week_label = f"{iso[0]}-W{iso[1]:02d}"
    return (
        week_start.strftime("%Y-%m-%d"),
        week_end.strftime("%Y-%m-%d"),
        week_label,
    )


def _llm_trend_summary(new_videos, stats):
    """Ask LLM for a 2-3 sentence trend summary."""
    cats = stats["category_dist"]
    top_cats = list(cats.items())[:3]
    cat_str = ", ".join(f"{k}({v})" for k, v in top_cats)
    video_titles = [v.get("title", "")[:30] for v in new_videos[:10]]
    titles_str = ", ".join(video_titles)

    messages = [
        {
            "role": "user",
            "content": (
                f"用繁體中文寫2-3句話總結本週短影音知識庫的趨勢。"
                f"本週新增{len(new_videos)}部影片。"
                f"分類：{cat_str}。"
                f"影片：{titles_str}。直接寫出來。"
            ),
        }
    ]
    try:
        resp = rate_limited_call(messages, max_tokens=200, temperature=0.3)
        text = _extract_llm_content(resp)
        # Filter out thinking process lines
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        good = [l for l in lines if not (l and l[0].isdigit() and ". **" in l[:8])]
        if good:
            return " ".join(good[:3])
        return text[:200]
    except Exception:
        return "本週趨勢分析暫時無法生成。"


def _build_digest_markdown(week_start, week_end, new_videos, new_insights,
                           contradictions, stats, trend_summary):
    """Build the digest markdown from data (rule-based)."""
    total = stats["total"]

    # Group videos by category
    by_cat = defaultdict(list)
    for v in new_videos:
        cat = v.get("category", "未分類")
        by_cat[cat].append(v)

    md = "## 本週概覽\n\n"
    md += f"本週（{week_start} ~ {week_end}）知識庫新增 **{len(new_videos)}** 部影片，"
    md += f"累計 **{total}** 部。"
    if new_insights:
        md += f" 新增 **{len(new_insights)}** 則洞見。"
    md += "\n\n"

    md += "## 新增知識點\n\n"
    for cat, videos in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        md += f"### {cat}\n\n"
        for v in videos:
            title = v.get("title", "")[:50]
            points = v.get("core_points", "")[:60]
            md += f"- **{title}**"
            if points:
                md += f"：{points}"
            md += "\n"
        md += "\n"

    md += "## 趨勢觀察\n\n"
    top_cats = list(stats["category_dist"].items())[:5]
    for cat, count in top_cats:
        md += f"- **{cat}**：{count} 部影片\n"
    md += f"\n**趨勢分析**：{trend_summary}\n\n"

    md += "## 本週精選 TOP 3\n\n"
    scored = sorted(new_videos, key=lambda v: len(v.get("core_points", "")), reverse=True)
    for i, v in enumerate(scored[:3], 1):
        title = v.get("title", "")
        cat = v.get("category", "")
        points = v.get("core_points", "")
        md += f"{i}. **{title}**（{cat}）\n"
        if points:
            md += f"   {points[:80]}\n"
    md += "\n"

    md += "## 知識缺口\n\n"
    existing_cats = set(stats["category_dist"].keys())
    common_cats = {"科技", "教育", "健康", "心理學", "創業", "財經", "AI", "個人成長"}
    missing = common_cats - existing_cats
    low_cats = [cat for cat, count in stats["category_dist"].items() if count < 5]
    if missing:
        md += "缺少以下分類的內容：" + "、".join(missing) + "\n"
    if low_cats:
        md += "以下分類內容較少（<5部）：" + "、".join(low_cats) + "\n"
    if not missing and not low_cats:
        md += "目前各分類覆蓋尚可，建議持續補充深度內容。\n"
    md += "\n"

    if contradictions:
        md += "## 觀點矛盾提醒\n\n"
        for c in contradictions[:5]:
            md += f"- {c}\n"
        md += "\n"

    return md


def generate_weekly_digest(dry_run=False):
    """Generate weekly digest.

    Returns:
        dict with keys: digest_path, new_count, total, week_label
    """
    videos = _load_videos()
    week_start, week_end, week_label = _get_week_range()
    recent = _filter_recent_videos(videos, days=7)
    new_insights = _load_recent_insights(days=7)
    contradictions = _load_contradictions()
    stats = _compute_stats(videos)

    # LLM for trend summary only (short call, thinking mode OK)
    trend_summary = _llm_trend_summary(recent, stats)

    # Rule-based markdown structure
    digest_content = _build_digest_markdown(
        week_start, week_end, recent, new_insights,
        contradictions, stats, trend_summary,
    )

    # Wrap in header/footer
    today_str = datetime.now().strftime("%Y-%m-%d")
    week_range = f"{week_start} ~ {week_end}"
    md = f"# 知識週報 {week_range}\n\n"
    md += f"> 自動生成於 {today_str}\n\n"
    md += digest_content
    md += f"\n\n---\n自動生成 | 本週 +{len(recent)} | 累計 {stats['total']}\n"

    # Save
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    digest_path = DIGESTS_DIR / f"{week_label}.md"

    if dry_run:
        print(f"[DRY RUN] Would save to: {digest_path}")
        print(f"Week: {week_range}")
        print(f"New videos: {len(recent)}")
        print(f"Total videos: {stats['total']}")
        print(f"New insights: {len(new_insights)}")
        print(f"Contradictions: {len(contradictions)}")
        print(f"\n--- Preview ---\n{md[:1000]}...")
        return {
            "digest_path": str(digest_path),
            "new_count": len(recent),
            "total": stats["total"],
            "week_label": week_label,
        }

    digest_path.write_text(md, encoding="utf-8")
    print(f"Weekly digest saved: {digest_path}")
    print(f"  New videos: {len(recent)}, Total: {stats['total']}, Insights: {len(new_insights)}")

    return {
        "digest_path": str(digest_path),
        "new_count": len(recent),
        "total": stats["total"],
        "week_label": week_label,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate weekly knowledge digest")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    args = parser.parse_args()

    result = generate_weekly_digest(dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
