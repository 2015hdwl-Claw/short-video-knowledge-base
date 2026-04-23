#!/usr/bin/env python3
"""Knowledge evolution tracker for the short-video knowledge base.

Takes snapshots of wiki state and computes diffs between them to track
how the knowledge base evolves over time.

CLI:
    python scripts/evolution_tracker.py            # take snapshot + diff
    python scripts/evolution_tracker.py --diff     # only diff, no new snapshot
"""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
JSON_PATH = REPO / "short-videos" / "short-videos.json"
WIKI_DIR = REPO / "wiki"
CONCEPTS_DIR = WIKI_DIR / "concepts"
INSIGHTS_DIR = WIKI_DIR / "insights"
EVOLUTION_DIR = WIKI_DIR / "evolution"
SNAPSHOTS_DIR = EVOLUTION_DIR / "snapshots"
DIFFS_DIR = EVOLUTION_DIR / "diffs"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glm_limiter import rate_limited_call


def _extract_llm_content(resp):
    msg = resp.choices[0].message
    content = msg.content or ""
    if not content.strip() and hasattr(msg, "reasoning_content") and msg.reasoning_content:
        content = msg.reasoning_content
    return content


def _load_videos():
    """Load all videos from short-videos.json."""
    if not JSON_PATH.exists():
        return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("videos", [])


def _content_hash(filepath):
    """Compute SHA-256 hash of a file's content."""
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return f"sha256:{h.hexdigest()[:16]}"


def _get_week_label(dt=None):
    """Return ISO week label like 2026-W17."""
    dt = dt or datetime.now()
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def take_snapshot():
    """Take a snapshot of the current knowledge base state.

    Returns:
        dict with snapshot data including stats and content hashes.
    """
    videos = _load_videos()
    cats = Counter(v.get("category", "未分類") for v in videos)
    all_tags = []
    for v in videos:
        all_tags.extend(v.get("tags", []))
    top_tags = [{"tag": t, "count": c} for t, c in Counter(all_tags).most_common(20)]

    concept_pages = list(CONCEPTS_DIR.glob("*.md")) if CONCEPTS_DIR.exists() else []
    content_hashes = {}
    for cp in sorted(concept_pages):
        content_hashes[cp.name] = _content_hash(cp)

    insight_count = len(list(INSIGHTS_DIR.glob("*.md"))) if INSIGHTS_DIR.exists() else 0

    snapshot = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "week": _get_week_label(),
        "stats": {
            "total_videos": len(videos),
            "category_distribution": dict(cats.most_common()),
            "concept_pages": len(concept_pages),
            "insights": insight_count,
            "top_tags": top_tags,
        },
        "content_hashes": content_hashes,
    }

    # Save snapshot
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = SNAPSHOTS_DIR / f"{snapshot['week']}.json"
    snap_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Snapshot saved: {snap_path}")
    return snapshot


def _find_latest_snapshot():
    """Find the most recent snapshot file."""
    if not SNAPSHOTS_DIR.exists():
        return None
    snapshots = sorted(SNAPSHOTS_DIR.glob("*.json"))
    if not snapshots:
        return None
    # Exclude current week if we want the previous one
    current_week = _get_week_label()
    for sp in reversed(snapshots):
        if sp.stem != current_week:
            with open(sp, "r", encoding="utf-8") as f:
                return json.load(f)
    # Only current week exists, return the earliest
    with open(snapshots[0], "r", encoding="utf-8") as f:
        return json.load(f)


def compute_diff(old_snapshot, new_snapshot):
    """Compute diff between two snapshots.

    Returns:
        dict with changes in videos, categories, pages, and tags.
    """
    old_stats = old_snapshot.get("stats", {})
    new_stats = new_snapshot.get("stats", {})

    old_total = old_stats.get("total_videos", 0)
    new_total = new_stats.get("total_videos", 0)
    video_delta = new_total - old_total

    # Category changes
    old_cats = old_stats.get("category_distribution", {})
    new_cats = new_stats.get("category_distribution", {})
    cat_changes = {}
    for cat in set(list(old_cats.keys()) + list(new_cats.keys())):
        old_c = old_cats.get(cat, 0)
        new_c = new_cats.get(cat, 0)
        if old_c != new_c:
            cat_changes[cat] = {"old": old_c, "new": new_c, "delta": new_c - old_c}

    # Page changes (content hash comparison)
    old_hashes = old_snapshot.get("content_hashes", {})
    new_hashes = new_snapshot.get("content_hashes", {})
    added_pages = [p for p in new_hashes if p not in old_hashes]
    removed_pages = [p for p in old_hashes if p not in new_hashes]
    modified_pages = [
        p for p in new_hashes
        if p in old_hashes and new_hashes[p] != old_hashes[p]
    ]

    # Tag changes
    old_tags = {t["tag"]: t["count"] for t in old_stats.get("top_tags", [])}
    new_tags = {t["tag"]: t["count"] for t in new_stats.get("top_tags", [])}
    new_tag_names = [t for t in new_tags if t not in old_tags]

    diff = {
        "old_week": old_snapshot.get("week", "unknown"),
        "new_week": new_snapshot.get("week", "unknown"),
        "video_delta": video_delta,
        "old_total": old_total,
        "new_total": new_total,
        "category_changes": cat_changes,
        "added_pages": added_pages,
        "removed_pages": removed_pages,
        "modified_pages": modified_pages,
        "new_tags": new_tag_names,
    }

    # Save diff as markdown
    DIFFS_DIR.mkdir(parents=True, exist_ok=True)
    diff_filename = f"{diff['old_week']}-to-{diff['new_week']}"
    diff_path = DIFFS_DIR / f"{diff_filename}.md"

    md = _build_diff_markdown(diff)
    diff_path.write_text(md, encoding="utf-8")
    print(f"Diff saved: {diff_path}")

    return diff


def _build_diff_markdown(diff):
    """Build markdown diff report."""
    lines = [
        f"# 知識演化 {diff['old_week']} -> {diff['new_week']}",
        "",
        "## 數據變化",
        f"- 影片：{'+' if diff['video_delta'] >= 0 else ''}{diff['video_delta']}"
        f"（{diff['old_total']} -> {diff['new_total']}）",
    ]

    for cat, ch in sorted(diff["category_changes"].items()):
        sign = "+" if ch["delta"] >= 0 else ""
        lines.append(f"- {cat}：{sign}{ch['delta']}（{ch['old']} -> {ch['new']}）")

    lines.append("")
    lines.append("## 頁面更新")

    for p in diff["added_pages"]:
        lines.append(f"- {p}：新增")
    for p in diff["modified_pages"]:
        lines.append(f"- {p}：內容更新")
    for p in diff["removed_pages"]:
        lines.append(f"- {p}：移除")

    lines.append("")
    lines.append("## 新增標籤")
    for t in diff["new_tags"]:
        lines.append(f"- {t}")
    if not diff["new_tags"]:
        lines.append("- 無")

    lines.append("")
    lines.append("## 趨勢分析")
    lines.append("[待 LLM 分析]")
    lines.append("")

    return "\n".join(lines)


def _llm_trend_analysis(diff):
    """Use LLM to generate trend analysis for a diff."""
    summary = (
        f"影片數 {diff['old_total']} -> {diff['new_total']} "
        f"(+{diff['video_delta']}), "
        f"新增頁面 {len(diff['added_pages'])}, "
        f"修改頁面 {len(diff['modified_pages'])}, "
        f"新增標籤 {', '.join(diff['new_tags'][:10]) or '無'}"
    )

    messages = [
        {
            "role": "system",
            "content": "你是知識庫演化分析師。根據數據變化，用繁體中文寫 50-100 字的趨勢分析摘要。",
        },
        {
            "role": "user",
            "content": f"分析這週知識庫的變化：{summary}",
        },
    ]

    try:
        resp = rate_limited_call(messages, max_tokens=200, temperature=0.5)
        return _extract_llm_content(resp)
    except Exception as e:
        return f"[LLM 分析失敗：{e}]"


def run_evolution(diff_only=False):
    """Run evolution tracking: take snapshot, compute diff, optionally analyze.

    Args:
        diff_only: If True, only compute diff without taking new snapshot.

    Returns:
        dict with diff, snapshot_path, has_significant_changes.
    """
    old_snapshot = _find_latest_snapshot()

    if diff_only and not old_snapshot:
        print("No previous snapshot found for diff. Taking first snapshot.")
        diff_only = False

    if diff_only:
        # Use current state as new snapshot but don't save
        videos = _load_videos()
        cats = Counter(v.get("category", "未分類") for v in videos)
        all_tags = []
        for v in videos:
            all_tags.extend(v.get("tags", []))
        top_tags = [{"tag": t, "count": c} for t, c in Counter(all_tags).most_common(20)]
        concept_pages = list(CONCEPTS_DIR.glob("*.md")) if CONCEPTS_DIR.exists() else []
        content_hashes = {}
        for cp in sorted(concept_pages):
            content_hashes[cp.name] = _content_hash(cp)
        insight_count = len(list(INSIGHTS_DIR.glob("*.md"))) if INSIGHTS_DIR.exists() else 0

        new_snapshot = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "week": _get_week_label(),
            "stats": {
                "total_videos": len(videos),
                "category_distribution": dict(cats.most_common()),
                "concept_pages": len(concept_pages),
                "insights": insight_count,
                "top_tags": top_tags,
            },
            "content_hashes": content_hashes,
        }
    else:
        new_snapshot = take_snapshot()

    result = {
        "snapshot_path": str(SNAPSHOTS_DIR / f"{new_snapshot['week']}.json"),
        "has_significant_changes": False,
        "diff": None,
    }

    if old_snapshot:
        diff = compute_diff(old_snapshot, new_snapshot)

        significant = (
            diff["video_delta"] != 0
            or diff["added_pages"]
            or diff["modified_pages"]
        )
        result["has_significant_changes"] = significant
        result["diff"] = {
            "old_week": diff["old_week"],
            "new_week": diff["new_week"],
            "video_delta": diff["video_delta"],
        }

        if significant:
            # Enhance diff with LLM trend analysis
            trend = _llm_trend_analysis(diff)
            diff_path = DIFFS_DIR / f"{diff['old_week']}-to-{diff['new_week']}.md"
            if diff_path.exists():
                content = diff_path.read_text(encoding="utf-8")
                content = content.replace("[待 LLM 分析]", trend)
                diff_path.write_text(content, encoding="utf-8")
    else:
        print("No previous snapshot to compare with. This is the first snapshot.")

    return result


def main():
    parser = argparse.ArgumentParser(description="Knowledge evolution tracker")
    parser.add_argument("--diff", action="store_true",
                        help="Only compute diff, no new snapshot")
    args = parser.parse_args()

    result = run_evolution(diff_only=args.diff)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
