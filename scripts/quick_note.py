#!/usr/bin/env python3
"""
隨身筆記系統 v2 - 支援提醒 + 編輯
觸發方式：
  記下：內容
  記下：內容，提醒 2026-04-15 09:00
  編輯筆記：內容關鍵字 → 新內容
"""

import json
import os
import re
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

KNOWLEDGE_BASE = Path(os.environ.get("KNOWLEDGE_BASE", "/root/knowledge-base"))
RAW_NOTES_DIR = KNOWLEDGE_BASE / "raw" / "notes"
WIKI_DIR = KNOWLEDGE_BASE / "wiki"
LOG_FILE = WIKI_DIR / "log.md"


def parse_reminder(text: str) -> tuple:
    """從文字中提取提醒時間
    支援格式：
    - 提醒明天 9點
    - 提醒 2026-04-15 09:00
    - 提醒 3天後
    - 提醒 2小時後
    """
    patterns = [
        # 明天 HH:MM
        (r'提醒\s*明天\s*(\d{1,2})[：:點](\d{0,2})', lambda m: _tomorrow(int(m.group(1)), int(m.group(2) or 0))),
        # 提醒 YYYY-MM-DD HH:MM
        (r'提醒\s*(\d{4}-\d{2}-\d{2})\s*(\d{1,2})[：:點](\d{0,2})', lambda m: f"{m.group(1)} {int(m.group(2)):02d}:{int(m.group(3) or 0):02d}"),
        # 提醒 N天後
        (r'提醒\s*(\d+)\s*天後', lambda m: _days_later(int(m.group(1)))),
        # 提醒 N小時後
        (r'提醒\s*(\d+)\s*小時後', lambda m: _hours_later(int(m.group(1)))),
        # 提醒 N分鐘後
        (r'提醒\s*(\d+)\s*分鐘後', lambda m: _minutes_later(int(m.group(1)))),
        # 提醒 HH:MM (今天)
        (r'提醒\s*(\d{1,2})[：:點](\d{0,2})$', lambda m: _today(int(m.group(1)), int(m.group(2) or 0))),
    ]
    
    for pattern, handler in patterns:
        m = re.search(pattern, text)
        if m:
            return handler(m), text[:m.start()].rstrip('，, ').strip()
    
    return None, text


def _tomorrow(h, m):
    dt = datetime.now() + timedelta(days=1)
    return f"{dt.strftime('%Y-%m-%d')} {h:02d}:{m:02d}"


def _today(h, m):
    return datetime.now().strftime(f"%Y-%m-%d {h:02d}:{m:02d}")


def _days_later(n):
    dt = datetime.now() + timedelta(days=n)
    return dt.strftime("%Y-%m-%d 09:00")


def _hours_later(n):
    dt = datetime.now() + timedelta(hours=n)
    return dt.strftime("%Y-%m-%d %H:%M")


def _minutes_later(n):
    dt = datetime.now() + timedelta(minutes=n)
    return dt.strftime("%Y-%m-%d %H:%M")


def save_note(content: str, tags: list = None, source: str = "quick-note", reminder: str = None) -> dict:
    """保存筆記"""
    RAW_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    date = datetime.now().strftime("%Y-%m-%d")
    filename = f"{timestamp}.md"
    filepath = RAW_NOTES_DIR / filename
    
    tags_str = ", ".join(tags) if tags else ""
    reminder_str = f"**提醒**：{reminder}" if reminder else ""
    
    md = f"""# 隨身筆記

**日期**：{date}
**時間**：{datetime.now().strftime("%H:%M")}
**來源**：{source}
**標籤**：{tags_str}
{reminder_str}

---

{content}
"""
    filepath.write_text(md, encoding="utf-8")
    
    meta = {
        "file": str(filepath.relative_to(KNOWLEDGE_BASE)),
        "title": content[:50].replace("\n", " "),
        "date": date,
        "time": datetime.now().strftime("%H:%M"),
        "source": source,
        "tags": tags or [],
        "type": "note",
        "reminder": reminder
    }
    
    return meta


def edit_note(search_text: str, new_content: str) -> dict:
    """編輯筆記（根據關鍵字找到筆記並替換內容）"""
    if not RAW_NOTES_DIR.exists():
        return {"error": "無筆記目錄"}
    
    notes = sorted(RAW_NOTES_DIR.glob("*.md"), reverse=True)
    
    for f in notes:
        text = f.read_text(encoding="utf-8")
        if search_text in text:
            # Replace the content section (after the last ---)
            parts = text.rsplit("---\n", 1)
            if len(parts) == 2:
                header = parts[0] + "---\n"
                new_text = header + new_content + "\n"
                f.write_text(new_text, encoding="utf-8")
                return {"edited": str(f.relative_to(KNOWLEDGE_BASE)), "found": True}
            else:
                # Simple replace
                new_text = text.replace(search_text, new_content)
                f.write_text(new_text, encoding="utf-8")
                return {"edited": str(f.relative_to(KNOWLEDGE_BASE)), "found": True}
    
    return {"error": f"找不到包含「{search_text}」的筆記"}


def append_to_log(action: str, detail: str):
    date = datetime.now().strftime("%Y-%m-%d")
    time = datetime.now().strftime("%H:%M")
    if LOG_FILE.exists():
        content = LOG_FILE.read_text(encoding="utf-8")
    else:
        content = "# 處理日誌\n\n"
    if f"## {date}" not in content:
        content += f"\n## {date}\n"
    content += f"- **{time} [{action}]**: {detail}\n"
    LOG_FILE.write_text(content, encoding="utf-8")


def find_related_concepts(note_content: str) -> list:
    concepts_dir = WIKI_DIR / "concepts"
    entities_dir = WIKI_DIR / "entities"
    related = []
    note_lower = note_content.lower()
    for d in [concepts_dir, entities_dir]:
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            concept_name = f.stem
            if concept_name in note_content or concept_name.lower() in note_lower:
                related.append(concept_name)
            elif any(kw in note_lower for kw in concept_name.lower().split() if len(kw) > 1):
                related.append(concept_name)
    return related


def ingest_note_to_wiki(note_content: str, note_title: str, note_date: str, tags: list = None):
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
                note_entry = f"- 📝 {note_title} — 隨身筆記（{note_date}）"
                if note_entry not in content:
                    if "## 我的筆記" not in content:
                        content += "\n## 我的筆記\n\n"
                    content += f"{note_entry}\n"
                    filepath.write_text(content, encoding="utf-8")
                    updated_concepts.append(concept)
    if updated_concepts:
        append_to_log("Ingest", f"筆記「{note_title[:30]}」→ 更新 {', '.join(f'[[{c}]]' for c in updated_concepts)}")
    return updated_concepts


def rebuild_notes_json():
    """重建 notes.json 索引"""
    notes = []
    if RAW_NOTES_DIR.exists():
        for f in sorted(RAW_NOTES_DIR.glob("*.md"), reverse=True):
            content = f.read_text(encoding="utf-8")
            date_m = re.search(r'\*\*日期\*\*：(\S+)', content)
            time_m = re.search(r'\*\*時間\*\*：(\S+)', content)
            source_m = re.search(r'\*\*來源\*\*：(\S+)', content)
            tags_m = re.search(r'\*\*標籤\*\*：(.+)', content)
            reminder_m = re.search(r'\*\*提醒\*\*：(\S+\s+\S+)', content)
            body = re.split(r'---\s*\n', content, maxsplit=2)
            body_text = body[-1].strip() if len(body) > 2 else ""
            tags = []
            if tags_m:
                tags = [t.strip() for t in tags_m.group(1).split(",") if t.strip()]
            notes.append({
                "file": str(f.relative_to(KNOWLEDGE_BASE)),
                "date": date_m.group(1) if date_m else "",
                "time": time_m.group(1) if time_m else "",
                "source": source_m.group(1) if source_m else "",
                "tags": tags,
                "content": body_text,
                "reminder": reminder_m.group(1) if reminder_m else None
            })
    (KNOWLEDGE_BASE / "notes.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(notes)


def process_note(content: str, tags: list = None, source: str = "quick-note", do_ingest: bool = True) -> dict:
    """完整流程：保存筆記 → ingest 到 wiki"""
    # Check for reminder
    reminder, clean_content = parse_reminder(content)
    if clean_content:
        content = clean_content
    
    meta = save_note(content, tags, source, reminder)
    
    result = {
        "saved": meta["file"],
        "related_concepts": []
    }
    
    if do_ingest:
        related = ingest_note_to_wiki(content, meta["title"], meta["date"], tags)
        result["related_concepts"] = related
    
    if reminder:
        result["reminder"] = reminder
    
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  quick_note.py <content> [tags] [source]  # save note")
        print("  quick_note.py --edit <search> <replace>     # edit note")
        print("  quick_note.py --rebuild                      # rebuild notes.json")
        sys.exit(1)
    
    if sys.argv[1] == "--edit":
        if len(sys.argv) < 4:
            print("Usage: quick_note.py --edit <search_text> <new_content>")
            sys.exit(1)
        result = edit_note(sys.argv[2], sys.argv[3])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif sys.argv[1] == "--rebuild":
        count = rebuild_notes_json()
        print(f"Rebuilt notes.json with {count} notes")
    
    else:
        content = sys.argv[1]
        tags = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] else []
        source = sys.argv[3] if len(sys.argv) > 3 else "quick-note"
        result = process_note(content, tags, source)
        print(json.dumps(result, ensure_ascii=False, indent=2))
