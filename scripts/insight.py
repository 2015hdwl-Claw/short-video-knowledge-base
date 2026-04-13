#!/usr/bin/env python3
"""Save an insight/lesson to wiki/insights/"""

import sys, os, json, datetime

REPO = os.path.dirname(os.path.abspath(__file__))
INSIGHTS_DIR = os.path.join(REPO, '..', 'wiki', 'insights')
os.makedirs(INSIGHTS_DIR, exist_ok=True)

def save(title, content, concepts=None, tags=None):
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    slug = title[:30].replace(' ', '-').replace('/', '_')
    filepath = os.path.join(INSIGHTS_DIR, f"{date}-{slug}.md")
    
    md = f"# {title}\n\n"
    md += f"> {content[:100]}...\n\n" if len(content) > 100 else f"> {content}\n\n"
    md += f"## 💡 洞見\n\n{content}\n\n"
    if concepts:
        md += "## 🔗 相關概念\n\n"
        for c in concepts:
            md += f"- [[{c}]]\n"
        md += "\n"
    if tags:
        md += f"**標籤**：{', '.join(tags)}\n\n"
    md += f"---\n📅 {date} | 🏷️ {', '.join(tags or ['未分類'])}\n"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"✅ Saved: {filepath}")
    return filepath

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 insight.py \"Title\" \"Content\" [concept1,concept2]")
        sys.exit(1)
    title = sys.argv[1]
    content = sys.argv[2]
    concepts = sys.argv[3].split(',') if len(sys.argv) > 3 else []
    save(title, content, concepts)
