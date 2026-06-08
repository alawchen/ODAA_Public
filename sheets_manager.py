import re
from datetime import date
import gspread
from google.oauth2.service_account import Credentials
from config import CREDENTIALS_JSON, SPREADSHEET_ID, SHEET_COLUMNS

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_spreadsheet_cache = None
_sheet_cache: dict = {}  # {roc_year: worksheet}


def _get_spreadsheet():
    global _spreadsheet_cache
    if _spreadsheet_cache is None:
        creds = Credentials.from_service_account_file(CREDENTIALS_JSON, scopes=_SCOPES)
        gc = gspread.authorize(creds)
        _spreadsheet_cache = gc.open_by_key(SPREADSHEET_ID)
    return _spreadsheet_cache


def _get_sheet(roc_year: str):
    """依民國年取得對應分頁，不存在時自動建立並寫入標題列。"""
    if roc_year in _sheet_cache:
        return _sheet_cache[roc_year]
    spreadsheet = _get_spreadsheet()
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    if roc_year in existing:
        sheet = existing[roc_year]
    else:
        sheet = spreadsheet.add_worksheet(title=roc_year, rows=1000, cols=10)
        sheet.update("A1", [SHEET_COLUMNS])
    _sheet_cache[roc_year] = sheet
    return sheet


def _year_from_fields(fields: dict) -> str:
    roc_date = fields.get("_roc_date", "")
    return roc_date.split(".")[0] if roc_date else str(date.today().year - 1911)


def get_next_serial(roc_year: str) -> int:
    """掃描指定年份分頁的 J 欄歸檔檔名，回傳同年份最大流水號 + 1。"""
    sheet = _get_sheet(roc_year)
    filename_col = sheet.col_values(10)  # J 欄（1-based）
    pattern = re.compile(rf'^(\d{{3}})\.{re.escape(roc_year)}\.')
    nums = []
    for v in filename_col[1:]:
        m = pattern.match(str(v).strip())
        if m:
            nums.append(int(m.group(1)))
    return max(nums, default=0) + 1


def append_record(fields: dict, serial: int, archive_filename: str):
    """在對應年份分頁末尾新增一列公文紀錄。"""
    roc_year = _year_from_fields(fields)
    sheet = _get_sheet(roc_year)
    row = [
        fields.get("類型", ""),
        fields.get("收發類型", ""),
        fields.get("收/發文機關", ""),
        fields.get("收發日期", ""),
        re.sub(r"\s+", "", fields.get("文號", "")),
        fields.get("案號", ""),
        fields.get("主旨", ""),
        fields.get("備註", ""),
        f"{serial:03d}",
        archive_filename,
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")

# === 更新日誌 ===
# [2026-05-13] [v1.0] 初始版本，gspread 服務帳號認證、流水號讀取、新增列
# [2026-05-13] [v1.1] 修正流水號格式：str(serial) → f"{serial:03d}"，輸出 001/002/003
# [2026-05-13] [v1.2] get_next_serial 改為依民國年篩選 J 欄歸檔檔名，流水號每年從 001 重置
# [2026-05-13] [v1.3] 改為多分頁架構：依民國年取得/建立分頁，移除 ensure_header_columns
# [2026-05-13] [v1.4] 改用 worksheets() 清單比對取代 try/except WorksheetNotFound，修正 gspread 6.x 相容性問題
# [2026-06-08] [v1.5] append_record 文號欄位去除所有空白字元（含 OCR/AI 引入的內部空白）
