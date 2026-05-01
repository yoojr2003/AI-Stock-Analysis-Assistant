"""
공통 유틸리티: 파일명 파서, 재무제표 종류 판별 등

DART 파일명 예:
  [삼성전자]_[2025년도공시]_0001.xml
  [SK하이닉스]_[2024년도공시]_report.html
"""

import re
from typing import Optional
from dataclasses import dataclass


# 시가총액 상위 10개 기업
KNOWN_CORPS = {
    "삼성전자", "SK하이닉스", "LG에너지솔루션", "삼성바이오로직스",
    "현대차", "LG화학", "기아", "셀트리온", "POSCO홀딩스", "NAVER",
}

# 사업보고서 / 분기보고서 / 반기보고서 구분용 키워드
QUARTERLY_HINTS = {
    "3분기": 3, "분기보고서": None,  # 분기보고서는 별도 판단 필요
    "반기": 2, "반기보고서": 2,
    "사업보고서": 4,  # 연간
}

# 연결/별도 재무제표 구분 키워드
REPORT_TYPE_PATTERNS = [
    (re.compile(r"연결재무제표|연결\s*재무|연결포괄손익|연결재무상태표|연결손익계산서|연결현금흐름표"), "연결"),
    (re.compile(r"별도재무제표|별도\s*재무|재무제표(?!\s*주석)"), "별도"),
]

# 재무제표 종류 구분
STATEMENT_TYPE_PATTERNS = [
    (re.compile(r"재무상태표|대차대조표"), "재무상태표"),
    (re.compile(r"손익계산서|포괄손익계산서"), "손익계산서"),
    (re.compile(r"현금흐름표"), "현금흐름표"),
    (re.compile(r"자본변동표"), "자본변동표"),
]


@dataclass
class FileMetadata:
    """DART 파일명에서 추출된 메타데이터"""
    source_file: str
    corp_name: Optional[str]
    year: Optional[int]

    def as_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "corp_name": self.corp_name,
            "year": self.year,
        }


def parse_filename(filename: str) -> FileMetadata:
    """
    DART 파일명에서 메타데이터 추출
    
    예: "[삼성전자]_[2025년도공시]_report.xml" 
       → corp_name="삼성전자", year=2025
    """
    corp_name = None
    year = None

    # 기업명 매칭: 알려진 기업명 중 파일명에 포함된 것을 찾음
    for known in KNOWN_CORPS:
        if known in filename:
            corp_name = known
            break
    # 폴백: 대괄호 또는 언더스코어로 둘러싼 첫 블록
    if corp_name is None:
        corp_match = re.search(r"[\[_]([가-힣A-Za-z0-9]+)[\]_]", filename)
        if corp_match:
            corp_name = corp_match.group(1).strip()

    # 연도
    year_match = re.search(r"(\d{4})년도공시", filename)
    if year_match:
        year = int(year_match.group(1))
    else:
        # 폴백
        year_match = re.search(r"20\d{2}", filename)
        if year_match:
            year = int(year_match.group(0))

    return FileMetadata(source_file=filename, corp_name=corp_name, year=year)


def infer_report_type(section_path: list[str]) -> Optional[str]:
    """
    섹션 경로를 보고 '연결' / '별도' 중 어느 재무제표인지 판별
    """
    joined = " ".join(section_path)
    for pattern, label in REPORT_TYPE_PATTERNS:
        if pattern.search(joined):
            return label
    return None


def infer_statement_type(section_path: list[str], table_caption: str = "") -> Optional[str]:
    """
    섹션 경로 + 표 캡션을 보고 재무제표 종류 판별
    """
    haystack = " ".join(section_path) + " " + table_caption
    for pattern, label in STATEMENT_TYPE_PATTERNS:
        if pattern.search(haystack):
            return label
    return None


def infer_quarter_from_text(text_near_table: str) -> Optional[int]:
    """
    표 주변 텍스트(또는 보고서 제목)에서 분기 정보 추출
    """
    m = re.search(r"([1-4])\s*분기", text_near_table)
    if m:
        return int(m.group(1))
    m = re.search(r"([1-4])Q|Q([1-4])", text_near_table, re.IGNORECASE)
    if m:
        return int(m.group(1) or m.group(2))
    if "반기" in text_near_table:
        return 2
    return None


def infer_period_end_date(text_near_table: str) -> Optional[str]:
    """
    날짜 표현을 정규화
    """
    # YYYY년 MM월 DD일
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text_near_table)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # YYYY-MM-DD 또는 YYYY.MM.DD
    m = re.search(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", text_near_table)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


def make_table_id(corp_name: str, year: int, quarter: Optional[int], table_idx: int) -> str:
    """고유 ID 생성"""
    q_part = f"Q{quarter}" if quarter else "Y"
    corp_slug = (corp_name or "unknown").replace(" ", "_")
    return f"{corp_slug}_{year}{q_part}_t{table_idx:04d}"


def make_narrative_id(corp_name: str, year: int, quarter: Optional[int], para_idx: int) -> str:
    """텍스트 청크 고유 ID"""
    q_part = f"Q{quarter}" if quarter else "Y"
    corp_slug = (corp_name or "unknown").replace(" ", "_")
    return f"{corp_slug}_{year}{q_part}_n{para_idx:04d}"


# ==========================================
# 단위 힌트 추출
# ==========================================
UNIT_PATTERNS = [
    (re.compile(r"단위\s*[:：]\s*백만\s*원"), "백만원"),
    (re.compile(r"단위\s*[:：]\s*천\s*원"), "천원"),
    (re.compile(r"단위\s*[:：]\s*억\s*원"), "억원"),
    (re.compile(r"단위\s*[:：]\s*원\b"), "원"),
    (re.compile(r"\(\s*백만\s*원\s*\)"), "백만원"),
    (re.compile(r"\(\s*천\s*원\s*\)"), "천원"),
]


def infer_unit_hint(text_near_table: str) -> Optional[str]:
    """표 주변 텍스트에서 단위 표기 추출"""
    for pattern, label in UNIT_PATTERNS:
        if pattern.search(text_near_table):
            return label
    return None


if __name__ == "__main__":
    # 테스트
    test_names = [
        "[삼성전자]_[2025년도공시]_report.xml",
        "[SK하이닉스]_[2024년도공시]_doc.html",
        "[LG에너지솔루션]_[2023년도공시]_file.xml",
    ]
    for name in test_names:
        meta = parse_filename(name)
        print(f"{name}")
        print(f"  → corp={meta.corp_name}, year={meta.year}")

    test_sections = [
        ["제2부. 재무에 관한 사항", "2. 연결재무제표", "(1) 연결재무상태표"],
        ["제2부. 재무에 관한 사항", "3. 재무제표", "(2) 손익계산서"],
        ["제1부. 회사의 개요", "2. 회사의 연혁"],
    ]
    for sp in test_sections:
        print(f"\n섹션: {' > '.join(sp)}")
        print(f"  report_type = {infer_report_type(sp)}")
        print(f"  statement_type = {infer_statement_type(sp)}")

    test_unit_texts = [
        "(단위 : 백만원)",
        "단위: 천원",
        "일반 문장에는 단위 없음",
    ]
    for t in test_unit_texts:
        print(f"\n텍스트: {t!r}")
        print(f"  unit = {infer_unit_hint(t)}")
