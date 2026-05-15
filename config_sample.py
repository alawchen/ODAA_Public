import os
from pathlib import Path
from dotenv import load_dotenv

# 使用說明：將此檔複製為 config.py，再依需求調整各項預設值。
# config.py 已列入 .gitignore，不入版控。

load_dotenv(Path(__file__).parent / ".env")

# === 路徑設定 ===
BASE_DIR = str(Path(__file__).parent)  # 自動偵測，不需手動設定
INBOX_DIR = os.environ.get("INBOX_DIR", "")
ARCHIVE_BASE_DIR = os.environ.get("ARCHIVE_BASE_DIR", "")
ARCHIVE_SUBDIR = os.environ.get("ARCHIVE_SUBDIR", "歸檔公文")  # 可在 .env 覆寫
LOGS_DIR = os.path.join(BASE_DIR, "logs")
PROCESSED_JSON = os.path.join(BASE_DIR, "processed.json")
CREDENTIALS_JSON = os.path.join(BASE_DIR, "credentials.json")

# === OCR 工具路徑 ===
TESSERACT_CMD = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
TESSDATA_DIR = os.path.join(BASE_DIR, "tessdata")
POPPLER_PATH = os.environ.get("POPPLER_PATH", "")

# === Google Sheets 設定 ===
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
SHEET_NAME = "工作表1"  # 若有多個分頁請修改為正確名稱

# === 啟動驗證（必要環境變數）===
_required = {
    "INBOX_DIR": INBOX_DIR,
    "ARCHIVE_BASE_DIR": ARCHIVE_BASE_DIR,
    "POPPLER_PATH": POPPLER_PATH,
    "SPREADSHEET_ID": SPREADSHEET_ID,
}
_missing = [k for k, v in _required.items() if not v]
if _missing:
    raise EnvironmentError(f"請在 .env 設定以下必要變數：{_missing}")

# === 欄位順序（對應 Google Sheets 欄位，A~J）===
SHEET_COLUMNS = ["類型", "收發類型", "收/發文機關", "收發日期", "文號", "案號", "主旨", "備註", "流水號", "歸檔檔名"]

# === Claude API（OCR fallback 用）===
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# === Gemini API（掃描件辨識用）===
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

# === 本機關設定 ===
OWN_ORG = os.environ.get("OWN_ORG", "")  # 本公司／機關名稱，用於判斷收發文類型

# === 解析設定 ===
TEXT_PDF_MIN_CHARS = 50  # 低於此字數視為掃描件
MAX_SUBJECT_LEN = 40     # 歸檔檔名主旨最大字元數（Gemini 精簡後上限）
MAX_ORG_LEN = 10         # 歸檔檔名機關名最大字元數

# === 更新日誌 ===
# [2026-05-13] [v1.0] 初始版本，定義所有路徑與設定常數
# [2026-05-13] [v1.1] ARCHIVE_DIR 改為 ARCHIVE_BASE_DIR + ARCHIVE_SUBDIR，支援依年份動態歸檔
# [2026-05-13] [v1.2] 移除 CASE_LOOKUP_JSON（案號改人工手動填寫）
# [2026-05-13] [v1.3] 新增 GOOGLE_API_KEY、GEMINI_MODEL（掃描件 Gemini Vision 辨識）
# [2026-05-13] [v1.4] 敏感資訊改由 .env 管理：BASE_DIR 自動偵測，路徑與 ID 移至環境變數，加啟動驗證
# [2026-05-14] [v1.5] ARCHIVE_SUBDIR 改由 .env 設定（預設 "歸檔公文"）
# [2026-05-15] [v1.6] MAX_SUBJECT_LEN: 25 → 40（期限語句完整保留需要更多空間）
# [2026-05-15] [v1.7] 新增 OWN_ORG 設定（本機關名稱，用於判斷收發文類型）
