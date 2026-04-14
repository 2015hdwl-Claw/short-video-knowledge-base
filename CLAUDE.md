# Short Video Knowledge Base

## Project
- **Repo**: 2015hdwl-Claw/short-video-knowledge-base
- **Live**: https://2015hdwl-claw.github.io/short-video-knowledge-base/
- **Admin**: admin.html (root) + short-videos/admin.html (subdir)
- **Database**: short-videos.json (101 videos), notes.json

## Architecture (4-Layer, Karpathy-inspired)
| Layer | Directory | Rule |
|-------|-----------|------|
| 1 Raw | raw/ | Read-only once ingested |
| 2 Wiki | wiki/ | LLM-maintained, never hand-edited |
| 3 Brainstorm | brainstorming/ | Exploration & health checks |
| 4 Docs | docs/ | Architecture & progress |

## Key Paths
- `short-videos.json` → main DB, referenced by admin.html via relative fetch
- `wiki/` → served via `WIKI_BASE` (GitHub raw URLs) in admin.html
- `scripts/` → Python tools, use relative paths to repo root
- `tools/douyin-downloader/` → Douyin aBogus/xBogus crypto modules

## Rules
- Never modify raw/ files after ingestion
- Wiki pages use wikilinks `[[Concept Name]]` for cross-references
- Concepts require 2+ video references to get their own page
- Scripts reference `short-videos.json` with relative paths
- admin.html at root fetches `short-videos.json` and `notes.json` directly
- admin.html in short-videos/ fetches `../notes.json`
