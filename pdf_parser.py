import os
import unicodedata
import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from config import TESSERACT_CMD, TESSDATA_DIR, POPPLER_PATH, TEXT_PDF_MIN_CHARS


def get_pdf_images(pdf_path: str) -> list:
    """將 PDF 各頁轉為 PIL Image 清單，供 Gemini Vision 使用。"""
    try:
        return convert_from_path(pdf_path, dpi=200, poppler_path=POPPLER_PATH)
    except Exception:
        return []

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def extract_text(pdf_path: str) -> tuple[str, str]:
    """從 PDF 擷取文字，回傳 (文字內容, 偵測類型)。
    類型為 '電子公文' 或 '郵寄'（掃描件）。
    """
    text = _extract_text_pdf(pdf_path)
    if len(text.strip()) >= TEXT_PDF_MIN_CHARS:
        return text, "電子公文"
    ocr_text = _extract_scan_pdf(pdf_path)
    return ocr_text, "郵寄"


def _extract_text_pdf(pdf_path: str) -> str:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return unicodedata.normalize("NFKC", "\n".join(pages))
    except Exception:
        return ""


def _extract_scan_pdf(pdf_path: str) -> str:
    try:
        images = convert_from_path(
            pdf_path,
            dpi=300,
            poppler_path=POPPLER_PATH,
        )
        pages_text = []
        for img in images:
            text = pytesseract.image_to_string(
                img,
                lang="chi_tra+eng",
                config="--tessdata-dir " + TESSDATA_DIR,
            )
            pages_text.append(text)
        raw = "\n".join(pages_text)
        return _clean_ocr_text(unicodedata.normalize("NFKC", raw))
    except Exception as e:
        return f"[OCR 失敗: {e}]"


def _clean_ocr_text(text: str) -> str:
    """移除 OCR 掃描件中 CJK 字元與數字之間的多餘空白（多輪替換直到穩定）。"""
    import re
    cjk = r'[一-鿿㐀-䶿！-｠　-〿]'
    # 多輪去除相鄰 CJK 字元間空白（使用 lookahead 避免吞字）
    for _ in range(5):
        prev = text
        text = re.sub(rf'({cjk})\s+(?={cjk})', r'\1', text)
        if text == prev:
            break
    # 數字與年月日號之間的空白
    text = re.sub(r'(\d)\s+(年|月|日|號)', r'\1\2', text)
    text = re.sub(r'(年|月)\s+(\d)', r'\1\2', text)
    return text

# === 更新日誌 ===
# [2026-05-13] [v1.0] 初始版本，文字型 PDF 用 pdfplumber，掃描件用 pytesseract
# [2026-05-13] [v1.1] 加入 Unicode NFKC 正規化，修正 PDF 使用 CJK 相容表意字元（如 U+F98E）導致 regex 無法比對年月日
# [2026-05-13] [v1.2] 新增 get_pdf_images()，將 PDF 頁面轉為 PIL Image 清單供 Gemini Vision 使用
