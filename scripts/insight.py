#!/usr/bin/env python3
"""Save an insight/lesson to wiki/insights/ or auto-detect from video summaries."""

import sys, os, json, time, datetime, argparse, re, glob

REPO = os.path.dirname(os.path.abspath(__file__))
INSIGHTS_DIR = os.path.join(REPO, '..', 'wiki', 'insights')
JSON_PATH = os.path.join(REPO, '..', 'short-videos', 'short-videos.json')
os.makedirs(INSIGHTS_DIR, exist_ok=True)

API_KEY = os.getenv('CLASSIFIER_API_KEY', '')
BASE_URL = os.getenv('CLASSIFIER_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4/')
MODEL = os.getenv('CLASSIFIER_MODEL', 'glm-4.7-flash')
MAX_BATCHES = 10
BATCH_SIZE = 5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glm_limiter import rate_limited_call as _rate_limited_call

def save(title, content, concepts=None, tags=None):
    """Save a single insight as a markdown file in wiki/insights/."""
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

def _get_existing_titles():
    """Read all files in wiki/insights/ and return set of title strings already saved."""
    titles = set()
    if not os.path.isdir(INSIGHTS_DIR):
        return titles
    for filepath in glob.glob(os.path.join(INSIGHTS_DIR, '*.md')):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            for line in content.splitlines():
                line = line.strip().lstrip('# >-').strip()
                if line and len(line) > 4:
                    titles.add(line)
        except OSError:
            continue
    return titles

def _extract_topic(title):
    """Strip 小紅書_ prefix and _YYYYMMDD_HHMMSS_XX date suffix from title."""
    cleaned = re.sub(r'^小紅書_', '', title)
    cleaned = re.sub(r'_\d{8}_\d{6}_\d+$', '', cleaned)
    return cleaned.strip('_')

def _is_already_covered(video_title, existing_titles):
    """Check if a video title is already covered by existing insights."""
    def normalize(s):
        return re.sub(r'[^\w\u4e00-\u9fff]', '', s.lower())

    norm_video = normalize(video_title)
    if not norm_video:
        return False
    for existing in existing_titles:
        if normalize(existing) == norm_video:
            return True
        if norm_video in normalize(existing) or normalize(existing) in norm_video:
            return True
    return False

def _format_video_batch(videos, start_index):
    """Format a batch of videos for the LLM prompt."""
    parts = []
    for i, v in enumerate(videos):
        text = (
            f"[{start_index + i}] 標題：{v['title']}\n"
            f"分類：{v.get('category', 'N/A')}\n"
            f"摘要：{v.get('core_points', 'N/A')}\n"
        )
        if v.get('advice'):
            text += f"建議：{v['advice']}\n"
        parts.append(text)
    return "\n---\n".join(parts)

DETECT_PROMPT = """以下是 {count} 段短影音摘要。判斷哪些包含值得長期記住的洞見。
洞見標準：
1. 顛覆常規認知（多數人不知道的觀點）
2. 提供可操作的獨特方法論（不是泛泛而談）
3. 包含具體數據或案例（不是空泛口號）
4. 跨領域的類比或遷移
排除：常見勵志語錄、產品廣告、空泛觀點、已覆蓋內容

回傳 JSON：
{{"insights": [{{"index": 0, "has_insight": true, "title": "15字以內", "content": "80-150字", "concepts": ["相關概念"], "tags": ["標籤"], "originality": "high/medium/low", "actionability": "high/medium/low"}}]}}
對沒有洞見的影片，has_insight 設為 false，其他欄位留空。

影片資料：
{formatted_videos}"""

def _call_llm(prompt):
    messages = [{"role": "user", "content": prompt}]
    resp = _rate_limited_call(
        messages,
        max_tokens=2048,
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    text = _extract_llm_content(resp)
    return json.loads(text)

def auto_detect(videos, dry_run=False, full=False):
    """Analyze videos and detect which contain novel insights worth saving.

    Args:
        videos: List of video dicts from short-videos.json.
        dry_run: If True, print results without saving.
        full: If True, process all videos (no batch limit).

    Returns:
        List of insight dicts that were found (or would be saved).
    """
    existing_titles = _get_existing_titles()
    uncovered = [v for v in videos if not _is_already_covered(v['title'], existing_titles)]
    print(f"📊 Total videos: {len(videos)}")
    print(f"📝 Already covered: {len(videos) - len(uncovered)}")
    print(f"🔍 To analyze: {len(uncovered)}")

    if not uncovered:
        print("Nothing to analyze — all videos already have insights.")
        return []

    if full:
        candidates = uncovered
        effective_batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE
    else:
        candidates = uncovered[:MAX_BATCHES * BATCH_SIZE]
        effective_batches = min(MAX_BATCHES, (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE)
    print(f"🎯 Processing {len(candidates)} videos "
          f"({min(len(candidates), BATCH_SIZE)} per batch, "
          f"{effective_batches} batches)\n")

    all_insights = []
    batch_count = 0

    for start in range(0, len(candidates), BATCH_SIZE):
        if not full and batch_count >= MAX_BATCHES:
            break
        batch = candidates[start: start + BATCH_SIZE]
        batch_count += 1

        formatted = _format_video_batch(batch, start)
        prompt = DETECT_PROMPT.format(count=len(batch), formatted_videos=formatted)

        print(f"--- Batch {batch_count} (videos {start}-{start + len(batch) - 1}) ---")
        try:
            result = _call_llm(prompt)
            insights = result.get("insights", [])
        except RuntimeError as e:
            print(f"❌ API error: {e}")
            continue
        except (json.JSONDecodeError, KeyError) as e:
            print(f"❌ Parse error: {e}")
            continue

        for item in insights:
            idx = item.get("index", -1)
            if not item.get("has_insight"):
                continue
            if idx < 0 or idx >= len(candidates):
                print(f"  ⚠️  Invalid index {idx}, skipping")
                continue

            video = candidates[idx]
            insight = {
                "video_title": video["title"],
                "title": item.get("title", video["title"]),
                "content": item.get("content", ""),
                "concepts": item.get("concepts", []),
                "tags": item.get("tags", video.get("tags", [])),
            }
            all_insights.append(insight)
            print(f"  💡 [{video['title']}] {insight['title']}")

        if batch_count < MAX_BATCHES and start + BATCH_SIZE < len(candidates):
            time.sleep(1)

    if not all_insights:
        print("\nNo new insights found.")
        return []

    print(f"\n📋 Found {len(all_insights)} insight(s)")
    if dry_run:
        print("🔍 DRY RUN — nothing saved:")
        for i, ins in enumerate(all_insights, 1):
            print(f"  {i}. {ins['title']}")
            print(f"     {ins['content'][:80]}...")
            print(f"     Tags: {', '.join(ins['tags'])}")
        return all_insights

    saved_paths = []
    for ins in all_insights:
        path = save(ins["title"], ins["content"], ins["concepts"], ins["tags"])
        saved_paths.append(path)

    print(f"\n🎉 Done — saved {len(saved_paths)} insight(s)")
    return all_insights

def main():
    parser = argparse.ArgumentParser(description="Save or auto-detect insights")
    parser.add_argument("title", nargs="?", help="Insight title (manual mode)")
    parser.add_argument("content", nargs="?", help="Insight content (manual mode)")
    parser.add_argument("concepts", nargs="?", help="Comma-separated concepts (manual mode)")
    parser.add_argument("--auto", action="store_true", help="Auto-detect insights from videos")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--full", action="store_true", help="Process all videos (no batch limit)")
    args = parser.parse_args()

    if args.auto:
        if not os.path.isfile(JSON_PATH):
            print(f"Error: {JSON_PATH} not found")
            sys.exit(1)
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        auto_detect(data["videos"], dry_run=args.dry_run, full=args.full)
    elif args.title and args.content:
        concepts = args.concepts.split(',') if args.concepts else []
        save(args.title, args.content, concepts)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
