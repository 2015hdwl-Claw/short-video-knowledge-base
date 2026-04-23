#!/usr/bin/env python3
"""Export wiki to Obsidian vault format.

Reads wiki/ content and converts to an Obsidian-compatible vault with
Chinese filenames and wikilinks, then packages as tar.gz.

CLI:
    python scripts/export_obsidian.py
    python scripts/export_obsidian.py --output /tmp/my-vault
"""

import argparse
import io
import json
import os
import re
import sys
import tarfile
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
JSON_PATH = REPO / "short-videos" / "short-videos.json"
WIKI_DIR = REPO / "wiki"
CONCEPTS_DIR = WIKI_DIR / "concepts"
ENTITIES_DIR = WIKI_DIR / "entities"
INSIGHTS_DIR = WIKI_DIR / "insights"
DIGESTS_DIR = WIKI_DIR / "digests"

DEFAULT_OUTPUT = REPO / "obsidian-vault"


def _load_videos():
    """Load all videos from short-videos.json."""
    if not JSON_PATH.exists():
        return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("videos", [])


def _extract_h1(filepath):
    """Extract the first h1 heading from a markdown file."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return None


def _build_wikilink_map():
    """Build mapping from English filename (without .md) to Chinese h1 title.

    Returns:
        dict: {"ai-coding-tools": "AI工具與編程", ...}
    """
    mapping = {}
    if not CONCEPTS_DIR.exists():
        return mapping

    for fp in CONCEPTS_DIR.glob("*.md"):
        slug = fp.stem  # e.g. "ai-coding-tools"
        h1 = _extract_h1(fp)
        if h1:
            mapping[slug] = h1
    return mapping


def _replace_wikilinks(content, wikilink_map):
    """Replace English wikilinks with Chinese titles in content.

    [[ai-coding-tools]] -> [[AI工具與編程]]
    [[Claude]] -> [[Claude]] (unchanged, not in map)
    """
    def replacer(match):
        slug = match.group(1)
        if slug in wikilink_map:
            return f"[[{wikilink_map[slug]}]]"
        return match.group(0)

    return re.sub(r"\[\[([^\]]+?)\]\]", replacer, content)


def _generate_source_moc(video, wikilink_map):
    """Generate an Obsidian source MOC page for a single video."""
    title = video.get("title", "Untitled")
    source = video.get("source", "unknown")
    date = video.get("date", "unknown")
    category = video.get("category", "未分類")
    core_points = video.get("core_points", "")
    advice = video.get("advice", "")
    tags = video.get("tags", [])

    # Build concept links
    concept_links = []
    for tag in tags[:5]:
        # Check if tag matches a concept slug or h1
        if tag in wikilink_map:
            concept_links.append(f"- [[{wikilink_map[tag]}]]")
        else:
            concept_links.append(f"- [[{tag}]]")

    lines = [
        f"# {title}",
        f"> 來源：{source} | 日期：{date} | 分類：{category}",
        "",
        "## 摘要",
        core_points or "（無摘要）",
        "",
        "## 相關概念",
    ]
    lines.extend(concept_links if concept_links else ["- （無相關概念）"])
    lines.append("")
    if advice:
        lines.extend(["## 建議", advice, ""])
    lines.extend(["---", f"分類：{category} | 標籤：{', '.join(tags) if tags else '無'}"])

    return "\n".join(lines)


def _safe_filename(name, max_len=80):
    """Sanitize a name for use as a filename."""
    # Remove characters not safe in filenames
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    cleaned = cleaned.strip('. ')
    return cleaned[:max_len] if cleaned else "untitled"


def export_to_obsidian(output_dir=None):
    """Export wiki content to Obsidian vault format.

    Args:
        output_dir: Output directory path. Defaults to obsidian-vault/ in repo.

    Returns:
        dict with exported_pages, exported_sources, vault_path, tar_path.
    """
    output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT
    wikilink_map = _build_wikilink_map()
    videos = _load_videos()

    # Create directory structure
    dirs = {
        "dashboard": output_dir / "00-Dashboard",
        "concepts": output_dir / "01-Concepts",
        "entities": output_dir / "02-Entities",
        "insights": output_dir / "03-Insights",
        "digests": output_dir / "04-Digests",
        "sources": output_dir / "05-Sources",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    exported_pages = 0
    exported_sources = 0

    # 00-Dashboard: wiki/index.md
    index_src = WIKI_DIR / "index.md"
    if index_src.exists():
        content = index_src.read_text(encoding="utf-8")
        content = _replace_wikilinks(content, wikilink_map)
        (dirs["dashboard"] / "Dashboard.md").write_text(content, encoding="utf-8")
        exported_pages += 1

    # 01-Concepts: Chinese filenames
    if CONCEPTS_DIR.exists():
        for fp in CONCEPTS_DIR.glob("*.md"):
            content = fp.read_text(encoding="utf-8")
            content = _replace_wikilinks(content, wikilink_map)
            h1 = wikilink_map.get(fp.stem, fp.stem)
            out_name = f"{_safe_filename(h1)}.md"
            (dirs["concepts"] / out_name).write_text(content, encoding="utf-8")
            exported_pages += 1

    # 02-Entities
    if ENTITIES_DIR.exists():
        for fp in ENTITIES_DIR.glob("*.md"):
            content = fp.read_text(encoding="utf-8")
            content = _replace_wikilinks(content, wikilink_map)
            (dirs["entities"] / fp.name).write_text(content, encoding="utf-8")
            exported_pages += 1

    # 03-Insights
    if INSIGHTS_DIR.exists():
        for fp in INSIGHTS_DIR.glob("*.md"):
            content = fp.read_text(encoding="utf-8")
            content = _replace_wikilinks(content, wikilink_map)
            (dirs["insights"] / fp.name).write_text(content, encoding="utf-8")
            exported_pages += 1

    # 04-Digests
    if DIGESTS_DIR.exists():
        for fp in DIGESTS_DIR.glob("*.md"):
            content = fp.read_text(encoding="utf-8")
            content = _replace_wikilinks(content, wikilink_map)
            (dirs["digests"] / fp.name).write_text(content, encoding="utf-8")
            exported_pages += 1

    # 05-Sources: one page per video
    for v in videos:
        title = v.get("title", "untitled")
        if not title.strip():
            title = "untitled"
        moc = _generate_source_moc(v, wikilink_map)
        safe_name = _safe_filename(title)
        # Add date to avoid collisions
        date_suffix = v.get("date", "unknown").replace("-", "")
        out_name = f"{safe_name}_{date_suffix}.md"
        (dirs["sources"] / out_name).write_text(moc, encoding="utf-8")
        exported_sources += 1

    # Package as tar.gz
    tar_path = output_dir.parent / f"{output_dir.name}.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for fpath in sorted(output_dir.rglob("*")):
            if fpath.is_file():
                tar.add(str(fpath), arcname=str(fpath.relative_to(output_dir.parent)))
    buf.seek(0)
    tar_path.write_bytes(buf.getvalue())

    print(f"Obsidian vault exported: {output_dir}")
    print(f"  Pages: {exported_pages}")
    print(f"  Sources: {exported_sources}")
    print(f"  Tar: {tar_path}")

    return {
        "exported_pages": exported_pages,
        "exported_sources": exported_sources,
        "vault_path": str(output_dir),
        "tar_path": str(tar_path),
    }


def main():
    parser = argparse.ArgumentParser(description="Export wiki to Obsidian vault")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output directory (default: obsidian-vault/)")
    args = parser.parse_args()

    result = export_to_obsidian(output_dir=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
