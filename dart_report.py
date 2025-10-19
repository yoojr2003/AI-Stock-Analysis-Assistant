import requests
import zipfile
import io
import pandas as pd
from datetime import datetime
import os
import time


DART_API_KEY = ""

# 분석할 시가총액 상위 10개 기업 목록 (2025년 10월 기준)
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

# 다운로드한 보고서를 저장할 폴더 이름입니다.
# Colab에서는 '/content/dart_reports/' 경로에 폴더가 생길 거예요.
OUTPUT_DIR = "dart_reports"

# --- 핵심 기능을 하는 함수들 ---

def get_corp_codes(api_key):
    """
    DART에 등록된 모든 회사의 고유번호를 가져오는 함수예요.
    """
    csv_path = 'corp_code.csv'
    if os.path.exists(csv_path):
        print(f"기존 '{csv_path}' 파일 존재.")
        # 이 부분이 중요해요! CSV를 그냥 읽으면 '005930'이 '5930'이 될 수 있어서, 처음부터 문자로 읽어오게 처리했어요.
        df = pd.read_csv(csv_path, dtype={'stock_code': str, 'corp_code': str})
        return df

    print(f"'{csv_path}' 파일 DART에서 새로 다운")
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
        print(f"✅ '{csv_path}' 파일 저장 완료")
        return df

    except requests.exceptions.RequestException as e:
        print(f"API 요청 중에 문제 발생: {e}")
        return None
    except Exception as e:
        print(f"데이터를 처리 중 오류: {e}")
        return None


def download_annual_reports(api_key, corp_code, company_name, years=3):
    """
   최근 3년 치 사업보고서를 찾아서 다운로드하는 함수
    """
    print(f"\n[{company_name}]의 사업보고서 검색")

    current_year = datetime.now().year
    start_date = f"{current_year - years}-01-01"
    end_date = datetime.now().strftime('%Y%m%d')

    url = (f"https://opendart.fss.or.kr/api/list.json?crtfc_key={api_key}"
           f"&corp_code={corp_code}&bgn_de={start_date.replace('-', '')}"
           f"&end_de={end_date}&pblntf_ty=A&pblntf_detail_ty=A001")

    try:
        res = requests.get(url)
        res.raise_for_status()
        data = res.json()

        if data['status'] != '000':
            print(f"  - DART API에서 오류 메시지를 보냄: {data['message']}")
            return

        if not data.get('list'):
            print(f"  - 해당 기간에 올라온 사업보고서 없음")
            return

        download_count = 0
        for report in data['list']:
            if download_count >= years:
                break

            rcept_no = report['rcept_no']
            rcept_dt = report['rcept_dt']
            
            file_year = rcept_dt[:4]
            filename = f"[{company_name}]_[{file_year}년도공시]_사업보고서.html"
            filepath = os.path.join(OUTPUT_DIR, filename)

            if os.path.exists(filepath):
                print(f"  - '{filename}' 이미 존재")
                continue

            report_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
            print(f"  -  '{filename}' 다운로드 중")

            report_res = requests.get(report_url)
            report_res.raise_for_status()

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(report_res.text)
            
            download_count += 1
            time.sleep(0.5) # DART 서버 고려

    except requests.exceptions.RequestException as e:
        print(f"  - 인터넷 연결에 문제: {e}")
    except Exception as e:
        print(f"  - 예상치 못한 오류: {e}")



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
            download_annual_reports(
                api_key=DART_API_KEY,
                corp_code=company['corp_code'],
                company_name=company['corp_name_top10']
            )

        print("\n 작업 완료")

if __name__ == "__main__":
    main()

