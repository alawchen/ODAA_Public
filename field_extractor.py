import re
import json
import time
from datetime import date
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, GOOGLE_API_KEY, GEMINI_MODEL, OWN_ORG, MAX_SUBJECT_LEN

# 民國年轉西元年（用於 Sheets 日期欄位）
_ROC_YEAR_OFFSET = 1911

# 主旨精簡 few-shot 範例參數
_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
_EXAMPLE_LIMIT = 4        # 注入 prompt 的範例筆數上限
_EXAMPLE_MAX_LEN = 60     # 超過此長度的主旨視為異常，不採為範例（防污染）


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
    if fields["類型"] == "發文" and fields.get("_發文方式"):
        method = fields["_發文方式"]
        fields["收發類型"] = "電子公文" if method == "電子交換" else method
    fields["案號"] = ""
    fields["備註"] = ""
    if fields.get("文號"):
        fields["文號"] = re.sub(r"\s+", "", fields["文號"])
    return fields


def _is_sufficient(fields: dict) -> bool:
    required = ["收/發文機關", "收發日期", "文號", "主旨"]
    return all(fields.get(k) for k in required)


def _strip_leader_dots(text: str) -> str:
    """移除公文點狀分隔線殘留（2 個以上連續 ASCII 點/間隔點的 leader），保留中文句號。"""
    return re.sub(r"[.·・･•‧]{2,}", "", text)


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
        fields["文號"] = re.sub(r"\s+", "", ref_match.group(1))

    # 發文日期（接受各種 OCR 分隔符與空白）
    date_match = re.search(
        r"發文日期\s*[：:‥﹕﹔;]\s*(?:中華民國)?\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        text
    )
    if date_match:
        roc_y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
        fields["收發日期"] = _roc_to_date_str(roc_y, m, d)
        fields["_roc_date"] = f"{roc_y}.{m:02d}.{d:02d}"

    # 主旨（多行擷取至下一個段落標題；合併 OCR 換行、清除點狀 leader）
    # 終止條件以「段落標題＋冒號」為界，不依賴換行，避免公文點狀分隔線導致過度擷取
    subject_match = re.search(
        r"主\s*旨\s*[：:‥﹕]\s*([\s\S]+?)(?=(?:說明|辦法|正本|副本)\s*[：:]|\Z)",
        text
    )
    if subject_match:
        subject_raw = re.sub(r"[ \t]*\n[ \t]*", "", subject_match.group(1))
        subject_raw = _strip_leader_dots(subject_raw).strip()
        if len(subject_raw) >= 5:
            fields["主旨"] = subject_raw

    # 受文者（發文時用以替換收/發文機關欄位）
    recv_org_match = re.search(r"受文者\s*[：:‥﹕]\s*([^\n]+)", text)
    if recv_org_match:
        fields["_受文者"] = recv_org_match.group(1).strip()

    # 發文方式（發文時覆蓋 recv_type；僅存在於發文公文，如「郵寄」「電子交換」）
    send_method_match = re.search(r"發文方式\s*[：:]\s*([^\n\s]+)", text)
    if send_method_match:
        fields["_發文方式"] = send_method_match.group(1).strip()

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
        '{"收/發文機關":"（信頭發文單位）", "受文者":"", "收發日期":"YYYY/MM/DD（西元年）", "文號":"", "主旨":"", "發文方式":""}\n'
        "收發日期請務必取公文信頭的「發文日期」欄位（民國年換算西元），"
        "不可使用主旨、說明或內文中提及的其他日期（如會議、督導、紀錄、工程日期）；"
        "請逐字確認信頭日期數字，避免判讀錯誤。\n"
        "主旨請擷取原文（完整文字，不要精簡）。發文方式如有標示請擷取（如「郵寄」「電子交換」）。\n"
        "找不到的欄位填空字串，只回傳 JSON，不要加說明。"
    )

    def _to_part(img):
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")

    parts = [types.Part.from_text(text=prompt)] + [_to_part(img) for img in images]
    time.sleep(20)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=parts)
    raw = re.sub(r"^```json|```$", "", response.text.strip(), flags=re.MULTILINE).strip()
    parsed = json.loads(raw)

    fields: dict = {"收發類型": recv_type, "案號": "", "備註": ""}
    for k in ["收/發文機關", "受文者", "收發日期", "文號", "主旨", "發文方式"]:
        if parsed.get(k):
            fields[k] = str(parsed[k])
    org = fields.get("收/發文機關", "")
    fields["類型"] = "發文" if (OWN_ORG and org and (OWN_ORG in org or org in OWN_ORG)) else "收文"
    if fields["類型"] == "發文" and fields.get("受文者"):
        fields["收/發文機關"] = fields["受文者"]
    if fields["類型"] == "發文" and fields.get("發文方式"):
        method = fields["發文方式"]
        fields["收發類型"] = "電子公文" if method == "電子交換" else method
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", fields.get("收發日期", ""))
    if m:
        roc_y = int(m.group(1)) - _ROC_YEAR_OFFSET
        fields["_roc_date"] = f"{roc_y}.{m.group(2)}.{m.group(3)}"
    if fields.get("文號"):
        fields["文號"] = re.sub(r"\s+", "", fields["文號"])
    return fields


def _local_condense(raw_subject: str) -> str:
    """Gemini 不可用時的本地退回：截到第一個句號或 MAX_SUBJECT_LEN。"""
    s = _strip_leader_dots(raw_subject).strip()
    head = s.split("。")[0]
    if head and len(head) <= MAX_SUBJECT_LEN:
        return head
    return s[:MAX_SUBJECT_LEN]


def _extract_project_key(subject: str) -> str:
    """從主旨引號內抽取工程/計畫名（含『工程』『計畫』『計劃』者），作為相關性關鍵字。"""
    for m in re.findall(r"[「『]([^」』]{2,40})[」』]", subject or ""):
        if any(k in m for k in ("工程", "計畫", "計劃")):
            return m
    return ""


def _filename_subject(filename: str) -> str:
    """從歸檔檔名 NNN.日期_機關_主旨.pdf 取回主旨段（自動精簡當時的值）。"""
    base = re.sub(r"\.pdf$", "", filename or "")
    parts = base.split("_", 2)
    return parts[2] if len(parts) >= 3 else ""


def _norm_for_filename(s: str) -> str:
    """套用與歸檔檔名相同的截斷＋去非法字元，供比對是否被人工修正。"""
    return _ILLEGAL_CHARS.sub("", (s or "")[:MAX_SUBJECT_LEN]).strip()


def _is_human_corrected(ex: dict) -> bool:
    """比對 J 欄檔名主旨（auto）與正規化後 G 欄主旨，判斷該列是否經人工修正。"""
    auto = _filename_subject(ex.get("filename", ""))
    if not auto:
        return False
    return auto != _norm_for_filename(ex.get("subject", ""))


def _relevance(new_org: str, project_key: str, ex: dict) -> int:
    """依機關相符、工程/計畫名關鍵字、是否人工修正，計算範例相關性分數。"""
    score = 0
    org = ex.get("org", "")
    if new_org and org and (new_org == org or new_org in org or org in new_org):
        score += 2
    if project_key:
        subj = ex.get("subject", "")
        for i in range(len(project_key) - 2):
            if project_key[i:i + 3] in subj:
                score += 3
                break
    # 人工修正僅作為「已相關列」的排序加權，不得單獨讓不相關列入選
    if score > 0 and _is_human_corrected(ex):
        score += 1
    return score


def _build_subject_examples(new_org: str, raw_subject: str) -> str:
    """讀 Sheet 依相關性挑選過往主旨，組成 few-shot 範例區字串；無可用範例時回傳空字串。"""
    try:
        from sheets_manager import fetch_subject_examples
        rows = fetch_subject_examples()
    except Exception:
        return ""
    project_key = _extract_project_key(raw_subject)
    scored = []
    for ex in rows:
        subj = ex.get("subject", "").strip()
        if not subj or len(subj) > _EXAMPLE_MAX_LEN:  # 排除異常長度（防污染）
            continue
        s = _relevance(new_org, project_key, ex)
        if s > 0:
            scored.append((s, subj))
    if not scored:
        return ""
    scored.sort(key=lambda x: x[0], reverse=True)
    seen, picked = set(), []
    for _, subj in scored:
        if subj in seen:
            continue
        seen.add(subj)
        picked.append(subj)
        if len(picked) >= _EXAMPLE_LIMIT:
            break
    lines = "\n".join(f"- {p}" for p in picked)
    return (
        "以下是本單位過往主旨精簡範例，請比照其長度、詳略與用語風格（僅供風格參考，勿抄內容）：\n"
        f"{lines}\n\n"
    )


def condense_subject(raw_subject: str, org: str = "") -> str:
    """用 Gemini 將公文主旨精簡為 40 字以內重點；重試 3 次仍失敗則本地截斷退回。
    org 若提供，會參考 Sheet 中同機關/同計畫過往已修正主旨作為 few-shot 風格範例。"""
    if not raw_subject:
        return raw_subject
    if not GOOGLE_API_KEY:
        return _local_condense(raw_subject)
    examples = _build_subject_examples(org, raw_subject)
    prompt = (
        "以下是一份台灣政府公文的主旨原文，請精簡為 40 字以內的重點摘要。"
        "規則：①若原文提及工程名稱或計畫名稱，將其置於摘要開頭，再接重點（格式：「XXX工程 摘要重點」）；"
        "②最優先：若有期限計算語句（如「次日起N日曆天完成」「N工作天內提交」），必須完整保留；"
        "③保留核心事項；④不加任何說明或額外字元：\n\n"
        f"{examples}"
        f"待精簡主旨：{raw_subject}"
    )
    from google import genai
    for attempt in range(3):
        try:
            client = genai.Client(api_key=GOOGLE_API_KEY)
            time.sleep(20)
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            # 去除 Gemini 附加的字數標注（如「(30字)」「（40字）」）
            result = re.sub(r"\s*[（(]\d+字[)）]\s*$", "", resp.text.strip()).strip()
            if result:
                return result
        except Exception:
            time.sleep(5 * (attempt + 1))
    return _local_condense(raw_subject)


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
# [2026-06-01] [v2.0] 擷取「發文方式」欄位：發文時以文件內標示覆蓋 recv_type（電子交換→電子公文，郵寄→郵寄）
# [2026-06-12] [v2.1] 文號去除內部空白（三處：regex/extract_fields/Vision 路徑）；condense_subject 工程/計畫名稱前置
# [2026-06-12] [v2.2] Gemini 呼叫前加 time.sleep(20) 限速，避免觸及 free tier RPM 上限
# [2026-06-16] [v2.3] Vision prompt 強化收發日期擷取：限定取信頭發文日期、禁用內文其他日期、逐字確認數字
# [2026-07-15] [v2.4] 修正主旨過度擷取：終止條件改為「段落標題＋冒號」不依賴換行；新增 _strip_leader_dots 清除點狀分隔線；condense_subject 改為重試 3 次＋失敗時本地截斷退回（不再回傳爆量原文）
# [2026-07-15] [v2.5] condense_subject 加入 few-shot：依機關＋工程/計畫名關鍵字自 Sheet 挑過往已修正主旨為風格範例（in-context，不改模型）；防污染長度過濾＋人工修正加權
