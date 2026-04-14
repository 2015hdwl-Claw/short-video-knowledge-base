# Short Video Knowledge Base

> [Karpathy LLM Wiki](https://github.com/gatelynch/llm-knowledge-base) + Short Video

GitHub Pages: [2015hdwl-claw.github.io/short-video-knowledge-base](https://2015hdwl-claw.github.io/short-video-knowledge-base/)

## Architecture

```
short-video-knowledge-base/
├── admin.html              # Admin interface (GitHub Pages)
├── index.html              # Public homepage
├── short-videos.json       # Main database (101 videos)
├── notes.json              # Quick notes
│
├── docs/                   # Documentation
│   ├── WIKI_SCHEMA.md      # Wiki architecture spec
│   └── PROGRESS.md         # Project progress
│
├── raw/                    # Layer 1: Raw materials (read-only)
│   ├── videos/             # 169 video reports (MD)
│   ├── articles/           # Curated articles
│   └── notes/              # Raw notes
│
├── wiki/                   # Layer 2: LLM-compiled knowledge
│   ├── concepts/           # 8 concept pages
│   ├── entities/           # 8 entity pages
│   ├── comparisons/        # Comparison pages
│   ├── syntheses/          # Synthesis pages
│   ├── insights/           # Insight records
│   ├── indexes/            # Master indexes
│   └── index.md            # Wiki index
│
├── brainstorming/          # Layer 3: Thinking & exploration
│   ├── chat/               # Q&A logs
│   └── health/             # Health check reports
│
├── scripts/                # Python tooling
│   ├── search.py           # BM25 full-text search
│   ├── lint_wiki.py        # Wiki contradiction detection
│   ├── insight.py          # Insight extraction
│   ├── rebuild_concepts.py # Concept page builder
│   └── ...
│
└── tools/
    └── douyin-downloader/  # Douyin API crypto modules
        └── fetch_metadata.py
