#!/usr/bin/env python3
"""Generate core_points from title using local rule-based extraction + NVIDIA API fallback"""

import json, sys, time, requests

JSON_PATH = '/root/knowledge-base/short-videos/short-videos.json'
NVIDIA_KEY = 'nvapi-SmGiNtR5HwKXlFJmEZh-3_oSl-oe7LTMz-pE-0Wc1RIoXwchGNmLb1QXn3DU7UM9pNVl3S-YnhUKSeiGfGF6y2lVIJb1t'
NVIDIA_URL = 'https://integrate.api.nvidia.com/v1/chat/completions'

def generate_nvidia(title, tags, source):
    prompt = f"""根據短影音標題生成 3 個核心重點（繁體中文）。
每點一行，數字開頭，不超過 40 字。只輸出要點。

標題：{title}
標籤：{', '.join(tags) if tags else source}"""

    try:
        resp = requests.post(NVIDIA_URL, headers={
            'Authorization': f'Bearer {NVIDIA_KEY}',
            'Content-Type': 'application/json'
        }, json={
            'model': 'meta/llama-3.1-8b-instruct',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 300,
            'temperature': 0.7
        }, timeout=30)
        
        if resp.status_code != 200:
            return None
        return resp.json()['choices'][0]['message']['content'].strip()
    except:
        return None

def local_extract(title):
    """Rule-based extraction from title when API fails"""
    # Clean title
    t = title.replace('短影音分析報告', '').replace('📊 短影音摘要報告', '').strip()
    if len(t) < 5:
        return None
    
    # Extract key phrases
    points = []
    
    # If title contains question marks or question patterns
    if '?' in t or '為什麼' in t or '如何' in t or '怎么' in t or '为什么' in t:
        # Extract the question
        for sep in ['#', '|', '_\d{8}']:
            if sep in t:
                t = t.split(sep)[0].strip()
                break
        points.append(f"探討：{t[:50]}")
    
    # Extract hashtags as topics
    hashtags = []
    for tag in ['#', '＃']:
        if tag in title:
            parts = title.split(tag)
            for p in parts[1:]:
                h = p.split()[0].strip() if p.strip() else ''
                if h and len(h) > 1 and len(h) < 15:
                    hashtags.append(h)
    
    if hashtags:
        points.append(f"主題涵蓋：{'、'.join(hashtags[:5])}")
    
    # Extract source info
    if 'douyin' in title.lower() or '抖音' in title:
        points.append("來源：抖音短影音平台")
    elif '小紅書' in title:
        points.append("來源：小紅書平台")
    
    if points:
        return '\n'.join(f"{i+1}. {p}" for i, p in enumerate(points))
    return None

if __name__ == '__main__':
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    need_content = []
    for i, v in enumerate(data['videos']):
        cp = v.get('core_points', '').strip()
        if not cp or cp == '短影音分析報告' or cp == '📊 短影音摘要報告' or len(cp) < 20:
            need_content.append(i)
    
    print(f"Need content: {len(need_content)} videos")
    
    generated = 0
    api_used = 0
    
    for idx in need_content:
        v = data['videos'][idx]
        title = v.get('title', '')
        tags = v.get('tags', [])
        source = v.get('source', '')
        
        # Try NVIDIA API first (batch of 3, then wait)
        if api_used % 3 == 0 and api_used > 0:
            time.sleep(2)
        
        result = generate_nvidia(title, tags, source)
        if result:
            v['core_points'] = result
            api_used += 1
            generated += 1
            print(f"  ✅ [{generated}] API: {title[:40]}")
        else:
            # Fallback to local extraction
            result = local_extract(title)
            if result:
                v['core_points'] = result
                generated += 1
                print(f"  ✅ [{generated}] Local: {title[:40]}")
            else:
                # Minimal fallback
                v['core_points'] = f"1. {title[:60]}"
                generated += 1
                print(f"  ⚠️ [{generated}] Minimal: {title[:40]}")
    
    # Save
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    import shutil
    shutil.copy(JSON_PATH, JSON_PATH.replace('short-videos/', ''))
    
    print(f"\n✅ Total: {generated}, API: {api_used}")
