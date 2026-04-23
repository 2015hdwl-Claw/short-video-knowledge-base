#!/usr/bin/env python3
"""One-time script to normalize video categories to Traditional Chinese enum.

Usage:
    python scripts/normalize_categories.py            # dry-run
    python scripts/normalize_categories.py --apply     # write changes
"""

import json
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
JSON_PATHS = [
    os.path.join(REPO, "short-videos", "short-videos.json"),
    os.path.join(REPO, "short-videos.json"),
]

CATEGORY_ENUM = ["AI", "教育", "個人成長", "財經", "健康", "心理學", "科技", "創業"]

CATEGORY_MAP = {
    "财经": "財經",
    "个人成长": "個人成長",
    "商业": "創業",
    "Personal Growth": "個人成長",
    "Other": "個人成長",
    "Finance": "財經",
    "Health": "健康",
    "Psychology": "心理學",
    "Education": "教育",
    "Technology": "科技",
    "Entrepreneurship": "創業",
}

VALID_SET = set(CATEGORY_ENUM)

SIMILAR_MAP = {
    "理財": "財經",
    "投資": "財經",
    "金融": "財經",
    "心理": "心理學",
    "認知": "心理學",
    "成長": "個人成長",
    "自我": "個人成長",
    "學習": "教育",
    "知識": "教育",
    "科學": "科技",
    "技術": "科技",
    "創新": "科技",
    "商業": "創業",
    "生意": "創業",
    "副業": "創業",
}


def _fuzzy_match(raw: str) -> str | None:
    for keyword, cat in SIMILAR_MAP.items():
        if keyword in raw:
            return cat
    return None


def normalize_category(raw_cat: str) -> tuple[str, str]:
    if not raw_cat:
        return "個人成長", "empty_default"
    if raw_cat in VALID_SET:
        return raw_cat, "exact"
    mapped = CATEGORY_MAP.get(raw_cat)
    if mapped:
        return mapped, "map"
    fuzzy = _fuzzy_match(raw_cat)
    if fuzzy:
        return fuzzy, "fuzzy"
    return "個人成長", "fallback"


def normalize_all(dry_run=True) -> dict:
    stats = {"total": 0, "changed": 0, "unchanged": 0, "details": {}}
    for path in JSON_PATHS:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        videos = data.get("videos", [])
        changed_indices = []
        for i, v in enumerate(videos):
            stats["total"] += 1
            old_cat = v.get("category", "")
            new_cat, method = normalize_category(old_cat)
            if new_cat != old_cat:
                stats["changed"] += 1
                key = f"{repr(old_cat)} -> {repr(new_cat)}"
                stats["details"][key] = stats["details"].get(key, 0) + 1
                v["category"] = new_cat
                changed_indices.append(i)
                if dry_run:
                    print(f"  [{path}] #{i}: {repr(old_cat)} -> {repr(new_cat)} ({method})")
            else:
                stats["unchanged"] += 1
        if not dry_run and changed_indices:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  Written {len(changed_indices)} changes to {path}")
    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Normalize video categories")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()

    dry_run = not args.apply
    print(f"Mode: {'DRY-RUN' if dry_run else 'APPLY'}")
    print()
    stats = normalize_all(dry_run=dry_run)
    print()
    print(f"Total: {stats['total']} videos")
    print(f"Changed: {stats['changed']}")
    print(f"Unchanged: {stats['unchanged']}")
    if stats["details"]:
        print("\nChanges breakdown:")
        for change, count in sorted(stats["details"].items(), key=lambda x: -x[1]):
            print(f"  {change}: {count}")


if __name__ == "__main__":
    main()
