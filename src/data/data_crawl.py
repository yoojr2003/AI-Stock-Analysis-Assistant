"""
data_crawl_v3.py — 10개 기업 × 2.5년치 다운로드 (수정판)

수정 사항 (v2 → v3):
  1. DART API의 pblntf_detail_ty 파라미터가 정확히 작동 안 함
     → 모든 보고서를 한 번에 가져오고, report_nm 필드로 직접 판별
  2. 회계연도 계산 정확화:
     - 사업보고서 (3월 제출) → 전년도
     - 반기보고서 (8월 제출) → 같은 해
     - 1Q (5월 제출) → 같은 해
     - 3Q (11월 제출) → 같은 해
  3. 중복 다운로드 방지 강화 (rcept_no 기준)

XBRL 본문 의무화 시점:
  bgn_de = 2023-11-01 (2023.3Q 보고서 제출 직전부터)
"""

import os
import re
import time
import zipfile
import io
import requests
import pandas as pd
from datetime import datetime


DART_API_KEY = os.environ.get("DART_API_KEY", "")

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
    "NAVER": "035420",
}

XBRL_START_DATE = "20231101"  # 2023.3Q 보고서 제출 직전
OUTPUT_DIR = "/content/dart_reports"


def get_corp_codes(api_key):
    csv_path = "corp_code.csv"
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path, dtype={"stock_code": str, "corp_code": str})
        return df

    print("corp_code.csv 새로 다운로드")
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={api_key}"
    res = requests.get(url)
    res.raise_for_status()
    
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    xml_file = zf.open("CORPCODE.xml")
    df = pd.read_xml(xml_file)
    df["corp_code"] = df["corp_code"].astype(str).str.zfill(8)
    df["stock_code"] = df["stock_code"].astype(str)
    df = df.dropna(subset=["stock_code"])
    df = df[["corp_name", "corp_code", "stock_code"]]
    df.to_csv(csv_path, index=False)
    return df


def classify_report(report_nm: str) -> tuple[str, str]:
    """
    report_nm으로 보고서 유형 정확히 판별.
    
    Returns:
        (type_code, type_label): ("A001", "사업"), ("A002", "반기"), ("A003", "분기"), ("Other", "기타")
    """
    if not report_nm:
        return ("Other", "기타")
    
    if "사업보고서" in report_nm:
        return ("A001", "사업")
    if "반기보고서" in report_nm:
        return ("A002", "반기")
    if "분기보고서" in report_nm:
        return ("A003", "분기")
    return ("Other", "기타")


def get_fiscal_period(report_nm: str, rcept_dt: str) -> tuple[int, str]:
    """
    보고서명과 제출일로 회계연도 + 분기 추정.
    
    예시:
      "사업보고서 (2024.12)" 제출일 2025.03.11 → (2024, "FY")
      "분기보고서 (2024.09)" 제출일 2024.11.14 → (2024, "3Q")
      "반기보고서 (2024.06)" 제출일 2024.08.14 → (2024, "HY")
      "분기보고서 (2024.03)" 제출일 2024.05.16 → (2024, "1Q")
    
    1차: report_nm에서 (YYYY.MM) 패턴 추출 → 가장 정확
    2차: 제출일 + 보고서 유형으로 fallback
    """
    type_code, type_label = classify_report(report_nm)
    
    # 1차: report_nm에서 직접 추출 — "사업보고서 (2024.12)" 형태
    match = re.search(r'\((\d{4})\.(\d{2})\)', report_nm)
    if match:
        fiscal_year = int(match.group(1))
        month = int(match.group(2))
        if month == 12:
            scope = "FY"
        elif month == 9:
            scope = "3Q"
        elif month == 6:
            scope = "HY"
        elif month == 3:
            scope = "1Q"
        else:
            scope = f"{month:02d}"
        return (fiscal_year, scope)
    
    # 2차: 제출일 기반 fallback
    rcept_year = int(rcept_dt[:4])
    rcept_month = int(rcept_dt[4:6])
    
    if type_code == "A001":  # 사업보고서, 보통 3월 제출 → 전년도 12월
        fiscal_year = rcept_year - 1 if rcept_month <= 4 else rcept_year
        return (fiscal_year, "FY")
    elif type_code == "A002":  # 반기, 8월 제출 → 같은 해 6월
        return (rcept_year, "HY")
    elif type_code == "A003":  # 분기, 5월 또는 11월 제출
        if rcept_month <= 6:
            return (rcept_year, "1Q")
        else:
            return (rcept_year, "3Q")
    
    return (rcept_year, "?")


def download_reports(api_key: str, corp_code: str, company_name: str):
    """
    회사별 사업/반기/분기 보고서 한 번에 검색 후 report_nm으로 분류.
    """
    print(f"\n[{company_name}] 보고서 검색 (제출일 ≥ {XBRL_START_DATE})")
    
    end_date = datetime.now().strftime("%Y%m%d")
    
    # pblntf_detail_ty 없이 정기공시만 (pblntf_ty=A) 한 번에 가져오기
    list_url = (
        f"https://opendart.fss.or.kr/api/list.json?crtfc_key={api_key}"
        f"&corp_code={corp_code}"
        f"&bgn_de={XBRL_START_DATE}"
        f"&end_de={end_date}"
        f"&pblntf_ty=A"
        f"&page_count=100"
    )
    
    try:
        res = requests.get(list_url)
        res.raise_for_status()
        data = res.json()
        
        if data.get("status") != "000":
            msg = data.get("message", "unknown")
            if data.get("status") != "013":
                print(f"  - API 에러: {msg}")
            return 0
        
        reports = data.get("list", [])
        
        # 사업/반기/분기 보고서만 필터
        target_reports = []
        for r in reports:
            nm = r.get("report_nm", "")
            type_code, type_label = classify_report(nm)
            if type_code in ("A001", "A002", "A003"):
                target_reports.append((r, type_code, type_label, nm))
        
        print(f"  발견된 정기보고서: {len(target_reports)}개")
        
        # 유형별 카운트
        from collections import Counter
        type_count = Counter([t[2] for t in target_reports])
        for label, cnt in type_count.items():
            print(f"    - {label}보고서: {cnt}개")
        
        # 다운로드
        total_count = 0
        seen_rcept = set()  # 같은 rcept_no 중복 방지
        
        for report, type_code, type_label, report_nm in target_reports:
            rcept_no = report["rcept_no"]
            if rcept_no in seen_rcept:
                continue
            seen_rcept.add(rcept_no)
            
            rcept_dt = report["rcept_dt"]
            fiscal_year, fiscal_scope = get_fiscal_period(report_nm, rcept_dt)
            
            # 다운로드 URL
            doc_url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={api_key}&rcept_no={rcept_no}"
            
            try:
                doc_res = requests.get(doc_url)
                doc_res.raise_for_status()
                
                with zipfile.ZipFile(io.BytesIO(doc_res.content)) as zf:
                    for fi in zf.infolist():
                        if not (fi.filename.endswith(".xml") or fi.filename.endswith(".html")):
                            continue
                        
                        # 파일명: [기업]_[YYYY년도공시(SCOPE)]_원본파일명
                        filename = f"[{company_name}]_[{fiscal_year}년도공시]_{fi.filename}"
                        filepath = os.path.join(OUTPUT_DIR, filename)
                        
                        if os.path.exists(filepath):
                            continue
                        
                        with zf.open(fi) as src:
                            with open(filepath, "wb") as f:
                                f.write(src.read())
                        total_count += 1
                        print(f"    ✅ {fiscal_year}.{fiscal_scope:3} ({type_label}) {fi.filename}")
            
            except zipfile.BadZipFile:
                print(f"    ⚠️ ZIP 오류 (rcept={rcept_no})")
            except Exception as e:
                print(f"    ⚠️ 오류 (rcept={rcept_no}): {e}")
            
            time.sleep(0.5)  # rate limit
        
        print(f"  ▶ 총 {total_count}개 파일 ({len(seen_rcept)}개 보고서)")
        return total_count
    
    except Exception as e:
        print(f"  - 오류: {e}")
        return 0


def main():
    if not DART_API_KEY:
        print("❌ DART_API_KEY 미설정")
        return
    
    # 기존 파일 정리 (v2의 잘못된 라벨 파일 제거)
    if os.path.exists(OUTPUT_DIR):
        # 안전장치: 백업 후 비우기
        existing = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".xml") or f.endswith(".html")]
        if existing:
            backup = f"{OUTPUT_DIR}_v2_backup_{int(time.time())}"
            os.rename(OUTPUT_DIR, backup)
            print(f"기존 파일 → {backup}")
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("=" * 60)
    print("  DART 공시 다운로드 v3 (보고서 유형 정확 판별)")
    print("=" * 60)
    print(f"  대상: {len(TOP_10_COMPANIES)}개 기업")
    print(f"  기간: 제출일 ≥ {XBRL_START_DATE}")
    print(f"  저장: {OUTPUT_DIR}")
    print(f"  API key: {DART_API_KEY[:4]}...{DART_API_KEY[-4:]}")
    print("=" * 60)
    
    corp_codes_df = get_corp_codes(DART_API_KEY)
    top10_df = pd.DataFrame(
        list(TOP_10_COMPANIES.items()),
        columns=["corp_name_top", "stock_code"]
    )
    target = pd.merge(top10_df, corp_codes_df, on="stock_code", how="left")
    
    grand_total = 0
    for _, company in target.dropna(subset=["corp_code"]).iterrows():
        cnt = download_reports(
            api_key=DART_API_KEY,
            corp_code=company["corp_code"],
            company_name=company["corp_name_top"],
        )
        grand_total += cnt
    
    print("\n" + "=" * 60)
    print(f"  ✅ 총 {grand_total}개 파일 다운로드")
    print("=" * 60)


if __name__ == "__main__":
    main()
