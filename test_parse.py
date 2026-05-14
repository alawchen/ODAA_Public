import sys
import io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pdf_parser import extract_text
from field_extractor import extract_fields
from file_manager import build_archive_filename

if len(sys.argv) < 2:
    print("用法：python test_parse.py <pdf路徑1> [<pdf路徑2> ...]")
    sys.exit(1)
pdfs = sys.argv[1:]

for i, pdf in enumerate(pdfs, 1):
    name = pdf.split("\\")[-1]
    print(f"\n=== PDF {i}: {name} ===")
    text, recv_type = extract_text(pdf)
    print(f"  [擷取字數: {len(text)}，類型: {recv_type}]")
    # 顯示前 300 字供調試
    print(f"  [文字預覽]: {repr(text[:300])}")
    fields = extract_fields(text, recv_type)
    fname = build_archive_filename(fields, i)
    print(f"  收發類型: {fields.get('收發類型')}")
    print(f"  收/發文機關: {fields.get('收/發文機關')}")
    print(f"  收發日期: {fields.get('收發日期')}")
    print(f"  文號: {fields.get('文號')}")
    print(f"  主旨: {str(fields.get('主旨', ''))[:60]}")
    print(f"  案號: {fields.get('案號')}")
    print(f"  歸檔檔名: {fname}")
