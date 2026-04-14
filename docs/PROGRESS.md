# 短影音知識庫 — 工作進度

> 最後更新：2026-04-14 00:57 (GMT+8)

---

## 📊 專案概況

| 指標 | 數值 |
|------|:----:|
| 總影片數 | 106 筆 |
| 有內容摘要 | 102 筆 (96%) |
| 概念頁面 | 8 個 |
| 洞見記錄 | 3 篇 |
| 知識卡片 | 106 張 |
| 管理介面 | admin.html |

### 分類分布

| 分類 | 數量 |
|------|:----:|
| AI | 56 |
| 教育 | 16 |
| 個人成長 | 14 |
| 財經 | 11 |
| 健康 | 6 |
| 心理學 | 3 |

---

## 🎯 已完成功能

### 核心系統
- [x] **自動化短影音處理流程**：YouTube/TikTok/B站全自動下載→轉錄→生成報告→推送 GitHub
- [x] **抖音分享文字摘要**：無需 cookies，直接從分享文字生成知識卡
- [x] **Admin 管理介面**：搜尋、篩選、排序、編輯、刪除（透過 GitHub API）
- [x] **隨身筆記系統**：跨平台筆記記錄
- [x] **多主題切換**：暗色、海洋、森林、日落、紫色、玫瑰、淺色

### 知識 Wiki
- [x] **8 個概念頁面**：AI工具與編程、AI趨勢與產業、財經投資理財、心理學與認知、健康養生、創業與商業模式、學習與知識管理、科學歷史與人文
- [x] **概念索引**：卡片式展示所有概念
- [x] **知識圖譜**：D3.js 力導向圖
- [x] **列表模式**：快速瀏覽所有概念
- [x] **交叉引用**：概念之間互相連結
- [x] **洞察記錄**：對話中產生的洞見自動沉澱

### 工具腳本
- [x] **BM25 搜尋引擎** (`scripts/search.py`)：影片 + Wiki 全文搜尋
- [x] **矛盾偵測 Lint** (`scripts/lint_wiki.py`)：自動掃描觀點差異、內容缺失、重複
- [x] **問答累積** (`scripts/insight.py`)：自動保存有價值的洞見
- [x] **內容填充** (`scripts/fill_content.py`)：為缺內容的影片生成摘要

### Bug 修復
- [x] **中文亂碼**：`atob()` → `ghDecode()` (TextDecoder) 正確處理 UTF-8 base64
- [x] **筆記刪除**：改為從 notes.json 刪除後 push
- [x] **知識圖譜列表模式**：整合到 Wiki tab
- [x] **Wiki HTML 顯示**：修復 markdown 渲染
- [x] **Script 標籤語法**：修復外部 script 內嵌 inline JS

### 資料清理
- [x] **去重**：168 → 106 筆（移除 62 筆重複/廢棄）
- [x] **修日期**：146 筆從檔名提取日期
- [x] **修 tags**：52 筆重新分類
- [x] **概念頁面精簡**：35 → 8 個（移除重複）
- [x] **Lint 報告**：矛盾 1 處、缺內容 4 筆、缺日期 0 筆、重複 0 組

---

## 🚧 進行中 / 待修復

- [ ] **admin.html Wiki 概念頁面 404**：概念頁面已改為英文檔名，需等待 GitHub CDN cache 過期後驗證
- [ ] **renderMd markdown 渲染**：`[[中文連結]]` 需要中英映射表才能正確跳轉

---

## 📋 待開發功能

### P2 — 改善現有功能
- [ ] **矛盾偵測升級**：接入 LLM 做語義級矛盾判斷（目前僅關鍵字匹配）
- [ ] **問答累積自動化**：在對話中自動判斷哪些洞見值得保存
- [ ] **搜尋引擎升級**：規模超過 500 筆時導入 BM25 或 qmd
- [ ] **缺內容影片補充**：4 筆影片仍缺少有意義的摘要（API rate limit 導致失敗）

### P3 — 新功能
- [ ] **定期自動 Lint**：用 OpenClaw cron 每週跑一次矛盾偵測
- [ ] **概念頁面自動更新**：新增影片後自動重建相關概念頁面
- [ ] **影片轉錄恢復**：抖音 cookies 問題解決後，重新為抖音影片生成完整轉錄
- [ ] **批量編輯**：支援一次選擇多張卡片批量修改分類/標籤

---

## 📂 專案結構

```
short-video-knowledge-base/
├── admin.html                  # 管理介面（入口）
├── short-videos.json           # 主資料庫（106 筆）
├── notes.json                  # 隨身筆記
├── index.html                  # 首頁
├── wiki/
│   ├── index.md                # Wiki 首頁
│   ├── lint-report.md          # 健康檢查報告
│   ├── concepts/               # 8 個概念頁面（英文檔名）
│   │   ├── ai-coding-tools.md
│   │   ├── ai-trends.md
│   │   ├── finance-investing.md
│   │   ├── psychology.md
│   │   ├── health.md
│   │   ├── entrepreneurship.md
│   │   ├── learning.md
│   │   └── science-history.md
│   └── insights/               # 洞見記錄
│       ├── 2026-04-13-GitHub-API-中文編碼陷阱.md
│       ├── 2026-04-13-Karpathy-llm-wiki-模式-vs-RAG.md
│       └── 2026-04-13-短影音知識庫架構演進.md
├── scripts/                    # 工具腳本
│   ├── search.py               # BM25 搜尋
│   ├── lint_wiki.py            # 矛盾偵測
│   ├── insight.py              # 洞見保存
│   └── fill_content.py         # 內容填充
├── short-videos/               # 同步備份
│   ├── admin.html
│   ├── short-videos.json
│   └── *.md                    # 106 筆影片報告
└── *.md                        # 106 筆影片報告（根目錄）
```

---

## 🔗 連結

- **GitHub Repo**：https://github.com/2015hdwl-Claw/short-video-knowledge-base
- **Admin 介面**：https://2015hdwl-claw.github.io/short-video-knowledge-base/admin.html
- **GitHub Pages**：https://2015hdwl-claw.github.io/short-video-knowledge-base/

---

_由 Alex 自動生成並維護_
