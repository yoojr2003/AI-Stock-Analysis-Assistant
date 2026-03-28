import os
from bs4 import BeautifulSoup
import glob
import pandas as pd # 표 변환을 위해 추가
import json
from io import StringIO

OUTPUT_DIR = "/content/dart_reports"

def extract_table_aware(filepath):
    """
    DART XML/HTML 파일에서 표 구조(Markdown)를 보존하며 텍스트를 추출하는 함수
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        soup = BeautifulSoup(content, 'html.parser')

        # 쓸모없는 태그 제거
        for script_or_style in soup(['script', 'style', 'noscript']):
            script_or_style.decompose()

        #  표를 찾아서 마크다운으로 변환 
        tables = soup.find_all('table')
        table_count = 0
        
        for table in tables:
            try:
                dfs = pd.read_html(StringIO(str(table)))
                if dfs:
                    df = dfs[0].fillna("") # 빈칸 처리
                    
                    # 데이터프레임을 마크다운 표 문자열로 변환
                    markdown_table = f"\n\n{df.to_markdown(index=False)}\n\n"
                    
                    # 기존 HTML <table> 태그 자리를 마크다운 문자열로 교체
                    table.replace_with(markdown_table)
                    table_count += 1
            except Exception:
                # 변환이 불가능한 표 무시
                pass

        # 텍스트 추출
        clean_text = soup.get_text(separator=' ', strip=True)

        return clean_text, table_count

    except Exception as e:
        print(f"파일 파싱 중 오류 발생 ({filepath}): {e}")
        return "", 0

def process_reports():
    """
    보고서를 파싱하여 텍스트로 변환하는 함수
    """
    file_pattern = os.path.join(OUTPUT_DIR, "*.[xh][mt][ml]*")
    report_files = glob.glob(file_pattern)

    if not report_files:
        print("파싱할 파일이 없음")
        return []

    print(f"{len(report_files)}개의 보고서 Table-Aware 파싱 시작\n")

    parsed_data_list = []
    total_tables_saved = 0

    for filepath in report_files:
        filename = os.path.basename(filepath)
        
        text, table_count = extract_table_aware(filepath)

        if text:
            print(f"[{filename}] 파싱 / 표: {table_count}개 (총 텍스트 길이: {len(text):,}자)")
            total_tables_saved += table_count
            
            parsed_data_list.append({
                "filename": filename,
                "text": text
            })

    print(f"\n 총 {total_tables_saved}개의 재무제표 표(Table) 데이터")
    return parsed_data_list

parsed_reports = process_reports()

with open(os.path.join(OUTPUT_DIR, "parsed_reports_table_aware.json"), "w", encoding="utf-8") as f:
    json.dump(parsed_reports, f, ensure_ascii=False, indent=2)

print("\n저장 완료")