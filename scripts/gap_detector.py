#!/usr/bin/env python3
import argparse, json, os, sys
from collections import Counter, defaultdict

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(REPO, "short-videos", "short-videos.json")
CONCEPTS_DIR = os.path.join(REPO, "wiki", "concepts")
MIN_TAG_FREQUENCY = 3
MIN_CORE_POINTS_LENGTH = 20

from glm_limiter import rate_limited_call


def _build_gap_prompt():
    parts = [
        "分析以下影片資料庫的分類和標籤分布，找出知識缺口。",
        "",
        "目前分類分布：{category_dist}",
        "",
        "目前概念頁面：{concept_pages}",
        "",
        "熱門標籤（{min_freq}+ 影片但沒有概念頁面）：{orphan_tags}",
        "",
        "內容品質問題：{quality_issues}",
        "",
        "回傳 JSON（不要用 markdown code block 包裹）：",
        "{",
        '  "new_concepts_suggested": [{"name": "...", "description": "...", "related_tags": [...], "potential_videos": N, "priority": "high/medium/low"}],',
        '  "underrepresented_categories": [{"category": "...", "current": N, "suggested_minimum": M}],',
        '  "content_quality_issues": [{"video_title": "...", "issue": "..."}]',
        "}",
    ]
    return chr(10).join(parts)

GAP_PROMPT = _build_gap_prompt()

def _load_data():
    for path in [JSON_PATH, os.path.join(REPO, "short-videos.json")]:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
    raise FileNotFoundError("short-videos.json not found")

def _get_concept_pages():
    pages = []
    if not os.path.isdir(CONCEPTS_DIR):
        return pages
    for fn in os.listdir(CONCEPTS_DIR):
        if fn.endswith(".md"):
            pages.append(fn[:-3])
    return pages

def analyze_category_distribution(videos):
    dist = Counter()
    for v in videos:
        dist[v.get("category", "")] += 1
    return dict(dist.most_common())

def analyze_tag_frequency(videos):
    tag_freq = Counter()
    tag_to_videos = defaultdict(list)
    for i, v in enumerate(videos):
        for t in v.get("tags", []):
            tag_freq[t] += 1
            tag_to_videos[t].append(i)
    return {"frequency": dict(tag_freq.most_common()), "tag_to_videos": dict(tag_to_videos)}

def find_orphan_tags(tag_freq, concept_pages, min_freq=MIN_TAG_FREQUENCY):
    page_set = set(p.lower().replace("-", " ") for p in concept_pages)
    orphans = []
    for tag, freq in tag_freq.items():
        if freq < min_freq:
            continue
        tag_norm = tag.lower().replace("-", " ")
        if tag_norm not in page_set and tag.lower() not in page_set:
            orphans.append({"tag": tag, "count": freq})
    orphans.sort(key=lambda x: -x["count"])
    return orphans

def find_quality_issues(videos):
    issues = []
    for v in videos:
        title = v.get("title", "")
        core = v.get("core_points", "")
        if not core or len(core) < MIN_CORE_POINTS_LENGTH:
            issues.append({"video_title": title[:60], "issue": "core_points too short ({} chars)".format(len(core))})
        elif core.strip() == title.strip():
            issues.append({"video_title": title[:60], "issue": "core_points == title (not extracted)"})
    return issues

def _extract_text(resp):
    if resp and resp.choices:
        return resp.choices[0].message.content or ""
    return ""

def detect_gaps():
    data = _load_data()
    videos = data.get("videos", [])
    concept_pages = _get_concept_pages()
    cat_dist = analyze_category_distribution(videos)
    tag_data = analyze_tag_frequency(videos)
    orphan_tags = find_orphan_tags(tag_data["frequency"], concept_pages)
    quality_issues = find_quality_issues(videos)
    cat_dist_str = json.dumps(cat_dist, ensure_ascii=False)
    pages_str = ", ".join(concept_pages) if concept_pages else "(none)"
    orphan_str = json.dumps(orphan_tags[:15], ensure_ascii=False)
    quality_str = json.dumps(quality_issues[:10], ensure_ascii=False)
    prompt = GAP_PROMPT.format(
        category_dist=cat_dist_str, concept_pages=pages_str,
        min_freq=MIN_TAG_FREQUENCY, orphan_tags=orphan_str,
        quality_issues=quality_str)
    system_msg = ("你是知識管理分析師。"
                  "分析資料庫分布，找出知識缺口。"
                  "回傳純 JSON，不要用 markdown code block 包裹。")
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": prompt}]
    suggestions = {}
    try:
        resp = rate_limited_call(messages, max_tokens=800, temperature=0.3, response_format={"type": "json_object"})
        text = _extract_text(resp)
        suggestions = json.loads(text)
    except Exception as e:
        suggestions = {"error": str(e), "raw_hint": "LLM analysis failed, stats only"}
    return {
        "category_distribution": cat_dist, "concept_pages": concept_pages,
        "orphan_tags": orphan_tags, "quality_issues": quality_issues,
        "suggestions": suggestions, "total_videos": len(videos),
        "total_tags": len(tag_data["frequency"])}

def main():
    parser = argparse.ArgumentParser(description="Knowledge Gap Detector")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    result = detect_gaps()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=== Gap Detection Report ===")
        print("Total videos: {}".format(result["total_videos"]))
        print("Total tags: {}".format(result["total_tags"]))
        print("Concept pages: {}".format(len(result["concept_pages"])))
        print(chr(10) + "--- Category Distribution ---")
        for cat, count in result["category_distribution"].items():
            print("  {}: {}".format(cat, count))
        print(chr(10) + "--- Orphan Tags ({}+ videos, no concept page) ---".format(MIN_TAG_FREQUENCY))
        for o in result["orphan_tags"][:10]:
            print("  {}: {} videos".format(o["tag"], o["count"]))
        print(chr(10) + "--- Quality Issues ({} total) ---".format(len(result["quality_issues"])))
        for q in result["quality_issues"][:5]:
            print("  [{}] {}".format(q["issue"], q["video_title"][:50]))
        sugg = result.get("suggestions", {})
        if "error" not in sugg:
            print(chr(10) + "--- LLM Suggestions ---")
            for nc in sugg.get("new_concepts_suggested", [])[:5]:
                print("  [{}] {} - {}".format(nc.get("priority", "?"), nc.get("name", ""), nc.get("description", "")[:50]))
            for ur in sugg.get("underrepresented_categories", [])[:3]:
                print("  Underrepresented: {} (now {}, suggested {})".format(ur.get("category", ""), ur.get("current", 0), ur.get("suggested_minimum", 0)))
        else:
            print(chr(10) + "--- LLM Failed ---")
            print("  {}".format(sugg.get("error", "unknown")))

if __name__ == "__main__":
    main()
