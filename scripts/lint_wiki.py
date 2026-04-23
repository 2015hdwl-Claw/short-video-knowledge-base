#!/usr/bin/env python3
"""Wiki Lint - 矛盾偵測與健康檢查

用法：python3 lint_wiki.py [--semantic]
輸出：wiki/lint-report.md
"""

import os
import sys
import json
import re
import glob
import time
import argparse

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CONCEPTS_DIR = os.path.join(REPO, 'wiki', 'concepts')
JSON_PATH = os.path.join(REPO, 'short-videos', 'short-videos.json')
REPORT_PATH = os.path.join(REPO, 'wiki', 'lint-report.md')

# GLM API config — uses env vars with sensible defaults
API_KEY = os.getenv('CLASSIFIER_API_KEY', '')
BASE_URL = os.getenv('CLASSIFIER_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4/')
MODEL = os.getenv('CLASSIFIER_MODEL', 'glm-4.7-flash')

SEMANTIC_PROMPT = """你是知識庫矛盾偵測專家。分析以下兩段短影音摘要，判斷是否存在真正的邏輯矛盾。
「矛盾」定義：對同一事實或結論提出不可並存的說法。
「不矛盾」：不同角度、時間框架、前提條件、互補觀點。

影片A：{title1}
摘要：{cp1}

影片B：{title2}
摘要：{cp2}

回傳 JSON：
{{
  "contradiction": true/false,
  "type": "事實矛盾|結論矛盾|方法矛盾|時間性矛盾|不矛盾",
  "reason": "簡短說明（50字以內）",
  "quote_a": "從影片A摘要中逐字引用導致矛盾的原文",
  "quote_b": "從影片B摘要中逐字引用導致矛盾的原文",
  "severity": "high/medium/low",
  "resolution_suggestion": "建議處理方式"
}}"""

MAX_SEMANTIC_CALLS = 10
RATE_LIMIT_SEC = 1.0


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
    """Extract numbered/bulleted points from text."""
    lines = text.split('\n')
    points = []
    for line in lines:
        line = line.strip()
        if re.match(r'^[\d\-\*•]', line) and len(line) > 10:
            clean = re.sub(r'^[\d\.\-\*•\s]+', '', line).strip()
            if clean:
                points.append(clean)
    return points


def _keyword_overlap_score(cp1, cp2):
    """Compute simple word overlap between two texts for pair ranking."""
    words1 = set(re.findall(r'[\u4e00-\u9fff]+', cp1))
    words2 = set(re.findall(r'[\u4e00-\u9fff]+', cp2))
    if not words1 or not words2:
        return 0
    return len(words1 & words2)


def find_potential_contradictions(videos):
    """Find videos in same category with potentially conflicting views."""
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


def _call_llm_for_contradiction(title1, cp1, title2, cp2):
    """Send a single pair to GLM and return parsed JSON result."""
    prompt = SEMANTIC_PROMPT.format(title1=title1, cp1=cp1[:500], title2=title2, cp2=cp2[:500])
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{BASE_URL}chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return json.loads(text)


def find_semantic_contradictions(videos):
    """Use LLM to detect genuine semantic contradictions between video pairs.

    Groups by category, ranks pairs by keyword overlap, then checks top pairs
    up to MAX_SEMANTIC_CALLS API calls.
    """
    from collections import defaultdict

    if not API_KEY:
        print("  [semantic] No CLASSIFIER_API_KEY set, skipping LLM detection")
        return []

    by_cat = defaultdict(list)
    for v in videos:
        cp = v.get('core_points', '').strip()
        if cp and len(cp) > 30 and cp != '短影音分析報告':
            by_cat[v.get('category', 'unknown')].append(v)

    # Build candidate pairs: only categories with 3+ videos, rank by overlap
    candidates = []
    for cat, vids in by_cat.items():
        if len(vids) < 3:
            continue
        for i, v1 in enumerate(vids):
            for v2 in vids[i+1:]:
                score = _keyword_overlap_score(
                    v1.get('core_points', ''), v2.get('core_points', '')
                )
                if score > 0:
                    candidates.append((score, v1, v2, cat))

    # Sort by overlap descending, take top pairs
    candidates.sort(key=lambda x: x[0], reverse=True)
    budget = min(MAX_SEMANTIC_CALLS, len(candidates))

    contradictions = []
    errors = 0
    for idx, (score, v1, v2, cat) in enumerate(candidates[:budget]):
        try:
            result = _call_llm_for_contradiction(
                v1.get('title', ''),
                v1.get('core_points', ''),
                v2.get('title', ''),
                v2.get('core_points', ''),
            )
            if result.get('contradiction'):
                severity = result.get('severity', 'medium')
                level_map = {'high': '🔴', 'medium': '🟠', 'low': '🟡'}
                contradictions.append({
                    'level': level_map.get(severity, '🟠'),
                    'type': result.get('type', '語義矛盾'),
                    'v1': v1.get('title', '')[:50],
                    'v2': v2.get('title', '')[:50],
                    'v1_sentiment': '',
                    'v2_sentiment': '',
                    'category': cat,
                    'reason': result.get('reason', ''),
                    'severity': severity,
                    'quote_a': result.get('quote_a', ''),
                    'quote_b': result.get('quote_b', ''),
                    'resolution_suggestion': result.get('resolution_suggestion', ''),
                })
            print(f"  [semantic] Pair {idx+1}/{budget}: no contradiction")
        except requests.exceptions.HTTPError as e:
            errors += 1
            print(f"  [semantic] API error on pair {idx+1}: {e.response.status_code}")
        except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError) as e:
            errors += 1
            print(f"  [semantic] Error on pair {idx+1}: {e}")

        # Rate limiting between calls
        if idx < budget - 1:
            time.sleep(RATE_LIMIT_SEC)

    if errors:
        print(f"  [semantic] {errors}/{budget} calls failed")

    return contradictions


def check_orphan_pages(concepts, videos):
    """Find concept pages with very few videos."""
    orphans = []
    all_tags = []
    for v in videos:
        all_tags.extend(v.get('tags', []))

    tag_counts = {}
    for t in all_tags:
        tag_counts[t] = tag_counts.get(t, 0) + 1

    for name, content in concepts.items():
        refs = len(re.findall(r'- \*\*|^- ', content))
        if refs < 3:
            orphans.append({
                'concept': name,
                'refs': refs,
                'suggestion': '需要更多相關影片來豐富此概念頁面'
            })

    return orphans


def check_content_gaps(videos):
    """Find videos without core_points."""
    no_content = []
    for v in videos:
        cp = v.get('core_points', '').strip()
        if not cp or cp == '短影音分析報告' or len(cp) < 20:
            no_content.append(v.get('title', 'Unknown')[:60])
    return no_content


def check_stale_dates(videos):
    """Find videos with empty dates."""
    no_date = [v.get('title', '')[:60] for v in videos if not v.get('date')]
    return no_date


def find_similar_titles(videos):
    """Find potential duplicates."""
    from collections import defaultdict
    seen = defaultdict(list)
    for v in videos:
        t = v.get('title', '')[:30].replace(' ', '')
        seen[t].append(v.get('title', '')[:60])

    dupes = []
    for key, titles in seen.items():
        if len(titles) > 1:
            dupes.append(titles)
    return dupes


def generate_report(contradictions, orphans, no_content, no_date, dupes,
                    semantic_results=None):
    import datetime
    date = datetime.datetime.now().strftime("%Y-%m-%d")

    md = f"# 🔍 Wiki 健康檢查報告\n\n> 自動生成於 {date}\n\n"

    # Summary
    md += "## 📊 摘要\n\n"
    md += f"| 檢查項目 | 結果 |\n|----------|------|\n"
    md += f"| 🟡 觀點差異 | {len(contradictions)} 處 |\n"
    if semantic_results is not None:
        md += f"| 🤖 AI 語義矛盾 | {len(semantic_results)} 處 |\n"
    md += f"| 📄 內容不足的概念頁 | {len(orphans)} 個 |\n"
    md += f"| ❌ 缺少摘要的影片 | {len(no_content)} 筆 |\n"
    md += f"| 📅 缺少日期的影片 | {len(no_date)} 筆 |\n"
    md += f"| 🔁 可能重複 | {len(dupes)} 組 |\n"
    md += "\n"

    # Keyword contradictions
    if contradictions:
        md += "## 🟡 觀點差異\n\n"
        for c in contradictions[:20]:
            md += f"**{c['level']}** [{c['category']}] {c['v1_sentiment']} vs {c['v2_sentiment']}\n"
            md += f"- 「{c['v1']}」\n"
            md += f"- 「{c['v2']}」\n\n"

    # Semantic contradictions (new section)
    if semantic_results:
        md += "## 🤖 AI 語義矛盾偵測\n\n"
        md += "> 使用 GLM 模型進行語義分析，偵測真正的邏輯矛盾（非單純不同觀點）\n\n"
        for i, c in enumerate(semantic_results, 1):
            severity_label = {'high': '高', 'medium': '中', 'low': '低'}.get(
                c.get('severity', 'medium'), '中'
            )
            c_type = c.get('type', '語義矛盾')
            md += f"### 矛盾 {i}：{c_type} — {severity_label}\n\n"
            md += f"- **影片A**：「{c['v1']}」\n"
            if c.get('quote_a'):
                md += f"  > 原文：{c['quote_a']}\n"
            md += f"- **影片B**：「{c['v2']}」\n"
            if c.get('quote_b'):
                md += f"  > 原文：{c['quote_b']}\n"
            md += f"- **原因**：{c.get('reason', 'N/A')}\n"
            if c.get('resolution_suggestion'):
                md += f"- **建議**：{c['resolution_suggestion']}\n"
            md += "\n"

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


def parse_args():
    parser = argparse.ArgumentParser(description='Wiki Lint - 矛盾偵測與健康檢查')
    parser.add_argument(
        '--semantic',
        action='store_true',
        help='啟用 AI 語義矛盾偵測（需要 GLM API）',
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    print("🔍 Running Wiki Lint...")
    videos = load_videos()
    concepts = load_concepts()

    print(f"  Videos: {len(videos)}, Concepts: {len(concepts)}")

    contradictions = find_potential_contradictions(videos)
    orphans = check_orphan_pages(concepts, videos)
    no_content = check_content_gaps(videos)
    no_date = check_stale_dates(videos)
    dupes = find_similar_titles(videos)

    semantic_results = None
    if args.semantic:
        print("  🤖 Running AI semantic contradiction detection...")
        semantic_results = find_semantic_contradictions(videos)
        print(f"  🤖 Semantic contradictions: {len(semantic_results)}")

    generate_report(contradictions, orphans, no_content, no_date, dupes,
                    semantic_results)

    print(f"  🟡 Contradictions: {len(contradictions)}")
    print(f"  📄 Orphan pages: {len(orphans)}")
    print(f"  ❌ No content: {len(no_content)}")
    print(f"  📅 No date: {len(no_date)}")
    print(f"  🔁 Duplicates: {len(dupes)}")
