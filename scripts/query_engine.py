#!/usr/bin/env python3
"""Knowledge query engine: BM25 retrieval + LLM synthesis.

Usage:
    python scripts/query_engine.py "AI 時代如何創業"
    python scripts/query_engine.py "減脂方法" --limit 5
    python scripts/query_engine.py "投資策略" --json
"""

import argparse
import json
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from search import search_videos, search_wiki
from glm_limiter import rate_limited_call

SYSTEM_PROMPT = (
    "你是短影音知識庫的問答引擎。根據提供的影片摘要和 wiki 頁面內容回答問題。\n"
    "規則：\n"
    "1. 回答必須基於提供的資料，不要編造\n"
    "2. 每個觀點都要引用來源（影片標題 + 日期）\n"
    "3. 如果資料不足，明確說明「目前知識庫中沒有相關資訊」\n"
    "4. 使用繁體中文\n"
    "5. 結構化輸出：先給結論，再展開細節\n"
)

USER_PROMPT_TEMPLATE = (
    "問題：{query}\n\n"
    "相關影片（按相關度排序）：\n{video_results}\n\n"
    "相關 wiki 頁面：\n{wiki_results}\n\n"
    "請回答。格式：\n"
    "## 回答\n"
    "[200-500 字]\n\n"
    "## 關鍵觀點\n"
    "- [觀點] — 來源：(影片標題, 日期)\n\n"
    "## 知識缺口\n"
    "[如果有的話]"
)


def _format_video_results(results: list[dict]) -> str:
    """Format video search results into readable text."""
    if not results:
        return "（無相關影片）"
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "未知")
        date = r.get("date", "未知")
        category = r.get("category", "未分類")
        score = r.get("score", 0)
        source = r.get("source", "")
        lines.append(
            f"{i}. 【{title}】\n"
            f"   日期：{date} | 分類：{category} | 來源：{source} | 相關度：{score}"
        )
    return "\n".join(lines)


def _format_wiki_results(results: list[dict]) -> str:
    """Format wiki search results into readable text."""
    if not results:
        return "（無相關 wiki 頁面）"
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "未知")
        subtype = r.get("subtype", "")
        score = r.get("score", 0)
        path = r.get("path", "")
        # Read first 300 chars of wiki content for context
        content_preview = ""
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content_preview = f.read(300)
            except (IOError, OSError):
                pass
        lines.append(
            f"{i}. 【{title}】({subtype}) | 相關度：{score}\n"
            f"   {content_preview[:200]}"
        )
    return "\n".join(lines)


def _extract_text(resp) -> str:
    """Extract text from LLM response.
    Falls back to reasoning_content if content is empty (GLM reasoning mode).
    """
    if not resp or not resp.choices:
        return ""
    msg = resp.choices[0].message
    text = msg.content or ""
    if not text.strip():
        rc = getattr(msg, "reasoning_content", None)
        if rc:
            text = rc
    return text


def query_knowledge_base(question: str, limit: int = 10) -> dict:
    """Query the knowledge base: BM25 search + LLM synthesis.

    Steps:
        1. BM25 search videos (top N)
        2. BM25 search wiki (top 5)
        3. Format results
        4. LLM synthesis with citations
        5. Return structured result

    Returns:
        dict with keys: answer, sources, video_count, wiki_count
    """
    video_limit = min(limit, 20)
    wiki_limit = min(max(limit // 2, 3), 10)

    video_results = search_videos(question, limit=video_limit)
    wiki_results = search_wiki(question, limit=wiki_limit)

    video_text = _format_video_results(video_results)
    wiki_text = _format_wiki_results(wiki_results)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        query=question,
        video_results=video_text,
        wiki_results=wiki_text,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        resp = rate_limited_call(messages, max_tokens=2000, temperature=0.5)
        answer = _extract_text(resp)
    except Exception as e:
        answer = (
            f"LLM 調用失敗: {e}\n\n"
            "以下為 BM25 檢索結果：\n"
            f"{video_text}\n\n{wiki_text}"
        )

    sources = []
    for r in video_results:
        sources.append({
            "type": "video",
            "title": r.get("title", ""),
            "date": r.get("date", ""),
            "category": r.get("category", ""),
            "score": r.get("score", 0),
        })
    for r in wiki_results:
        sources.append({
            "type": "wiki",
            "title": r.get("title", ""),
            "subtype": r.get("subtype", ""),
            "score": r.get("score", 0),
        })

    return {
        "answer": answer,
        "sources": sources,
        "video_count": len(video_results),
        "wiki_count": len(wiki_results),
    }


def main():
    parser = argparse.ArgumentParser(description="Knowledge Query Engine")
    parser.add_argument("question", help="Question to ask")
    parser.add_argument("--limit", type=int, default=10, help="Max results")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    result = query_knowledge_base(args.question, limit=args.limit)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["answer"])
        print(f"\n--- {result['video_count']} videos, {result['wiki_count']} wiki pages referenced ---")


if __name__ == "__main__":
    main()
