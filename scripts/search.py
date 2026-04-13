#!/usr/bin/env python3
"""BM25 Search for short-video knowledge base

用法：
  python3 search.py "關鍵字"
  python3 search.py "關鍵字" --limit 10
  python3 search.py "關鍵字" --type wiki  (搜概念頁面)
"""

import os, sys, re, math, json, glob
from collections import Counter, defaultdict

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
JSON_PATH = os.path.join(REPO, 'short-videos', 'short-videos.json')
CONCEPTS_DIR = os.path.join(REPO, 'wiki', 'concepts')
INSIGHTS_DIR = os.path.join(REPO, 'wiki', 'insights')

def tokenize(text):
    """Simple tokenizer: split on non-alphanumeric, keep CJK chars"""
    # Split CJK characters individually and keep words
    tokens = []
    for m in re.finditer(r'[\u4e00-\u9fff]|[a-zA-Z0-9]+', text.lower()):
        tokens.append(m.group())
    return tokens

def build_bm25_index(documents):
    """Build BM25 index from list of (id, text) tuples"""
    k1 = 1.5
    b = 0.75
    
    doc_tokens = {}
    df = Counter()  # document frequency
    doc_lengths = {}
    
    for doc_id, text in documents:
        tokens = tokenize(text)
        doc_tokens[doc_id] = tokens
        doc_lengths[doc_id] = len(tokens)
        unique = set(tokens)
        for t in unique:
            df[t] += 1
    
    N = len(documents)
    avg_dl = sum(doc_lengths.values()) / N if N > 0 else 1
    
    # Precompute IDF
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
        'N': N
    }

def bm25_search(index, query, limit=10):
    """Search using BM25"""
    query_tokens = tokenize(query)
    scores = defaultdict(float)
    
    for token in query_tokens:
        if token not in index['idf']:
            continue
        idf = index['idf'][token]
        
        for doc_id, tokens in index['doc_tokens'].items():
            tf = tokens.count(token)
            if tf == 0:
                continue
            dl = index['doc_lengths'][doc_id]
            k1 = index['k1']
            b = index['b']
            avg_dl = index['avg_dl']
            
            score = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
            scores[doc_id] += score
    
    return sorted(scores.items(), key=lambda x: -x[1])[:limit]

def search_videos(query, limit=10):
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    docs = []
    for i, v in enumerate(data['videos']):
        text = f"{v.get('title','')} {v.get('core_points','')} {v.get('source','')} {' '.join(v.get('tags',[]))}"
        docs.append((i, text))
    
    index = build_bm25_index(docs)
    results = bm25_search(index, query, limit)
    
    output = []
    for doc_id, score in results:
        v = data['videos'][doc_id]
        output.append({
            'title': v.get('title', ''),
            'score': round(score, 2),
            'category': v.get('category', ''),
            'date': v.get('date', ''),
            'source': v.get('source', ''),
            'has_content': bool(v.get('core_points') and len(v.get('core_points','')) > 20)
        })
    return output

def search_wiki(query, limit=10):
    docs = []
    for f in glob.glob(os.path.join(CONCEPTS_DIR, '*.md')):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, 'r', encoding='utf-8') as fh:
            text = fh.read()
        docs.append((f'concept:{name}', text))
    
    for f in glob.glob(os.path.join(INSIGHTS_DIR, '*.md')):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, 'r', encoding='utf-8') as fh:
            text = fh.read()
        docs.append((f'insight:{name}', text))
    
    index = build_bm25_index(docs)
    results = bm25_search(index, query, limit)
    
    output = []
    for doc_id, score in results:
        kind, name = doc_id.split(':', 1)
        output.append({
            'type': kind,
            'name': name,
            'score': round(score, 2)
        })
    return output

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 search.py \"query\" [--limit N] [--type videos|wiki|all]")
        sys.exit(1)
    
    query = args[0]
    limit = 10
    search_type = 'all'
    
    i = 1
    while i < len(args):
        if args[i] == '--limit' and i+1 < len(args):
            limit = int(args[i+1])
            i += 2
        elif args[i] == '--type' and i+1 < len(args):
            search_type = args[i+1]
            i += 2
        else:
            i += 1
    
    if search_type in ('all', 'videos'):
        print(f"\n📹 影片搜尋: \"{query}\"\n")
        results = search_videos(query, limit)
        if not results:
            print("  沒有找到結果")
        for r in results:
            content_icon = '📝' if r['has_content'] else '📄'
            print(f"  {content_icon} [{r['score']}] {r['title'][:60]}")
            print(f"     {r['source']} | {r['category']} | {r['date']}")
    
    if search_type in ('all', 'wiki'):
        print(f"\n🧠 Wiki 搜尋: \"{query}\"\n")
        results = search_wiki(query, limit)
        if not results:
            print("  沒有找到結果")
        for r in results:
            icon = '📚' if r['type'] == 'concept' else '💡'
            print(f"  {icon} [{r['score']}] {r['name']}")
