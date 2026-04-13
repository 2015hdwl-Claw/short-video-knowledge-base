# GitHub API 中文編碼陷阱

> GitHub Contents API 回傳的 content 是 base64 編碼的 UTF-8。絕對不能用 atob() 直接解碼中文，必須用 TextDecoder：new TextDecod...

## 💡 洞見

GitHub Contents API 回傳的 content 是 base64 編碼的 UTF-8。絕對不能用 atob() 直接解碼中文，必須用 TextDecoder：new TextDecoder().decode(Uint8Array.from(atob(base64), c => c.charCodeAt(0)))。寫入用 btoa(unescape(encodeURIComponent(text))) 沒問題，但讀回來必須用 TextDecoder。2026-04-13 事故：admin.html 編輯功能用 atob() 解碼導致 163 筆全毀。

## 🔗 相關概念

- [[AI工具與編程]]

---
📅 2026-04-13 | 🏷️ 未分類
