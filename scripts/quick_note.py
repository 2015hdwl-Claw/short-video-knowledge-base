#!/usr/bin/env python3
"""
隨身筆記系統 - Quick Note Capture & Wiki Ingest
觸發方式：在任何 channel 說「記下：xxx」或「note: xxx」
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

KNOWLEDGE_BASE = Path(os.environ.get("KNOWLEDGE_BASE", "/root/knowledge-base"))
RAW_NOTES_DIR = KNOWLEDGE_BASE / "raw" / "notes"
WIKI_DIR = KNOWLEDGE_BASE / "wiki"
LOG_FILE = WIKI_DIR / "log.md"


def save_note(content: str, tags: list = None, source: str = "quick-note") -> dict:
    """保存筆記到 raw/notes/ 並返回元數據"""
    RAW_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    date = datetime.now().strftime("%Y-%m-%d")
    filename = f"{timestamp}.md"
    filepath = RAW_NOTES_DIR / filename
    
    tags_str = ", ".join(tags) if tags else ""
    
    md = f"""# 隨身筆記

**日期**：{date}
**時間**：{datetime.now().strftime("%H:%M")}
**來源**：{source}
**標籤**：{tags_str}

---

{content}
"""
    filepath.write_text(md, encoding="utf-8")
    
    meta = {
        "file": str(filepath.relative_to(KNOWLEDGE_BASE)),
        "title": content[:50].replace("\n", " "),
        "date": date,
        "source": source,
        "tags": tags or [],
        "type": "note"
    }
    
    return meta


def append_to_log(action: str, detail: str):
    """追加到 wiki/log.md"""
    date = datetime.now().strftime("%Y-%m-%d")
    time = datetime.now().strftime("%H:%M")
    
    if LOG_FILE.exists():
        content = LOG_FILE.read_text(encoding="utf-8")
    else:
        content = "# 處理日誌\n\n"
    
    # Check if today's section exists
    if f"## {date}" not in content:
        content += f"\n## {date}\n"
    
    content += f"- **{time} [{action}]**: {detail}\n"
    LOG_FILE.write_text(content, encoding="utf-8")


def find_related_concepts(note_content: str) -> list:
    """從筆記內容中找到相關的 wiki 概念"""
    concepts_dir = WIKI_DIR / "concepts"
    entities_dir = WIKI_DIR / "entities"
    
    related = []
    note_lower = note_content.lower()
    
    for d in [concepts_dir, entities_dir]:
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            concept_name = f.stem
            # Simple keyword matching
            keywords = concept_name.lower().split()
            # Also check for Chinese characters
            if concept_name in note_content or concept_name.lower() in note_lower:
                related.append(concept_name)
            elif any(kw in note_lower for kw in keywords if len(kw) > 1):
                related.append(concept_name)
    
    return related


def ingest_note_to_wiki(note_content: str, note_title: str, note_date: str, tags: list = None):
    """將筆記攝取到 wiki（更新相關概念頁面）"""
    related = find_related_concepts(note_content)
    
    if not related:
        append_to_log("Ingest", f"筆記「{note_title[:30]}」→ 無匹配概念，已存檔")
        return related
    
    updated_concepts = []
    for concept in related:
        for d in [WIKI_DIR / "concepts", WIKI_DIR / "entities"]:
            filepath = d / f"{concept}.md"
            if filepath.exists():
                content = filepath.read_text(encoding="utf-8")
                
                # Add to 相關影片 section (or create 我的筆記 section)
                note_entry = f"- 📝 {note_title} — 隨身筆記（{note_date}）"
                if note_entry not in content:
                    if "## 我的筆記" not in content:
                        content += "\n## 我的筆記\n\n"
                    content += f"{note_entry}\n"
                    filepath.write_text(content, encoding="utf-8")
                    updated_concepts.append(concept)
    
    if updated_concepts:
        append_to_log("Ingest", 
            f"筆記「{note_title[:30]}」→ 更新 {', '.join(f'[[{c}]]' for c in updated_concepts)}")
    else:
        append_to_log("Ingest", f"筆記「{note_title[:30]}」→ 找到概念但無需更新")
    
    return updated_concepts


def process_note(content: str, tags: list = None, source: str = "quick-note", do_ingest: bool = True) -> dict:
    """完整流程：保存筆記 → ingest 到 wiki"""
    meta = save_note(content, tags, source)
    
    result = {
        "saved": meta["file"],
        "related_concepts": []
    }
    
    if do_ingest:
        related = ingest_note_to_wiki(content, meta["title"], meta["date"], tags)
        result["related_concepts"] = related
    
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: quick_note.py <content> [tag1,tag2,...] [source]")
        sys.exit(1)
    
    content = sys.argv[1]
    tags = sys.argv[2].split(",") if len(sys.argv) > 2 else []
    source = sys.argv[3] if len(sys.argv) > 3 else "quick-note"
    
    result = process_note(content, tags, source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
