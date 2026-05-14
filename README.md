# ODAA 公文自動歸檔系統

自動處理每日進出公文 PDF，完成欄位解析、依規則命名歸檔、並寫入公文收發紀錄表（預設使用 Google Sheets），可搭配 Windows 工作排程器自動觸發，完成半人工（人工掃描 + 電子公文人工下載）、半自動的公文歸檔作業。

> 初始設定請參閱：`公文自動歸檔系統設定文件.html`

---

## 功能

- **電子公文**：pdfplumber 擷取文字 → regex 解析欄位 → Claude Haiku fallback
- **掃描件**：Gemini 2.5 Flash Vision 直接辨識並結構化擷取
- **主旨精簡**：呼叫 Gemini API 將主旨精簡為 30 字以內重點（含日期/期限優先保留）
- **歸檔命名**：`{流水號}.{發文日期}_{發文單位}_{Gemini精簡後的主旨}.pdf`
- **多年份分頁**：Google Sheets 依民國年自動建立分頁，流水號每年從 001 重置
- **防重複**：`processed.json` 記錄已處理 PDF，重複執行不重複寫入

---

## 工作流程

```
公文 PDF 放入來源資料夾（INBOX_DIR）
    │
    ├─ 已在 processed.json → 略過
    │
    └─ 新檔案
        ├─ 電子公文（pdfplumber 字數 ≥ 50）
        │    regex / Claude Haiku → 欄位擷取 → Gemini 精簡主旨
        │
        └─ 掃描件（字數 < 50）
             Gemini Vision → 欄位擷取 + 主旨精簡（一步完成）
             └─ 無 API Key → Tesseract OCR fallback

        ↓ 共同後續
        取得流水號（Google Sheets 對應年份分頁最大值 +1）
        → 依命名規則建立檔名
        → 複製 PDF 至歸檔資料夾（ARCHIVE_BASE_DIR/{民國年}年/）
        → 新增一列至 Google Sheets
        → 記錄至 processed.json
```
