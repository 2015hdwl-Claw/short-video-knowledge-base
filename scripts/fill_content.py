#!/usr/bin/env python3
"""Batch generate core_points for videos without content using GLM API"""

import json, sys, time, requests

JSON_PATH = '/root/knowledge-base/short-videos/short-videos.json'
API_KEY = '46f8a41bea604903bf743a291d4a236d.FZddI5O8diUSh1hQ'
API_URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'

def generate_summary(title, tags, source, url):
    """Generate core_points from title/tags using GLM"""
    prompt = f"""根據以下短影音資訊，生成 3-5 個核心重點（繁體中文）。
每個重點一行，以數字開頭。簡潔有力，每點不超過 40 字。

標題：{title}
標籤：{', '.join(tags) if tags else '無'}
來源：{source}
連結：{url}

直接輸出 3-5 個要點，不要其他說明："""

    try:
        resp = requests.post(API_URL, headers={
            'Authorization': f'Bearer {API_KEY}',
            'Content-Type': 'application/json'
        }, json={
            'model': 'glm-4.7-flash',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 300,
            'temperature': 0.7
        }, timeout=30)
        
        if resp.status_code != 200:
            print(f"  API error {resp.status_code}")
            return None
        
        content = resp.json()['choices'][0]['message']['content'].strip()
        return content
    except Exception as e:
        print(f"  Error: {e}")
        return None

if __name__ == '__main__':
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Find videos without content
    need_content = []
    for i, v in enumerate(data['videos']):
        cp = v.get('core_points', '').strip()
        if not cp or cp == '短影音分析報告' or len(cp) < 20:
            need_content.append(i)
    
    print(f"Need content: {len(need_content)} videos")
    
    # Process in batches of 5
    batch_size = 5
    generated = 0
    failed = 0
    
    for i in range(0, len(need_content), batch_size):
        batch = need_content[i:i+batch_size]
        for idx in batch:
            v = data['videos'][idx]
            title = v.get('title', '')
            tags = v.get('tags', [])
            source = v.get('source', '')
            url = v.get('url', '')
            
            print(f"  [{generated+1}/{len(need_content)}] {title[:40]}...", end=' ')
            
            result = generate_summary(title, tags, source, url)
            if result:
                v['core_points'] = result
                generated += 1
                print("✅")
            else:
                failed += 1
                print("❌")
        
        # Save progress after each batch
        with open(JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        import shutil
        shutil.copy(JSON_PATH, JSON_PATH.replace('short-videos/', ''))
        
        if i + batch_size < len(need_content):
            time.sleep(1)  # Rate limit
    
    print(f"\n✅ Generated: {generated}, Failed: {failed}")
    
    # Also fix tags for videos with empty tags
    tag_fixed = 0
    for v in data['videos']:
        if not v.get('tags') or v['tags'] == ['']:
            cat = v.get('category', '')
            tag_map = {
                'AI': ['AI', '科技'],
                '財經': ['財經'],
                '健康': ['健康'],
                '科技': ['科技'],
                '心理學': ['心理學'],
                '教育': ['教育'],
                '個人成長': ['個人成長'],
                '財富思維': ['財富思維'],
            }
            v['tags'] = tag_map.get(cat, ['AI'])
            tag_fixed += 1
    
    print(f"Tags fixed: {tag_fixed}")
    
    # Final save
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    shutil.copy(JSON_PATH, JSON_PATH.replace('short-videos/', ''))
    print("✅ All saved")
