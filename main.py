import os
import sys
import json
import logging
from datetime import datetime, date
from config import INBOX_DIR, LOGS_DIR, PROCESSED_JSON, GOOGLE_API_KEY
from pdf_parser import extract_text, get_pdf_images
from field_extractor import extract_fields, extract_fields_from_images, condense_subject
from sheets_manager import get_next_serial, append_record
from file_manager import build_archive_filename, archive_pdf

os.makedirs(LOGS_DIR, exist_ok=True)
log_file = os.path.join(LOGS_DIR, f"run_{datetime.now():%Y%m%d}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def load_processed() -> set:
    if os.path.exists(PROCESSED_JSON):
        with open(PROCESSED_JSON, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_processed(processed: set):
    with open(PROCESSED_JSON, "w", encoding="utf-8") as f:
        json.dump(sorted(processed), f, ensure_ascii=False, indent=2)


def scan_inbox() -> list[str]:
    if not os.path.isdir(INBOX_DIR):
        log.error(f"公文夾不存在：{INBOX_DIR}")
        return []
    return [
        os.path.join(INBOX_DIR, f)
        for f in os.listdir(INBOX_DIR)
        if f.lower().endswith(".pdf")
    ]


def process_pdf(pdf_path: str, processed: set) -> bool:
    filename = os.path.basename(pdf_path)
    if filename in processed:
        log.info(f"略過（已處理）：{filename}")
        return False

    log.info(f"處理中：{filename}")
    try:
        text, recv_type = extract_text(pdf_path)

        if recv_type == "郵寄" and GOOGLE_API_KEY:
            images = get_pdf_images(pdf_path)
            if images:
                log.info(f"使用 Gemini Vision 辨識掃描件：{filename}")
                fields = extract_fields_from_images(images, recv_type)
                if fields.get("主旨"):
                    fields["主旨"] = condense_subject(fields["主旨"])
                    log.info(f"主旨已精簡（Gemini）：{fields['主旨']}")
            else:
                log.warning(f"圖片轉換失敗，退回 Tesseract：{filename}")
                fields = extract_fields(text, recv_type)
        else:
            if text.startswith("[OCR 失敗"):
                log.warning(f"OCR 失敗，需人工複核：{filename}")
            fields = extract_fields(text, recv_type)
            if fields.get("主旨") and GOOGLE_API_KEY:
                fields["主旨"] = condense_subject(fields["主旨"])
                log.info(f"主旨已精簡（Gemini）：{fields['主旨']}")
        _log_parse_result(filename, fields)

        roc_year = fields.get("_roc_date", "").split(".")[0] or str(date.today().year - 1911)
        serial = get_next_serial(roc_year)
        archive_name = build_archive_filename(fields, serial)
        archive_pdf(pdf_path, archive_name, fields)
        append_record(fields, serial, archive_name)

        processed.add(filename)
        log.info(f"完成：{archive_name}")
        return True

    except Exception as e:
        log.error(f"處理失敗 {filename}：{e}", exc_info=True)
        return False


def _log_parse_result(filename: str, fields: dict):
    missing = [k for k in ["收/發文機關", "收發日期", "文號", "主旨"] if not fields.get(k)]
    if missing:
        log.warning(f"欄位解析不完整（{filename}），需人工確認：{missing}")


def main():
    log.info("=== 公文處理程式啟動 ===")
    processed = load_processed()
    pdfs = scan_inbox()
    log.info(f"公文夾發現 {len(pdfs)} 份 PDF，已處理 {len(processed)} 份")

    new_count = 0
    for pdf_path in pdfs:
        if process_pdf(pdf_path, processed):
            new_count += 1
            save_processed(processed)  # 每處理一份即儲存，防止中途中斷遺失

    log.info(f"本次新處理 {new_count} 份，程式結束")


if __name__ == "__main__":
    main()

# === 更新日誌 ===
# [2026-05-13] [v1.0] 初始版本，主控流程整合所有模組
# [2026-05-13] [v1.1] archive_pdf 呼叫補傳 fields，支援依年份歸檔
# [2026-05-13] [v1.2] get_next_serial 傳入 roc_year，流水號依年份重置
# [2026-05-13] [v1.3] 移除 ensure_header_columns（邏輯已移入 sheets_manager._get_sheet）
# [2026-05-13] [v1.4] 移除案號未對應 log 警告（案號改人工填寫）
# [2026-05-13] [v1.5] 掃描件改用 Gemini Vision 路徑，Tesseract 保留為 fallback
# [2026-05-14] [v1.6] 電子公文路徑新增 condense_subject() 呼叫
# [2026-05-15] [v1.7] 掃描件 Vision 路徑亦加入 condense_subject() 呼叫
