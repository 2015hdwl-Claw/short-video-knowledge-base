#!/usr/bin/env python3
"""Auto cross-reference builder for wiki pages.

Scans all concept/entity pages, detects unlinked mentions,
and inserts [[wikilinks]] in the "相關概念" section.

Usage:
    python scripts/cross_reference.py            # dry-run
    python scripts/cross_reference.py --apply     # write changes
"""

import json
import os
import re
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WIKI_CONCEPTS = os.path.join(REPO, "wiki", "concepts")
WIKI_ENTITIES = os.path.join(REPO, "wiki", "entities")
JSON_PATH = os.path.join(REPO, "short-videos", "short-videos.json")


def build_page_registry():
    registry = {}
    for dirpath in [WIKI_CONCEPTS, WIKI_ENTITIES]:
        if not os.path.isdir(dirpath):
            continue
        rel_dir = os.path.relpath(dirpath, os.path.join(REPO, "wiki"))
        for fname in os.listdir(dirpath):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(dirpath, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
            title = first_line.lstrip("# ").strip()
            if not title:
                continue
            link_path = os.path.join(rel_dir, fname).replace("\\", "/")
            registry[title] = {
                "path": fpath,
                "link": link_path,
                "filename": fname.replace(".md", ""),
            }
    return registry


def extract_mentions(content, registry):
    self_title_line = content.split("\n", 1)[0].lstrip("# ").strip()
    existing_links = set(re.findall(r"\[\[(.+?)\]\]", content))
    existing_titles = set()
    for link_text in existing_links:
        for title in registry:
            if title in link_text:
                existing_titles.add(title)
    mentions = {}
    for title, info in registry.items():
        if title == self_title_line:
            continue
        if title in existing_titles:
            continue
        count = content.count(title)
        if count > 0:
            mentions[title] = {"count": count, "link": info["link"]}
    return mentions


def build_cross_refs(videos):
    tag_to_concepts = {}
    for v in videos:
        cat = v.get("category", "")
        tags = v.get("tags", [])
        for tag in tags:
            tag = tag.strip()
            if tag not in tag_to_concepts:
                tag_to_concepts[tag] = set()
            if cat:
                tag_to_concepts[tag].add(cat)
    concept_pairs = {}
    tag_list = sorted(tag_to_concepts.keys())
    for i in range(len(tag_list)):
        for j in range(i + 1, len(tag_list)):
            shared = tag_to_concepts[tag_list[i]] & tag_to_concepts[tag_list[j]]
            if shared:
                key = tuple(sorted([tag_list[i], tag_list[j]]))
                concept_pairs[key] = len(shared)
    return concept_pairs


def _build_related_section(mentions, registry):
    if not mentions:
        return "- （待建立連結）"
    sorted_mentions = sorted(mentions.items(), key=lambda x: -x[1]["count"])
    lines = []
    for title, info in sorted_mentions[:8]:
        link = info["link"]
        lines.append(f"- [[{title}|{link}]]")
    return "\n".join(lines)


def apply_cross_references(dry_run=True):
    registry = build_page_registry()
    print(f"Registry: {len(registry)} pages")
    for title, info in registry.items():
        print(f"  {title} -> {info['link']}")

    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        videos = data.get("videos", [])
        cross_refs = build_cross_refs(videos)
        print(f"\nCross-ref pairs from tags: {len(cross_refs)}")
    else:
        cross_refs = {}

    total_changes = 0
    for title, info in registry.items():
        fpath = info["path"]
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        mentions = extract_mentions(content, registry)
        if not mentions:
            continue
        related_text = _build_related_section(mentions, registry)
        old_marker = "- （待建立連結）"
        if old_marker not in content:
            continue
        new_content = content.replace(old_marker, related_text, 1)
        if new_content == content:
            continue
        total_changes += 1
        print(f"\n{title}:")
        for mtitle, minfo in sorted(mentions.items(), key=lambda x: -x[1]["count"])[:8]:
            print(f"  + [[{mtitle}]] ({minfo['count']} mentions)")
        if not dry_run:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)

    print(f"\nTotal pages updated: {total_changes}")
    if dry_run:
        print("(DRY-RUN: no files written)")
    return total_changes


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build wiki cross-references")
    parser.add_argument("--apply", action="store_true", help="Write changes")
    args = parser.parse_args()
    apply_cross_references(dry_run=not args.apply)


if __name__ == "__main__":
    main()
