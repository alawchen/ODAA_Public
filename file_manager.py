import os
import re
import shutil
from datetime import date
from field_extractor import roc_date_for_filename
from config import ARCHIVE_BASE_DIR, ARCHIVE_SUBDIR, MAX_SUBJECT_LEN, MAX_ORG_LEN

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
_ROC_YEAR_OFFSET = 1911


def build_archive_filename(fields: dict, serial: int) -> str:
    """依規則建立歸檔檔名（不含路徑）。
    格式：NNN.{民國年}.{月}.{日}_{機關名稱}_{主旨}.pdf
    """
    roc_date = roc_date_for_filename(fields)
    org = _sanitize(_truncate(fields.get("收/發文機關", "未知機關"), MAX_ORG_LEN))
    subject = _sanitize(_truncate(fields.get("主旨", "無主旨"), MAX_SUBJECT_LEN))
    serial_str = f"{serial:03d}"
    return f"{serial_str}.{roc_date}_{org}_{subject}.pdf"


def _get_archive_dir(fields: dict) -> str:
    """依公文的民國年與收/發文類型決定歸檔資料夾：
    ARCHIVE_BASE_DIR / {民國年}年 / ARCHIVE_SUBDIR / {收文|發文}。
    """
    roc_date = fields.get("_roc_date", "")
    if roc_date:
        year = roc_date.split(".")[0]
    else:
        year = str(date.today().year - _ROC_YEAR_OFFSET)
    doc_type = fields.get("類型", "收文")
    return os.path.join(ARCHIVE_BASE_DIR, f"{year}年", ARCHIVE_SUBDIR, doc_type)


def archive_pdf(src_path: str, archive_filename: str, fields: dict) -> str:
    """複製 PDF 至依年份決定的歸檔資料夾，回傳目標完整路徑。"""
    archive_dir = _get_archive_dir(fields)
    os.makedirs(archive_dir, exist_ok=True)
    dst_path = os.path.join(archive_dir, archive_filename)
    # 若目標已存在（重名），加 _dup 後綴避免覆蓋
    if os.path.exists(dst_path):
        base, ext = os.path.splitext(archive_filename)
        dst_path = os.path.join(archive_dir, f"{base}_dup{ext}")
    shutil.copy2(src_path, dst_path)
    return dst_path


def _truncate(text: str, max_len: int) -> str:
    return text[:max_len]


def _sanitize(text: str) -> str:
    return _ILLEGAL_CHARS.sub("", text).strip()

# === 更新日誌 ===
# [2026-05-13] [v1.0] 初始版本，歸檔命名規則與複製功能
# [2026-05-13] [v1.1] archive_pdf 新增 fields 參數，依公文民國年動態決定歸檔路徑
# [2026-06-01] [v1.2] 歸檔路徑加入收/發文子資料夾（收文\ 或 發文\），方便檔案總管直接辨識
