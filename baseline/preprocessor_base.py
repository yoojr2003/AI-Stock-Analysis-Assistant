import os
from bs4 import BeautifulSoup
import glob

OUTPUT_DIR = "/content/dart_reports"

def extract_text(filepath):
    """
    DART XML/HTML 파일에서 순수 텍스트만 추출하는 함수
    """
    try:
        # DART 문서는 utf-8 인코딩 사용
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 'html.parser'를 사용하여 엄격한 XML 문법 에러 무시
        soup = BeautifulSoup(content, 'html.parser')

        # 쓸모없는 태그 제거
        for script_or_style in soup(['script', 'style', 'noscript']):
            script_or_style.decompose()

        # 텍스트 추출
        clean_text = soup.get_text(separator=' ', strip=True)

        return clean_text

    except Exception as e:
        print(f"파일 파싱 중 오류 발생 ({filepath}): {e}")
        return ""

def process_reports():
    """
    보고서를 파싱하여 텍스트로 변환하는 함수
    """
    # xml이나 html 파일 목록을 탐색
    file_pattern = os.path.join(OUTPUT_DIR, "*.[xh][mt][ml]*") 
    report_files = glob.glob(file_pattern)

    if not report_files:
        print("파싱할 파일이 없음")
        return

    print(f"{len(report_files)}개의 보고서 텍스트 추출을 시작\n")

    parsed_data_list = []

    for filepath in report_files:
        filename = os.path.basename(filepath)
        print(f"[{filename}] 파싱")

        text = extract_text(filepath)

        if text:
            print(f"  총 {len(text):,}자 추출\n")

            parsed_data_list.append({
                "filename": filename,
                "text": text
            })

    return parsed_data_list

parsed_reports = process_reports()

# 테스트
if parsed_reports:
  print("=== 첫 번째 문서 미리보기 ===")
  print(parsed_reports[0]["text"][:500])

import json

with open(os.path.join(OUTPUT_DIR, "parsed_reports.json"), "w", encoding="utf-8") as f:
    json.dump(parsed_reports, f, ensure_ascii=False, indent=2)

print("저장 완료")