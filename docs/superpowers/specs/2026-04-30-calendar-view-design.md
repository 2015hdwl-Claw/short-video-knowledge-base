# Calendar View Design — added_date 追蹤功能

**Date:** 2026-04-30
**Scope:** 為短影音知識庫新增「寫入時間」追蹤，支持依寫入時間排序
**Status:** Design Approved · Pending Implementation

## 設計概述

在現有的 admin.html 基礎上，為每個知識卡片新增 added_date 欄位，用來追蹤影片被寫入知識庫的時間。保留原有的 date 欄位（短影音原始發布日期），兩者並存。

核心需求：
1. 新增卡片時自動記錄寫入時間（當前 ISO 8601 時間）
2. 編輯時可手動修改寫入日期
3. 支持依寫入時間排序（新→舊、舊→新）
4. 卡片上顯示兩個日期（原始發布日期 + 寫入日期）
5. 舊數據向下相容（沒有 added_date 的卡片視為空）

## 數據結構

short-videos.json 新增欄位：
- title: 影片標題
- date: 原始發布日期（保持不變）
- added_date: 新增：寫入日期（ISO 8601）
- source: 作者
- category: 類別
- core_points: 核心要點
- tags: 標籤數組
- url: 原始連結
- file: 檔案路徑
- advice: 實踐建議
- audience: 目標受眾
- note: 備註
- personal_insight: 個人觀點

遷移處理規則：
- 沒有 added_date 的舊卡片：在 admin.html 加載時使用 date 作為 added_date 的默認值
- 新增卡片：pipeline.py 自動寫入當前時間
- 編輯卡片：可手動設定 added_date，留空則保持原值

## 介面設計

1. 排序選單新增「依寫入時間」
   - 依寫入時間（新→舊）
   - 依寫入時間（舊→新）
   - 依原發布時間（新→舊）
   - 依原發布時間（舊→新）
   - 按標題排序

2. 日期格式化顯示
   - 原始發布日期：📅 YYYY-MM-DD
   - 寫入日期：✨ 今天 / 昨天 / N 天前 / MM-DD

3. 編輯對話框新增欄位
   - 標題
   - 來源/作者
   - 原始連結
   - 分類
   - 標籤（逗號分隔）
   - 核心重點
   - 實踐建議
   - 適合對象
   - 備註
   - 個人觀點
   - 寫入日期（新增）

4. 卡片日期徽章顯示
   - Meta 欄顯示兩個日期徽章

5. Modal 詳情顯示
   - 標題
   - 來源/分類/日期徽章
   - 原始連結
   - 核心重點
   - 實踐建議
   - 適合對象
   - 備註
   - 個人觀點

## 實施步驟

步驟 1：修改 pipeline.py
- 文件：scripts/pipeline.py
- 函數：_save_video()
- 變更：在 entry 字典中新增 added_date 欄位
- 代碼：entry["added_date"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

步驟 2：修改 admin.html — 數據遷移處理
- 位置：加載數據後
- 變更：為沒有 added_date 的舊卡片添加默認值
- 邏輯：
  if (!v.added_date) {
      v.added_date = v.date ? v.date + 'T00:00:00Z' : '';
  }

步驟 3：修改 admin.html — 排序邏輯
- 函數：render()
- 變更：新增依寫入時間排序邏輯
- 代碼：
  if (sort === 'added-desc') {
      filtered.sort((a,b) => {
          const da = a.added_date ? new Date(a.added_date) : new Date(0);
          const db = b.added_date ? new Date(b.added_date) : new Date(0);
          return db - da;
      });
  } else if (sort === 'added-asc') {
      filtered.sort((a,b) => {
          const da = a.added_date ? new Date(a.added_date) : new Date(0);
          const db = b.added_date ? new Date(b.added_date) : new Date(0);
          return da - db;
      });
  }

步驟 4：修改 admin.html — 編輯保存
- 函數：saveEdit()
- 變更：保存 added_date 欄位
- 代碼：videos[idx].added_date = getVal('ed_added_date') || videos[idx].added_date;

步驟 5：修改 admin.html — 輔助函數
- 新增：formatDate(), formatAddedDate()
- 位置：script 開頭
- 功能：日期格式化

步驟 6：修改 admin.html — HTML 模板更新
- 位置：排序下拉選單
- 變更：新增依寫入時間選項

## 測試計畫

測試場景 1：新增卡片
1. 發送抖音連結到 Telegram bot
2. Bot 處理完成，推送到 GitHub
3. 打開 admin.html
4. 檢查新卡片顯示：📅 原始發布日期 | ✨ 今天 或類似格式

測試場景 2：排序切換
1. 點擊「依寫入時間（新→舊）」
2. 檢查卡片排列順序正確
3. 切換到「依原發布時間」
4. 檢查順序重新按原始日期排列

測試場景 3：編輯卡片
1. 點擊卡片編輯圖示
2. 修改「寫入日期」欄位
3. 點擊儲存
4. 檢查 Modal 和卡片上顯示更新後的日期

測試場景 4：舊數據相容
1. 加載 admin.html
2. 檢查沒有 added_date 的舊卡片正常顯示
3. 檢查 UI 不報錯

## 已知限制

1. 批次編輯功能（batchSetCategory 和 batchSetTags）不會更新 added_date，需要時可以擴展
2. 歷史數據：已存在的舊卡片沒有準確的 added_date，會用 date 作為默認值（可接受）
3. 時區：使用瀏覽器本地時間，與 Render 伺服器時間可能不一致（影響「今天/昨天」顯示）

## 未來擴展建議

1. 如果用戶想要完整的 Calendar 視圖，可考慮作為 Phase 2
   - 新增第四個 Tab：Calendar
   - 以週為單位顯示寫入數量熱力圖
   - 點擊日期查看該天的所有卡片

2. 如果需要精確的「寫入時間」記錄，可以在 Bot 收到訊息時就寫入時間戳，而非在 pipeline 完成時
