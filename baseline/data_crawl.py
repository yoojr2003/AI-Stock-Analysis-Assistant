import requests
import zipfile
import io
import pandas as pd
from datetime import datetime
import os
import time


DART_API_KEY = ""

# 시가총액 상위 10개 기업 목록
TOP_10_COMPANIES = {
    "삼성전자": "005930",
    "SK하이닉스": "000660",
    "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940",
    "현대차": "005380",
    "LG화학": "051910",
    "기아": "000270",
    "셀트리온": "068270",
    "POSCO홀딩스": "005490",
    "NAVER": "035420"
}

OUTPUT_DIR = "/content/dart_reports"

def get_corp_codes(api_key):
    """
    DART에 등록된 회사의 고유번호를 가져오는 함수
    """
    csv_path = 'corp_code.csv'
    if os.path.exists(csv_path):
        print(f"기존 '{csv_path}' 파일 존재")
        df = pd.read_csv(csv_path, dtype={'stock_code': str, 'corp_code': str})
        return df

    print(f"'{csv_path}' 파일 새로 다운")
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={api_key}"
    try:
        res = requests.get(url)
        res.raise_for_status()

        zip_file = zipfile.ZipFile(io.BytesIO(res.content))
        xml_file = zip_file.open('CORPCODE.xml')

        df = pd.read_xml(xml_file)

        df['corp_code'] = df['corp_code'].astype(str).str.zfill(8)
        df['stock_code'] = df['stock_code'].astype(str)

        df = df.dropna(subset=['stock_code'])
        df = df[['corp_name', 'corp_code', 'stock_code']]

        df.to_csv(csv_path, index=False)
        print(f"'{csv_path}' 파일 저장 완료")
        return df

    except requests.exceptions.RequestException as e:
        print(f"API 요청 문제: {e}")
        return None
    except Exception as e:
        print(f"데이터 처리 오류: {e}")
        return None


def download_reports(api_key, corp_code, company_name, years=3):
    """
   최근 3년 치 사업보고서 원문(XML/HTML)을 다운로드하는 함수
    """
    print(f"\n[{company_name}] 사업보고서 검색")

    current_year = datetime.now().year
    start_date = f"{current_year - years}-01-01"
    end_date = datetime.now().strftime('%Y%m%d')

    list_url = (f"https://opendart.fss.or.kr/api/list.json?crtfc_key={api_key}"
                f"&corp_code={corp_code}&bgn_de={start_date.replace('-', '')}"
                f"&end_de={end_date}&pblntf_ty=A&pblntf_detail_ty=A001")

    try:
        res = requests.get(list_url)
        res.raise_for_status()
        data = res.json()

        if data.get('status') != '000':
            print(f"  - DART API에서 오류 메시지: {data.get('message')}")
            return

        if not data.get('list'):
            print(f"  - 해당 기간에 올라온 사업보고서 없음")
            return

        download_count = 0
        for report in data['list']:
            if download_count >= years:
                break

            rcept_no = report['rcept_no']
            file_year = report['rcept_dt'][:4]

            # 원문 다운로드 API URL
            document_url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={api_key}&rcept_no={rcept_no}"

            print(f"  -  [{file_year}년도] 원문 다운로드 중 (접수번호: {rcept_no})")

            doc_res = requests.get(document_url)
            doc_res.raise_for_status()

            # ZIP 파일 압축을 해제
            try:
                with zipfile.ZipFile(io.BytesIO(doc_res.content)) as zf:
                    # 압축 풀기 전 파일 목록 확인
                    for file_info in zf.infolist():
                        if file_info.filename.endswith('.xml') or file_info.filename.endswith('.html'):
                            filename = f"[{company_name}]_[{file_year}년도공시]_{file_info.filename}"
                            filepath = os.path.join(OUTPUT_DIR, filename)

                            if os.path.exists(filepath):
                                print(f"  - '{filename}' 이미 존재")
                                continue

                            # 파일 추출 및 저장
                            with zf.open(file_info) as extracted_file:
                                with open(filepath, 'wb') as f:
                                    f.write(extracted_file.read())
                            print(f"  - ✅ '{filename}' 저장 완료")
            except zipfile.BadZipFile:
                print("  - ZIP 파일 형식이 아닙니다.")

            download_count += 1
            time.sleep(1) # API 호출 제한 고려

    except requests.exceptions.RequestException as e:
        print(f"  - 인터넷 연결 문제: {e}")
    except Exception as e:
        print(f"  - 예상 못한 오류: {e}")



def main():
    if DART_API_KEY == "YOUR_DART_API_KEY_HERE" or not DART_API_KEY:
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    corp_codes_df = get_corp_codes(DART_API_KEY)

    if corp_codes_df is not None:
        top10_df = pd.DataFrame(list(TOP_10_COMPANIES.items()), columns=['corp_name', 'stock_code'])
        target_companies = pd.merge(top10_df, corp_codes_df, on='stock_code', how='left', suffixes=('_top10', ''))

        if target_companies['corp_code'].isnull().any():
            missing = target_companies[target_companies['corp_code'].isnull()]
            print("\nDART 고유번호 오류. 종목코드가 맞는지 확인")
            for _, row in missing.iterrows():
                print(f"  - {row['corp_name_top10']} ({row['stock_code']})")

        for _, company in target_companies.dropna(subset=['corp_code']).iterrows():
            download_reports(
                api_key=DART_API_KEY,
                corp_code=company['corp_code'],
                company_name=company['corp_name_top10']
            )

        print("\n 완료")

if __name__ == "__main__":
    main()
