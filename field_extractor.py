import re
import json
from datetime import date
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, GOOGLE_API_KEY, GEMINI_MODEL, OWN_ORG

# 民國年轉西元年（用於 Sheets 日期欄位）
_ROC_YEAR_OFFSET = 1911


def extract_fields(text: str, recv_type: str) -> dict:
    """從公文文字解析各欄位，回傳欄位字典。"""
    fields = _parse_by_regex(text)
    if not _is_sufficient(fields):
        fields = _parse_by_claude(text, fields)
    org = fields.get("收/發文機關", "")
    fields["類型"] = "發文" if (OWN_ORG and org and (OWN_ORG in org or org in OWN_ORG)) else "收文"
    if fields["類型"] == "發文" and fields.get("_受文者"):
        fields["收/發文機關"] = fields["_受文者"]
    fields["收發類型"] = recv_type
    fields["案號"] = ""
    fields["備註"] = ""
    return fields


def _is_sufficient(fields: dict) -> bool:
    required = ["收/發文機關", "收發日期", "文號", "主旨"]
    return all(fields.get(k) for k in required)


def _parse_by_regex(text: str) -> dict:
    fields: dict = {}

    # 類型：預設收文，若有「正本」包含多個機關則可能為發文
    # 簡單判斷：若「受文者」不是公司名則視為收文，此處預設收文
    fields["類型"] = "收文"

    # 發文機關（搜尋含機關後綴的名稱，去除前綴雜訊）
    org_match = re.search(
        r"([^\s.﹒‥\n]{2,20}(?:部|署|局|府|院|廳|縣|市|區|鄉|鎮|分署|委員會|公司))",
        text
    )
    if org_match:
        fields["收/發文機關"] = org_match.group(1).strip()

    # 發文字號（接受各種 OCR 分隔符）
    ref_match = re.search(
        r"發文字號\s*[：:‥﹕]\s*([^\n\r]{4,40}號)",
        text
    )
    if ref_match:
        fields["文號"] = ref_match.group(1).strip()

    # 發文日期（接受各種 OCR 分隔符與空白）
    date_match = re.search(
        r"發文日期\s*[：:‥﹕﹔;]\s*(?:中華民國)?\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        text
    )
    if date_match:
        roc_y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
        fields["收發日期"] = _roc_to_date_str(roc_y, m, d)
        fields["_roc_date"] = f"{roc_y}.{m:02d}.{d:02d}"

    # 主旨（多行擷取至下一個段落標題；合併 OCR 換行）
    subject_match = re.search(
        r"主\s*旨\s*[：:‥﹕]\s*([\s\S]+?)(?=\n\s*(?:說明|辦法|正本|副本)|\Z)",
        text
    )
    if subject_match:
        subject_raw = re.sub(r"[ \t]*\n[ \t]*", "", subject_match.group(1)).strip()
        if len(subject_raw) >= 5:
            fields["主旨"] = subject_raw

    # 受文者（發文時用以替換收/發文機關欄位）
    recv_org_match = re.search(r"受文者\s*[：:‥﹕]\s*([^\n]+)", text)
    if recv_org_match:
        fields["_受文者"] = recv_org_match.group(1).strip()

    return fields


def _roc_to_date_str(roc_year: int, month: int, day: int) -> str:
    """民國年轉 YYYY/MM/DD 格式（供 Sheets 使用）。"""
    western = roc_year + _ROC_YEAR_OFFSET
    return f"{western}/{month:02d}/{day:02d}"


def roc_date_for_filename(fields: dict) -> str:
    """取得歸檔檔名用的民國日期字串，格式為 {民國年}.{月}.{日}。"""
    roc = fields.get("_roc_date", "")
    if roc:
        return roc
    # fallback：從西曆日期反推
    date_str = fields.get("收發日期", "")
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_str)
    if m:
        roc_y = int(m.group(1)) - _ROC_YEAR_OFFSET
        return f"{roc_y}.{m.group(2)}.{m.group(3)}"
    return date.today().strftime(f"{date.today().year - _ROC_YEAR_OFFSET}.%m.%d")


def _parse_by_claude(text: str, partial: dict) -> dict:
    """當 regex 解析不足時，呼叫 Claude API 補充欄位。"""
    if not ANTHROPIC_API_KEY:
        return partial
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = (
            "以下是一份台灣政府公文的文字內容，請從中擷取以下欄位並以 JSON 回傳：\n"
            "類型（收文或發文）、收/發文機關、收發日期（YYYY/MM/DD格式）、"
            "文號（發文字號）、主旨（完整主旨文字）\n\n"
            f"公文內容：\n{text[:3000]}\n\n"
            "僅回傳 JSON，不要加其他說明。"
        )
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        for k, v in parsed.items():
            if v and not partial.get(k):
                partial[k] = v
    except Exception:
        pass
    return partial


def extract_fields_from_images(images: list, recv_type: str) -> dict:
    """掃描件專用：直接以 Gemini Vision 從圖片擷取結構化欄位，回傳欄位字典。"""
    import io
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GOOGLE_API_KEY)

    prompt = (
        "這是一份台灣政府公文圖片，請擷取以下欄位並以 JSON 回傳：\n"
        '{"收/發文機關":"（信頭發文單位）", "受文者":"", "收發日期":"YYYY/MM/DD（西元年）", "文號":"", "主旨":""}\n'
        "主旨請擷取原文（完整文字，不要精簡）。\n"
        "找不到的欄位填空字串，只回傳 JSON，不要加說明。"
    )

    def _to_part(img):
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")

    parts = [types.Part.from_text(text=prompt)] + [_to_part(img) for img in images]
    response = client.models.generate_content(model=GEMINI_MODEL, contents=parts)
    raw = re.sub(r"^```json|```$", "", response.text.strip(), flags=re.MULTILINE).strip()
    parsed = json.loads(raw)

    fields: dict = {"收發類型": recv_type, "案號": "", "備註": ""}
    for k in ["收/發文機關", "受文者", "收發日期", "文號", "主旨"]:
        if parsed.get(k):
            fields[k] = str(parsed[k])
    org = fields.get("收/發文機關", "")
    fields["類型"] = "發文" if (OWN_ORG and org and (OWN_ORG in org or org in OWN_ORG)) else "收文"
    if fields["類型"] == "發文" and fields.get("受文者"):
        fields["收/發文機關"] = fields["受文者"]
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", fields.get("收發日期", ""))
    if m:
        roc_y = int(m.group(1)) - _ROC_YEAR_OFFSET
        fields["_roc_date"] = f"{roc_y}.{m.group(2)}.{m.group(3)}"
    return fields


def condense_subject(raw_subject: str) -> str:
    """用 Gemini 將公文主旨精簡為 30 字以內的重點摘要；若含日期/期限須保留。"""
    if not GOOGLE_API_KEY or not raw_subject:
        return raw_subject
    try:
        from google import genai
        client = genai.Client(api_key=GOOGLE_API_KEY)
        prompt = (
            "以下是一份台灣政府公文的主旨原文，請精簡為 40 字以內的重點摘要。"
            "規則：①最優先：若有期限計算語句（如「次日起N日曆天完成」「N工作天內提交」），必須完整保留；"
            "②保留核心事項；③不加任何說明或額外字元：\n"
            f"{raw_subject}"
        )
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        result = resp.text.strip()
        # 去除 Gemini 附加的字數標注（如「(30字)」「（40字）」）
        result = re.sub(r"\s*[（(]\d+字[)）]\s*$", "", result).strip()
        return result
    except Exception:
        return raw_subject


# === 更新日誌 ===
# [2026-05-13] [v1.0] 初始版本，regex 解析 + Claude API fallback + 案號查詢
# [2026-05-13] [v1.1] 移除案號自動查詢（_lookup_case），案號改由人工手動填寫，固定輸出空字串
# [2026-05-13] [v1.2] 新增 extract_fields_from_images()，掃描件改用 Gemini Vision 直接結構化擷取
# [2026-05-14] [v1.3] 遷移 Gemini SDK：google.generativeai → google.genai（棄用警告修正）
# [2026-05-14] [v1.4] 新增 condense_subject()（Gemini 精簡主旨，30字含日期）；Vision prompt 加精簡指示
# [2026-05-15] [v1.5] 提示詞改善：明確要求完整保留期限計算語句（次日起N日曆天等）；字數上限 30→40
# [2026-05-15] [v1.6] 修正 _parse_by_regex 主旨正則：改為多行擷取並合併 OCR 換行（原 [^\n]{5,} 僅擷取首行）；Vision prompt 改為原文擷取
# [2026-05-15] [v1.7] 新增 OWN_ORG 判斷：發文字號機關符合本機關名稱時自動標記「發文」
# [2026-05-16] [v1.8] condense_subject 去除 Gemini 字數標注（如「(30字)」）
# [2026-05-16] [v1.9] 發文時以「受文者」取代「收/發文機關」欄位（regex 與 Vision 路徑同步）
