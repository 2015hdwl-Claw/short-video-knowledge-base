#!/usr/bin/env python3
"""Wiki Lint - 矛盾偵測與健康檢查

用法：python3 lint_wiki.py
輸出：wiki/lint-report.md
"""

import os, json, re, glob

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CONCEPTS_DIR = os.path.join(REPO, 'wiki', 'concepts')
JSON_PATH = os.path.join(REPO, 'short-videos', 'short-videos.json')
REPORT_PATH = os.path.join(REPO, 'brainstorming', 'health', 'lint-report.md')

def load_videos():
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['videos']

def load_concepts():
    concepts = {}
    for f in glob.glob(os.path.join(CONCEPTS_DIR, '*.md')):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, 'r', encoding='utf-8') as fh:
            concepts[name] = fh.read()
    return concepts

def extract_points(text):
    """Extract numbered/bulleted points from text"""
    lines = text.split('\n')
    points = []
    for line in lines:
        line = line.strip()
        if re.match(r'^[\d\-\*•]', line) and len(line) > 10:
            clean = re.sub(r'^[\d\.\-\*•\s]+', '', line).strip()
            if clean:
                points.append(clean)
    return points

def find_potential_contradictions(videos):
    """Find videos in same category with potentially conflicting views"""
    from collections import defaultdict
    by_cat = defaultdict(list)
    for v in videos:
        cp = v.get('core_points', '').strip()
        if cp and len(cp) > 30 and cp != '短影音分析報告':
            by_cat[v.get('category', 'unknown')].append(v)
    
    contradictions = []
    for cat, vids in by_cat.items():
        if len(vids) < 2:
            continue
        # Check for opposing keywords
        positive_kws = ['機會', '利好', '增長', '賺', '成功', '看好', '樂觀', '崛起']
        negative_kws = ['風險', '危機', '衰退', '虧', '失敗', '看空', '悲觀', '泡沫', '崩潰', '取代', '淘汰']
        
        for i, v1 in enumerate(vids):
            for v2 in vids[i+1:]:
                cp1 = v1.get('core_points', '')
                cp2 = v2.get('core_points', '')
                title1 = v1.get('title', '')
                title2 = v2.get('title', '')
                
                v1_pos = sum(1 for kw in positive_kws if kw in cp1)
                v1_neg = sum(1 for kw in negative_kws if kw in cp1)
                v2_pos = sum(1 for kw in positive_kws if kw in cp2)
                v2_neg = sum(1 for kw in negative_kws if kw in cp2)
                
                # One positive, one negative on similar topic
                if (v1_pos > 0 and v2_neg > 0) or (v1_neg > 0 and v2_pos > 0):
                    contradictions.append({
                        'level': '🟡',
                        'type': '觀點不同',
                        'v1': title1[:50],
                        'v2': title2[:50],
                        'v1_sentiment': '樂觀' if v1_pos > v1_neg else '悲觀',
                        'v2_sentiment': '樂觀' if v2_pos > v2_neg else '悲觀',
                        'category': cat
                    })
    
    return contradictions

def check_orphan_pages(concepts, videos):
    """Find concept pages with very few videos"""
    orphans = []
    all_tags = []
    for v in videos:
        all_tags.extend(v.get('tags', []))
    
    tag_counts = {}
    for t in all_tags:
        tag_counts[t] = tag_counts.get(t, 0) + 1
    
    for name, content in concepts.items():
        # Count video references
        refs = len(re.findall(r'- \*\*|^- ', content))
        if refs < 3:
            orphans.append({
                'concept': name,
                'refs': refs,
                'suggestion': '需要更多相關影片來豐富此概念頁面'
            })
    
    return orphans

def check_content_gaps(videos):
    """Find videos without core_points"""
    no_content = []
    for v in videos:
        cp = v.get('core_points', '').strip()
        if not cp or cp == '短影音分析報告' or len(cp) < 20:
            no_content.append(v.get('title', 'Unknown')[:60])
    return no_content

def check_stale_dates(videos):
    """Find videos with empty dates"""
    no_date = [v.get('title', '')[:60] for v in videos if not v.get('date')]
    return no_date

def find_similar_titles(videos):
    """Find potential duplicates"""
    from collections import defaultdict
    seen = defaultdict(list)
    for v in videos:
        # Normalize title for comparison
        t = v.get('title', '')[:30].replace(' ', '')
        seen[t].append(v.get('title', '')[:60])
    
    dupes = []
    for key, titles in seen.items():
        if len(titles) > 1:
            dupes.append(titles)
    return dupes

def generate_report(contradictions, orphans, no_content, no_date, dupes):
    import datetime
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    md = f"# 🔍 Wiki 健康檢查報告\n\n> 自動生成於 {date}\n\n"
    
    # Summary
    md += "## 📊 摘要\n\n"
    md += f"| 檢查項目 | 結果 |\n|----------|------|\n"
    md += f"| 🟡 觀點差異 | {len(contradictions)} 處 |\n"
    md += f"| 📄 內容不足的概念頁 | {len(orphans)} 個 |\n"
    md += f"| ❌ 缺少摘要的影片 | {len(no_content)} 筆 |\n"
    md += f"| 📅 缺少日期的影片 | {len(no_date)} 筆 |\n"
    md += f"| 🔁 可能重複 | {len(dupes)} 組 |\n"
    md += "\n"
    
    # Contradictions
    if contradictions:
        md += "## 🟡 觀點差異\n\n"
        for c in contradictions[:20]:
            md += f"**{c['level']}** [{c['category']}] {c['v1_sentiment']} vs {c['v2_sentiment']}\n"
            md += f"- 「{c['v1']}」\n"
            md += f"- 「{c['v2']}」\n\n"
    
    # Orphans
    if orphans:
        md += "## 📄 內容不足的概念頁\n\n"
        for o in orphans:
            md += f"- **{o['concept']}** — 僅 {o['refs']} 筆引用。{o['suggestion']}\n"
        md += "\n"
    
    # No content
    if no_content:
        md += f"## ❌ 缺少摘要的影片（{len(no_content)} 筆）\n\n"
        for t in no_content[:20]:
            md += f"- {t}\n"
        if len(no_content) > 20:
            md += f"- ... 還有 {len(no_content) - 20} 筆\n"
        md += "\n"
    
    # No date
    if no_date:
        md += f"## 📅 缺少日期的影片（{len(no_date)} 筆）\n\n"
        for t in no_date[:10]:
            md += f"- {t}\n"
        md += "\n"
    
    # Duplicates
    if dupes:
        md += f"## 🔁 可能重複的影片（{len(dupes)} 組）\n\n"
        for d in dupes[:10]:
            for t in d:
                md += f"- {t}\n"
            md += "\n"
    
    md += "---\n*下次建議：補充缺少摘要的影片、豐富內容不足的概念頁*\n"
    
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"✅ Report saved: {REPORT_PATH}")

if __name__ == '__main__':
    print("🔍 Running Wiki Lint...")
    videos = load_videos()
    concepts = load_concepts()
    
    print(f"  Videos: {len(videos)}, Concepts: {len(concepts)}")
    
    contradictions = find_potential_contradictions(videos)
    orphans = check_orphan_pages(concepts, videos)
    no_content = check_content_gaps(videos)
    no_date = check_stale_dates(videos)
    dupes = find_similar_titles(videos)
    
    generate_report(contradictions, orphans, no_content, no_date, dupes)
    print(f"  🟡 Contradictions: {len(contradictions)}")
    print(f"  📄 Orphan pages: {len(orphans)}")
    print(f"  ❌ No content: {len(no_content)}")
    print(f"  📅 No date: {len(no_date)}")
    print(f"  🔁 Duplicates: {len(dupes)}")
