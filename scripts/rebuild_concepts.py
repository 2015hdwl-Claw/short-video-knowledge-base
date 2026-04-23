#!/usr/bin/env python3
"""Rebuild concept pages from short-videos.json.

Usage:
    python scripts/rebuild_concepts.py          # rebuild all concept pages
    python scripts/rebuild_concepts.py --v2     # rebuild with LLM synthesis
    python scripts/rebuild_concepts.py --push   # rebuild + git commit & push
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glm_limiter import rate_limited_call

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
JSON_PATH = os.path.join(REPO, "short-videos", "short-videos.json")
CONCEPTS_DIR = os.path.join(REPO, "wiki", "concepts")
INDEX_PATH = os.path.join(REPO, "wiki", "index.md")

SYNTHESIS_SYSTEM_PROMPT = (
    "你是一位知識管理專家。你的任務是從多段短影音摘要中，"
    "綜合出一篇結構化的概念頁面。\n"
    "規則：\n"
    "1. 不要逐條列影片，而是找出共同主題和模式\n"
    "2. 每個主題用一段話（100-200字）綜合多部影片的觀點\n"
    "3. 標注來源：每個觀點後面用 (來源：影片標題) 標注\n"
    "4. 如果有矛盾觀點，用 ⚠️ 標記並說明\n"
    "5. 使用繁體中文\n"
    "6. 輸出 Markdown 格式"
)

SYNTHESIS_USER_TEMPLATE = (
    "以下是「{concept_name}」主題的 {video_count} 部影片摘要。\n"
    "請綜合成一篇概念頁面，格式如下：\n"
    "## 核心洞察（2-3 句話概括整體趨勢）\n"
    "## 主題分析\n"
    "### 主題1：[名稱]\n"
    "[綜合 3-5 部影片的觀點，100-200 字]\n"
    "### 主題2：[名稱]\n"
    "...\n"
    "## 爭議與矛盾\n"
    "⚠️ [如果有不同觀點]\n"
    "## 實用建議\n"
    "- [從影片中提取的可執行建議]\n"
    "---\n"
    "影片摘要：\n"
    "{formatted_videos}"
)

MERGE_USER_TEMPLATE = (
    "以下是「{concept_name}」主題的多批次綜合結果。\n"
    "請將它們合併為一篇統一的綜合頁面，去除重複，保留最有價值的觀點。\n"
    "格式：\n"
    "## 核心洞察\n"
    "## 主題分析\n"
    "## 爭議與矛盾\n"
    "## 實用建議\n"
    "---\n"
    "各批次綜合：\n"
    "{batch_syntheses}"
)

CONCEPT_MAP = {
    "AI工具與編程": {
        "filename": "ai-coding-tools",
        "description": "Claude Code、OpenClaw、Codex 等 AI 編程工具與生態",
        "tags": ["AI", "AI編程"],
        "categories": ["AI"],
    },
    "AI趨勢與產業": {
        "filename": "ai-trends",
        "description": "AI 行業動態、大模型發展與社會影響",
        "tags": ["AI趨勢"],
        "categories": ["AI", "科技"],
    },
    "財經投資理財": {
        "filename": "finance-investing",
        "description": "投資思維、市場分析與財富管理",
        "tags": ["財經"],
        "categories": ["財經"],
    },
    "心理學與認知": {
        "filename": "psychology",
        "description": "心理學原理、情緒管理與認知偏誤",
        "tags": ["心理學"],
        "categories": ["心理學"],
    },
    "健康養生": {
        "filename": "health",
        "description": "減脂、健身、睡眠與飲食健康",
        "tags": ["健康"],
        "categories": ["健康"],
    },
    "創業與商業模式": {
        "filename": "entrepreneurship",
        "description": "創業思維、商業模式與流量變現",
        "tags": ["創業", "商業模式"],
        "categories": ["創業", "個人成長"],
    },
    "學習與知識管理": {
        "filename": "learning",
        "description": "學習方法、知識管理與自我提升",
        "tags": ["學習"],
        "categories": ["教育", "個人成長"],
    },
    "科學歷史與人文": {
        "filename": "science-history",
        "description": "科學原理、歷史事件與社會現象",
        "tags": ["科學", "歷史"],
        "categories": ["教育", "科技"],
    },
}


def load_videos():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("videos", [])


def matches_concept(video, concept_cfg):
    """Check if a video belongs to a concept by tags or category."""
    vid_tags = [t.strip() for t in video.get("tags", [])]
    vid_cat = video.get("category", "").strip()
    for tag in concept_cfg["tags"]:
        if tag in vid_tags:
            return True
    if vid_cat and vid_cat in concept_cfg["categories"]:
        return True
    return False


def format_points(core_points):
    """Parse core_points string into individual bullet lines."""
    if not core_points or not core_points.strip():
        return []
    lines = core_points.strip().split("\n")
    bullets = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Strip leading number pattern like "1. " or "- "
        cleaned = line
        for prefix in ("1. ", "2. ", "3. ", "4. ", "5. ", "6. ", "7. ", "8. ", "9. ", "10. "):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break
        else:
            if cleaned.startswith("- "):
                cleaned = cleaned[2:]
        cleaned = cleaned.strip()
        if cleaned:
            bullets.append(cleaned)
    return bullets


def build_video_entry(video):
    """Build a single video entry block for the concept page."""
    title = video.get("title", "Unknown")
    source = video.get("source", "")
    date = video.get("date", "")

    header_parts = [title]
    meta_line = " | ".join(p for p in [source, date] if p)

    lines = [f"**{title}**"]
    if meta_line:
        lines[0] = f"{lines[0]} | {meta_line}"

    points = format_points(video.get("core_points", ""))
    if points:
        for pt in points:
            lines.append(f"- {pt}")
    else:
        lines.append(f"- {title}")

    return "\n".join(lines)


def build_video_list_entry(video):
    """Build a compact single-line entry for the related videos list."""
    title = video.get("title", "Unknown")
    points = format_points(video.get("core_points", ""))
    summary = points[0][:80] + "..." if points else title[:80] + "..."
    return f"- **{title}** — {summary}"


def _extract_content(resp):
    msg = resp.choices[0].message
    content = msg.content or ""
    if not content.strip() and hasattr(msg, "reasoning_content") and msg.reasoning_content:
        content = msg.reasoning_content
    return content


def _format_videos_for_prompt(videos):
    parts = []
    for v in videos:
        title = v.get("title", "Unknown")
        cp = v.get("core_points", "").strip()
        if not cp:
            continue
        entry = f"【{title}】\n{cp}\n"
        advice = v.get("advice", "").strip()
        if advice:
            entry += f"建議：{advice}\n"
        parts.append(entry)
    return "\n".join(parts)


def _batch_videos_for_synthesis(videos, max_chars_per_batch=8000):
    batches = []
    current_batch = []
    current_chars = 0
    for v in videos:
        cp = v.get("core_points", "").strip()
        if not cp:
            continue
        entry = f"【{v.get('title', 'Unknown')}】\n{cp}\n"
        entry_len = len(entry)
        if current_batch and current_chars + entry_len > max_chars_per_batch:
            batches.append(current_batch)
            current_batch = [v]
            current_chars = entry_len
        else:
            current_batch.append(v)
            current_chars += entry_len
    if current_batch:
        batches.append(current_batch)
    return batches


def _generate_batch_synthesis(concept_name, concept_desc, videos):
    formatted = _format_videos_for_prompt(videos)
    user_msg = SYNTHESIS_USER_TEMPLATE.format(
        concept_name=concept_name,
        video_count=len(videos),
        formatted_videos=formatted,
    )
    messages = [
        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    resp = rate_limited_call(
        messages,
        max_tokens=4096,
        temperature=0.3,
    )
    return _extract_content(resp)


def _merge_syntheses(concept_name, concept_desc, batch_syntheses):
    combined = "\n\n---批次分隔---\n\n".join(batch_syntheses)
    user_msg = MERGE_USER_TEMPLATE.format(
        concept_name=concept_name,
        batch_syntheses=combined,
    )
    messages = [
        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    resp = rate_limited_call(
        messages,
        max_tokens=4096,
        temperature=0.2,
    )
    return _extract_content(resp)


def build_concept_page_v2(chinese_name, concept_cfg, videos):
    matched = [v for v in videos if matches_concept(v, concept_cfg)]
    matched.sort(key=lambda v: v.get("date", "") or "0000", reverse=True)

    today = datetime.date.today().isoformat()
    has_content = sum(1 for v in matched if v.get("core_points", "").strip())

    if not matched or has_content == 0:
        return build_concept_page(chinese_name, concept_cfg, videos)

    try:
        batches = _batch_videos_for_synthesis(matched)
        print(f"    v2: {len(matched)} videos -> {len(batches)} batch(es)")

        if len(batches) == 1:
            synthesis = _generate_batch_synthesis(
                chinese_name, concept_cfg["description"], batches[0]
            )
        else:
            batch_syntheses = []
            for i, batch in enumerate(batches):
                print(f"    synthesizing batch {i+1}/{len(batches)} ({len(batch)} videos)")
                s = _generate_batch_synthesis(
                    chinese_name, concept_cfg["description"], batch
                )
                batch_syntheses.append(s)
            print(f"    merging {len(batch_syntheses)} batches")
            synthesis = _merge_syntheses(
                chinese_name, concept_cfg["description"], batch_syntheses
            )

        lines = [
            f"# {chinese_name}",
            "",
            f"> {concept_cfg['description']}",
            "",
            "## 📌 AI 綜合分析",
            "",
            synthesis,
            "",
            f"## 📹 相關影片 ({len(matched)} 筆)",
            "",
        ]
        for video in matched:
            lines.append(build_video_list_entry(video))
        lines.append("")

        lines.append("## 🔗 相關概念")
        lines.append("")
        lines.append("- （待建立連結）")
        lines.append("")
        lines.append("---")
        lines.append(
            f"📅 {today} | 📹 {len(matched)} 筆 | "
            f"📝 {has_content} 筆有內容 | 🤖 AI 綜合 v2"
        )
        lines.append("")

        return "\n".join(lines), len(matched)

    except Exception as e:
        print(f"    v2 synthesis failed ({e}), falling back to v1")
        return build_concept_page(chinese_name, concept_cfg, videos)


def build_concept_page(chinese_name, concept_cfg, videos):
    """Generate the full markdown content for a concept page."""
    matched = [v for v in videos if matches_concept(v, concept_cfg)]
    # Sort by date descending, missing dates last
    matched.sort(key=lambda v: v.get("date", "") or "0000", reverse=True)

    today = datetime.date.today().isoformat()
    has_content = sum(
        1 for v in matched if v.get("core_points", "").strip()
    )

    lines = [
        f"# {chinese_name}",
        "",
        f"> {concept_cfg['description']}",
        "",
        "## 📌 核心觀點綜合",
        "",
    ]

    for video in matched:
        lines.append(build_video_entry(video))
        lines.append("")

    lines.append(f"## 📹 相關影片 ({len(matched)} 筆)")
    lines.append("")

    for video in matched:
        lines.append(build_video_list_entry(video))
    lines.append("")

    lines.append("## 🔗 相關概念")
    lines.append("")
    lines.append("- （待建立連結）")
    lines.append("")
    lines.append("---")
    lines.append(
        f"📅 {today} | 📹 {len(matched)} 筆 | 📝 {has_content} 筆有內容"
    )
    lines.append("")

    return "\n".join(lines), len(matched)


def build_index(concept_counts):
    """Rebuild wiki/index.md with updated video counts."""
    total_videos = sum(concept_counts.values())

    # Preserve insights section if it exists
    insights_lines = []
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            original = f.read()
        # Extract everything after "## 💡 洞見記錄"
        marker = "## 💡 洞見記錄"
        idx = original.find(marker)
        if idx != -1:
            insights_lines = original[idx:].strip().split("\n")

    today = datetime.date.today().isoformat()

    lines = [
        "# 🧠 短影音知識 Wiki",
        "",
        "> AI 自動從短影音中提取的結構化知識庫",
        "",
        "## 📂 概念索引",
        "",
        "| 概念 | 描述 | 影片數 |",
        "|------|------|:------:|",
    ]

    # Order matching the original index.md
    display_order = [
        "AI工具與編程", "AI趨勢與產業", "創業與商業模式",
        "科學歷史與人文", "學習與知識管理", "財經投資理財",
        "健康養生", "心理學與認知",
    ]

    for cn_name in display_order:
        cfg = CONCEPT_MAP[cn_name]
        count = concept_counts.get(cn_name, 0)
        link = f"[{cn_name}](concepts/{cfg['filename']}.md)"
        lines.append(f"| {link} | {cfg['description']} | {count} |")

    lines.append("")

    if insights_lines:
        lines.extend(insights_lines)
        lines.append("")

    lines.append("---")
    lines.append(
        f"*📅 {today} 更新 | 📹 {total_videos} 筆影片 | 🧠 {len(CONCEPT_MAP)} 個概念*"
    )
    lines.append("")

    return "\n".join(lines)


def git_push():
    """Stage, commit and push concept page changes."""
    os.chdir(REPO)
    subprocess.run(
        ["git", "add", "wiki/concepts/", "wiki/index.md"],
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: rebuild concept pages from short-videos.json"],
        check=True,
    )
    subprocess.run(["git", "push"], check=False)


def main():
    parser = argparse.ArgumentParser(description="Rebuild concept pages")
    parser.add_argument("--push", action="store_true", help="Git commit & push after rebuild")
    parser.add_argument("--v2", action="store_true", help="Use LLM synthesis (v2 concept pages)")
    args = parser.parse_args()

    if not os.path.exists(JSON_PATH):
        print(f"Error: {JSON_PATH} not found", file=sys.stderr)
        sys.exit(1)

    os.makedirs(CONCEPTS_DIR, exist_ok=True)
    videos = load_videos()
    print(f"Loaded {len(videos)} videos")

    build_fn = build_concept_page_v2 if args.v2 else build_concept_page
    if args.v2:
        print("Using v2 (LLM synthesis) mode")

    concept_counts = {}
    for cn_name, cfg in CONCEPT_MAP.items():
        content, count = build_fn(cn_name, cfg, videos)
        concept_counts[cn_name] = count
        out_path = os.path.join(CONCEPTS_DIR, f"{cfg['filename']}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {cn_name}: {count} videos -> {out_path}")

    # Rebuild index
    index_content = build_index(concept_counts)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(index_content)
    print(f"  Index updated: {INDEX_PATH}")

    if args.push:
        print("\nPushing to remote...")
        git_push()
        print("Done.")
    else:
        print("\nRebuild complete. Use --push to commit and push.")


if __name__ == "__main__":
    main()
