# PLAN — 主旨擷取修正與 AI 精簡優化

## 現階段目標

修正最近 2 封公文主旨被過度擷取的問題，並讓 Gemini 精簡主旨時參考 Sheet 中過往已修正的主旨（few-shot 風格參考）。範圍僅限主旨擷取與精簡，不動收發判斷、欄位解析、歸檔、流水號。

## 已完成項目

- [x] 主旨 regex 終止條件改為「段落標題＋冒號」，不依賴換行（`field_extractor.py`，commit 30ddb8b）
- [x] 新增 `_strip_leader_dots` 清除公文點狀分隔線殘留（`field_extractor.py`）
- [x] `condense_subject` 改為重試 3 次＋失敗時本地截斷退回，不再回傳爆量原文（`field_extractor.py`）
- [x] 新增 `fetch_subject_examples()` 彙整各年份分頁主旨，單次執行快取（`sheets_manager.py`，commit 08b001c）
- [x] `condense_subject` 依「工程/計畫名關鍵字＋機關」自 Sheet 挑範例注入 prompt，含長度過濾與人工修正加權（`field_extractor.py`）
- [x] `main.py` 兩處 condense 呼叫傳入收/發文機關

## 驗證標準

驗證環境為 Windows 端（含 gspread、Gemini 金鑰、poppler/tesseract）；WSL 端僅能驗純邏輯。測試 PDF：`C:\scan\03fa1da8-…pdf`（070）、`C:\scan\a489e27f-…pdf`（071），皆為林業保育署嘉義分署香林服務區工程電子公文。

### A. 主旨擷取邊界（`field_extractor._parse_by_regex`）

- V1. 對 070 PDF 取 pdfplumber 文字後呼叫 `_parse_by_regex` → 主旨長度約 55 字，內容止於「…同意辦理, 請查照。」，不含「說明/正本」等後段。
- V2. 對 071 PDF 同上 → 主旨長度約 49 字，止於「…同意備查,請查照。」。
- V3. 主旨內不得出現連續點狀 leader（如「設置工...程」應為「設置工程」；驗證方式：主旨字串不含 2 個以上連續半形句點）。
- V4. 邊界：一份「說明」緊接換行且無點狀分隔線的正常公文 → 主旨仍正確止於「說明」前（回歸不退步）。

### B. AI 精簡韌性（`field_extractor.condense_subject` / `_local_condense`）

- V5. Gemini 正常回應時 → 主旨精簡為 40 字內重點；log「主旨已精簡（Gemini）」不再出現整段說明/正本全文。
- V6. 模擬 Gemini 連續失敗（暫時填錯 `GOOGLE_API_KEY` 或斷網）→ `condense_subject` 於重試 3 次後走本地截斷，回傳值長度 ≤ MAX_SUBJECT_LEN（40），且為原主旨開頭而非爆量全文。
- V7. `GOOGLE_API_KEY` 未設定 → 直接走 `_local_condense`，回傳截斷後主旨，不呼叫 Gemini、不崩潰。

### C. few-shot 範例注入（`field_extractor._build_subject_examples`）

- V8. 香林類公文（同機關、主旨含「香林…工程」）→ 範例區包含 Sheet 中同計畫/同機關的過往主旨（可於 debug 印出 prompt 或 `_build_subject_examples` 回傳值確認）。
- V9. 無關公文（他機關且主旨無工程/計畫名）→ `_build_subject_examples` 回傳空字串，prompt 退回原本內容（不注入不相關範例）。
- V10. 防污染：Sheet 中若存在超過 60 字的異常主旨列 → 不得被選為範例。
- V11. 人工修正加權：同時符合機關且已人工修正（J 檔名主旨 ≠ 正規化後 G 欄主旨）的列，排序應優先於未修正列；但單憑「已修正」不得讓不相關列入選。
- V12. 降級：Sheet 讀取失敗（無 gspread 或連線異常）→ `_build_subject_examples` 回傳空字串，精簡流程照常進行。

### D. 回歸（不影響其他功能）

- V13. 完整跑一封測試公文 → 歸檔檔名格式、Google Sheets 新增列、流水號遞增、`processed.json` 記錄均與修改前一致。
- V14. 掃描件（郵寄）路徑 → Vision 擷取後 condense 同樣帶入機關、正常精簡並歸檔。

## 注意事項

- 070/071 兩檔的 hash 已在 `processed.json`，直接重跑會被略過。若要實跑驗證 A/B，需準備新測試 PDF，或（僅測試用）暫時自 `processed.json` 移除對應 hash 後重跑，並於驗證後清掉重複產生的列/檔。
- 兩封已錯誤處理的 Sheet 列與檔名，使用者已手動修正，few-shot 不再受其污染。
- 相關性目前以「工程/計畫名關鍵字＋機關」為檢索鍵；案號因處理當下尚未產生（人工事後填寫），不作為即時檢索鍵，保留供未來 Phase 2 監督式配對使用。

## 更新日誌

- [2026-07-15] [v1.0] 建立本文件；記錄主旨擷取修正（commit 30ddb8b）與 few-shot 精簡優化（commit 08b001c）之已完成項目與驗證標準 V1–V14。
