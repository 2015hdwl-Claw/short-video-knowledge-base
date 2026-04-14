#!/usr/bin/env python3
"""Rebuild concept pages from short-videos.json.

Usage:
    python scripts/rebuild_concepts.py          # rebuild all concept pages
    python scripts/rebuild_concepts.py --push   # rebuild + git commit & push
"""

import argparse, datetime, json, os, subprocess, sys

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
JSON_PATH = os.path.join(REPO, "short-videos", "short-videos.json")
CONCEPTS_DIR = os.path.join(REPO, "wiki", "concepts")
INDEX_PATH = os.path.join(REPO, "wiki", "index.md")

CONCEPT_MAP = {
    "AI工具與編程": ("ai-coding-tools", "Claude Code、OpenClaw、Codex 等 AI 編程工具與生態", ["AI", "AI編程"], ["AI"]),
    "AI趨勢與產業": ("ai-trends", "AI 行業動態、大模型發展與社會影響", ["AI趨勢"], ["AI"]),
    "財經投資理財": ("finance-investing", "投資思維、市場分析與財富管理", ["財經"], ["財經"]),
    "心理學與認知": ("psychology", "心理學原理、情緒管理與認知偏誤", ["心理學"], ["心理學"]),
    "健康養生": ("health", "減脂、健身、睡眠與飲食健康", ["健康"], ["健康"]),
    "創業與商業模式": ("entrepreneurship", "創業思維、商業模式與流量變現", ["創業", "商業模式"], ["個人成長"]),
    "學習與知識管理": ("learning", "學習方法、知識管理與自我提升", ["學習"], ["教育"]),
    "科學歷史與人文": ("science-history", "科學原理、歷史事件與社會現象", ["科學", "歷史"], ["教育"]),
}
DISPLAY_ORDER = list(CONCEPT_MAP.keys())


def load_videos():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("videos", [])


def matches_concept(video, tags, categories):
    vid_tags = [t.strip() for t in video.get("tags", [])]
    cat = video.get("category", "").strip()
    return any(t in vid_tags for t in tags) or (cat and cat in categories)


def format_points(text):
    if not text or not text.strip():
        return []
    bullets = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        for i in range(1, 11):
            p = f"{i}. "
            if line.startswith(p):
                line = line[len(p):]
                break
        else:
            if line.startswith("- "):
                line = line[2:]
        line = line.strip()
        if line:
            bullets.append(line)
    return bullets


def build_video_entry(v):
    title = v.get("title", "Unknown")
    source = v.get("source", "")
    date = v.get("date", "")
    meta = " | ".join(x for x in [source, date] if x)
    header = f"**{title}**" + (f" | {meta}" if meta else "")
    points = format_points(v.get("core_points", ""))
    body = "\n".join(f"- {pt}" for pt in points) if points else f"- {title}"
    return f"{header}\n{body}"


def build_concept_page(cn_name, filename, description, tags, categories, videos):
    matched = sorted(
        [v for v in videos if matches_concept(v, tags, categories)],
        key=lambda v: v.get("date", "") or "0000",
        reverse=True,
    )
    today = datetime.date.today().isoformat()
    has_content = sum(1 for v in matched if v.get("core_points", "").strip())
    L = [f"# {cn_name}", "", f"> {description}", "",
         "## \U0001f4cc \u6838\u5fc3\u89c0\u9ede\u7d9c\u5408", ""]
    for v in matched:
        L += [build_video_entry(v), ""]
    L.append(f"## \U0001f4f9 \u76f8\u95dc\u5f71\u7247 ({len(matched)} \u7b46)")
    L.append("")
    for v in matched:
        pts = format_points(v.get("core_points", ""))
        s = (pts[0][:80] + "...") if pts else (v.get("title", "")[:80] + "...")
        L.append(f"- **{v.get('title', 'Unknown')}** \u2014 {s}")
    L += ["", "## \U0001f517 \u76f8\u95dc\u6982\u5ff5", "",
          "- \uff08\u5f85\u5efa\u7acb\u9023\u7d50\uff09", "",
          "---",
          f"\U0001f4c5 {today} | \U0001f4f9 {len(matched)} \u7b46 | \U0001f4dd {has_content} \u7b46\u6709\u5167\u5bb9", ""]
    return "\n".join(L), len(matched)


def build_index(counts):
    total = sum(counts.values())
    insights = []
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            orig = f.read()
        marker = "\u6d1e\u898b\u8a18\u9304"
        idx = orig.find(marker)
        if idx != -1:
            h2_idx = orig.rfind("## ", 0, idx)
            if h2_idx != -1:
                insights = orig[h2_idx:].strip().split("\n")
    today = datetime.date.today().isoformat()
    L = ["# \U0001f9e0 \u77ed\u5f71\u97f3\u77e5\u8b58 Wiki", "",
         "> AI \u81ea\u52d5\u5f9e\u77ed\u5f71\u97f3\u4e2d\u63d0\u53d6\u7684\u7d50\u69cb\u5316\u77e5\u8b58\u5eab", "",
         "## \U0001f4c2 \u6982\u5ff5\u7d22\u5f15", "",
         "| \u6982\u5ff5 | \u63cf\u8ff0 | \u5f71\u7247\u6578 |",
         "|------|------|:------:|"]
    for cn in DISPLAY_ORDER:
        fn, desc, _, _ = CONCEPT_MAP[cn]
        c = counts.get(cn, 0)
        L.append(f"| [{cn}](concepts/{fn}.md) | {desc} | {c} |")
    L.append("")
    if insights:
        L += insights + [""]
    L += ["---",
          f"*\U0001f4c5 {today} \u66f4\u65b0 | \U0001f4f9 {total} \u7b46\u5f71\u7247 | \U0001f9e0 {len(CONCEPT_MAP)} \u500b\u6982\u5ff5*", ""]
    return "\n".join(L)


def git_push():
    os.chdir(REPO)
    subprocess.run(["git", "add", "wiki/concepts/", "wiki/index.md"], check=True)
    subprocess.run(["git", "commit", "-m", "chore: rebuild concept pages from short-videos.json"], check=True)
    subprocess.run(["git", "push"], check=False)


def main():
    p = argparse.ArgumentParser(description="Rebuild concept pages")
    p.add_argument("--push", action="store_true", help="Git commit & push after rebuild")
    args = p.parse_args()
    if not os.path.exists(JSON_PATH):
        print(f"Error: {JSON_PATH} not found", file=sys.stderr)
        sys.exit(1)
    os.makedirs(CONCEPTS_DIR, exist_ok=True)
    videos = load_videos()
    print(f"Loaded {len(videos)} videos")
    counts = {}
    for cn, (fn, desc, tags, cats) in CONCEPT_MAP.items():
        content, count = build_concept_page(cn, fn, desc, tags, cats, videos)
        counts[cn] = count
        path = os.path.join(CONCEPTS_DIR, f"{fn}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {cn}: {count} videos -> {path}")
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(build_index(counts))
    print(f"  Index updated: {INDEX_PATH}")
    if args.push:
        print("\nPushing to remote...")
        git_push()
        print("Done.")
    else:
        print("\nRebuild complete. Use --push to commit and push.")


if __name__ == "__main__":
    main()
