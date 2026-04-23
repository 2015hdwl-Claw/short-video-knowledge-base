#!/usr/bin/env python3
"""BM25 Search for short-video knowledge base (v2)

用法：
  python3 search.py "關鍵字"
  python3 search.py "關鍵字" --limit 10
  python3 search.py "關鍵字" --type videos|wiki|all
  python3 search.py "關鍵字" --all           (統一排名)
  python3 search.py "關鍵字" --json          (JSON 輸出)
  python3 search.py "關鍵字" --recent 30     (近 N 天)
"""

import os
import sys
import re
import math
import json
import glob
from collections import Counter, defaultdict
from datetime import datetime, timedelta

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
JSON_PATH = os.path.join(REPO, 'short-videos', 'short-videos.json')
CONCEPTS_DIR = os.path.join(REPO, 'wiki', 'concepts')
INSIGHTS_DIR = os.path.join(REPO, 'wiki', 'insights')

CATEGORY_BOOST = 1.25
TAG_EXACT_BOOST = 1.20
BIGRAM_WEIGHT = 0.6
FUZZY_THRESHOLD = 3


def tokenize(text):
    """Tokenizer: unigrams + bigrams for CJK, words for Latin."""
    tokens = []
    cjk_spans = []
    for m in re.finditer(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text.lower()):
        span = m.group()
        if re.match(r'[\u4e00-\u9fff]+$', span):
            cjk_spans.append(span)
        else:
            tokens.append(span)

    for span in cjk_spans:
        for ch in span:
            tokens.append(ch)
        for i in range(len(span) - 1):
            tokens.append(span[i:i + 2])
    return tokens


def bigram_tokens_only(text):
    """Return only the bigram tokens from text."""
    tokens = []
    for m in re.finditer(r'[\u4e00-\u9fff]+', text.lower()):
        span = m.group()
        for i in range(len(span) - 1):
            tokens.append(span[i:i + 2])
    return tokens


def build_bm25_index(documents):
    """Build BM25 index from list of (id, text) tuples."""
    k1, b = 1.5, 0.75
    doc_tokens = {}
    df = Counter()
    doc_lengths = {}
    bigram_tokens = {}

    for doc_id, text in documents:
        tokens = tokenize(text)
        doc_tokens[doc_id] = tokens
        doc_lengths[doc_id] = len(tokens)
        bigram_tokens[doc_id] = bigram_tokens_only(text)
        for t in set(tokens):
            df[t] += 1

    N = len(documents)
    avg_dl = sum(doc_lengths.values()) / N if N > 0 else 1

    idf = {}
    for term, freq in df.items():
        idf[term] = math.log((N - freq + 0.5) / (freq + 0.5) + 1)

    return {
        'doc_tokens': doc_tokens,
        'df': df,
        'doc_lengths': doc_lengths,
        'avg_dl': avg_dl,
        'idf': idf,
        'k1': k1,
        'b': b,
        'N': N,
        'bigram_tokens': bigram_tokens,
    }


def bm25_score(index, query_tokens, doc_id):
    """Compute BM25 score for a single document."""
    k1 = index['k1']
    b = index['b']
    avg_dl = index['avg_dl']
    dl = index['doc_lengths'][doc_id]
    tokens = index['doc_tokens'][doc_id]
    total = 0.0

    for token in query_tokens:
        if token not in index['idf']:
            continue
        idf_val = index['idf'][token]
        tf = tokens.count(token)
        if tf == 0:
            continue
        total += idf_val * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
    return total


def bm25_search(index, query, limit=10):
    """Search using BM25 with bigram support."""
    query_tokens = tokenize(query)
    scores = defaultdict(float)
    bigram_queries = bigram_tokens_only(query)

    for doc_id in index['doc_tokens']:
        score = bm25_score(index, query_tokens, doc_id)
        if score == 0 and bigram_queries:
            doc_bigrams = index['bigram_tokens'][doc_id]
            for bg in bigram_queries:
                if bg in doc_bigrams:
                    score += BIGRAM_WEIGHT * index['idf'].get(bg, 0.5)
        if score > 0:
            scores[doc_id] = score

    return sorted(scores.items(), key=lambda x: -x[1])[:limit]


def generate_fuzzy_variants(query):
    """Generate 1-edit-distance variants for CJK fallback."""
    variants = set()
    if len(query) <= 2:
        return variants

    chars = list(query)
    for i in range(len(chars)):
        removed = chars[:i] + chars[i + 1:]
        if removed:
            variants.add(''.join(removed))

    common_chars = '的是在了不人有我他這那她與和及對中'
    for i in range(len(chars) + 1):
        for c in common_chars:
            inserted = chars[:i] + [c] + chars[i:]
            variants.add(''.join(inserted))
    return variants


def load_videos_data():
    """Load and return video data with index."""
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def search_videos(query, limit=10, recent_days=None):
    """Search videos with BM25 + category/tag boosting."""
    data = load_videos_data()
    docs = []
    categories = defaultdict(list)

    for i, v in enumerate(data['videos']):
        date_str = v.get('date', '')
        if recent_days and date_str:
            try:
                doc_date = datetime.strptime(date_str, '%Y-%m-%d')
                cutoff = datetime.now() - timedelta(days=recent_days)
                if doc_date < cutoff:
                    continue
            except ValueError:
                pass

        cat = v.get('category', '')
        text_parts = [
            v.get('title', ''),
            v.get('core_points', ''),
            v.get('source', ''),
            ' '.join(v.get('tags', [])),
            cat,
        ]
        docs.append((i, ' '.join(text_parts)))
        if cat:
            categories[cat].append(i)

    index = build_bm25_index(docs)
    results = bm25_search(index, query, limit)

    # Fallback to fuzzy if few results
    if len(results) < FUZZY_THRESHOLD:
        fuzzy_results = defaultdict(float)
        for variant in generate_fuzzy_variants(query):
            for doc_id, score in bm25_search(index, variant, limit):
                fuzzy_results[doc_id] = max(fuzzy_results[doc_id], score * 0.7)
        existing_ids = {did for did, _ in results}
        for doc_id, score in fuzzy_results.items():
            if doc_id not in existing_ids:
                results.append((doc_id, score))
        results.sort(key=lambda x: -x[1])
        results = results[:limit]

    # Build tag lookup
    tag_to_docs = defaultdict(list)
    for i, v in enumerate(data['videos']):
        for t in v.get('tags', []):
            tag_to_docs[t].append(i)

    query_lower = query.lower()
    output = []
    for doc_id, score in results:
        v = data['videos'][doc_id]
        cat = v.get('category', '')

        # Category boost
        if cat and cat.lower() in query_lower:
            score *= CATEGORY_BOOST

        # Tag exact boost
        for t in v.get('tags', []):
            if t.lower() == query_lower:
                score *= TAG_EXACT_BOOST
                break

        output.append({
            'type': 'video',
            'title': v.get('title', ''),
            'score': round(score, 2),
            'category': cat,
            'date': v.get('date', ''),
            'source': v.get('source', ''),
            'has_content': bool(
                v.get('core_points') and len(v.get('core_points', '')) > 20
            ),
        })
    return output


def search_wiki(query, limit=10):
    """Search wiki concepts and insights pages with BM25."""
    docs = []
    file_map = {}

    for f in glob.glob(os.path.join(CONCEPTS_DIR, '*.md')):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, 'r', encoding='utf-8') as fh:
            text = fh.read()
        docs.append((name, text))
        file_map[name] = ('concept', f)

    for f in glob.glob(os.path.join(INSIGHTS_DIR, '*.md')):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, 'r', encoding='utf-8') as fh:
            text = fh.read()
        docs.append((name, text))
        file_map[name] = ('insight', f)

    # Also search other wiki subdirectories
    for subdir in ['comparisons', 'entities', 'syntheses', 'indexes']:
        dir_path = os.path.join(REPO, 'wiki', subdir)
        if not os.path.isdir(dir_path):
            continue
        for f in glob.glob(os.path.join(dir_path, '*.md')):
            name = os.path.splitext(os.path.basename(f))[0]
            with open(f, 'r', encoding='utf-8') as fh:
                text = fh.read()
            docs.append((name, text))
            file_map[name] = (subdir, f)

    if not docs:
        return []

    index = build_bm25_index(docs)
    results = bm25_search(index, query, limit)

    output = []
    for doc_id, score in results:
        page_type, path = file_map[doc_id]
        output.append({
            'type': 'wiki',
            'subtype': page_type,
            'title': doc_id,
            'score': round(score, 2),
            'path': path,
        })
    return output


def search_all(query, limit=10):
    """Search both videos and wiki, merge and rank by score."""
    video_results = search_videos(query, limit=limit)
    wiki_results = search_wiki(query, limit=limit)

    merged = []
    for r in video_results:
        merged.append({**r, 'rank_score': r['score']})
    for r in wiki_results:
        merged.append({**r, 'rank_score': r['score']})

    merged.sort(key=lambda x: -x['rank_score'])
    return merged[:limit]


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='BM25 Search')
    parser.add_argument('query', help='Search query')
    parser.add_argument('--limit', type=int, default=10, help='Max results')
    parser.add_argument('--type', choices=['videos', 'wiki', 'all'], default='all',
                        help='Search type')
    parser.add_argument('--recent', type=int, default=None,
                        help='Only videos from last N days')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()

    if args.type == 'videos':
        results = search_videos(args.query, limit=args.limit,
                                recent_days=args.recent)
    elif args.type == 'wiki':
        results = search_wiki(args.query, limit=args.limit)
    else:
        results = search_all(args.query, limit=args.limit)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            score = r['score']
            title = r['title']
            rtype = r.get('type', '?')
            extra = ''
            if rtype == 'video':
                extra = f" [{r.get('category', '')}] {r.get('date', '')}"
            elif rtype == 'wiki':
                extra = f" ({r.get('subtype', '')})"
            print(f"  {score:6.2f}  {title}{extra}")
