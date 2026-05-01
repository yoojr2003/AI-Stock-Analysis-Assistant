"""
preprocessor_v2.py — DART XML 전처리기

입력: DART 원본 XML 파일 (dart4.xsd 기반)
출력:
  - facts.jsonl  : XBRL 태그 기반 정형 재무 데이터 (한 행 = 한 셀)
  - sections.jsonl : 섹션 트리 기반 내러티브 텍스트 (한 행 = 한 섹션)
  - tables.jsonl : 마크다운 변환된 표 (백업/검증용)

핵심 아이디어:
  DART XML은 dart4.xsd 스키마를 따르며, XBRL 태그가 각 셀마다 박혀 있다.
  단순 HTML 파싱으로 텍스트만 뽑는 게 아니라, 구조적 정보를 보존한다.

XBRL 분류 코드:
  BS_C / BS_S   = 재무상태표 (연결/별도)
  IS_C* / IS_S* = 포괄손익계산서 (연결/별도) — 1=누적, 2/3=당분기만
  CF_C / CF_S   = 현금흐름표
  EF_C / EF_S   = 자본변동표
  NT_C_* / NT_S_* = 재무제표 주석
"""

from __future__ import annotations

import json
import re
import os
import glob
from dataclasses import dataclass, field, asdict
from typing import Optional, Iterator
from pathlib import Path

from lxml import etree

from utils import (
    parse_filename,
    infer_report_type,
    infer_statement_type,
    infer_unit_hint,
    make_table_id,
    make_narrative_id,
)


# ==========================================
# 상수 정의
# ==========================================

XBRL_STATEMENT_MAP = {
    "BS_C": ("재무상태표", "연결"),
    "BS_S": ("재무상태표", "별도"),
    "IS_C1": ("포괄손익계산서", "연결"),
    "IS_C2": ("포괄손익계산서", "연결"),
    "IS_C3": ("포괄손익계산서", "연결"),
    "IS_S1": ("포괄손익계산서", "별도"),
    "IS_S2": ("포괄손익계산서", "별도"),
    "IS_S3": ("포괄손익계산서", "별도"),
    "CF_C":  ("현금흐름표", "연결"),
    "CF_S":  ("현금흐름표", "별도"),
    "EF_C":  ("자본변동표", "연결"),
    "EF_S":  ("자본변동표", "별도"),
}

# ACONTEXT 파싱용 정규식
# 예: "CFY2025eHYA_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_..."
#     "CFY2025dHYA_..." (d=during, 기간 데이터), "CFY2025eHY_..." (e=end, 시점 데이터)
# C=Current, P=Prior / FY=Fiscal Year / eHY=end of Half Year / dHY=during Half Year
# e3Q=end of 3Q / d3Q=during 3Q (누적) / d3QA=3Q 누적 / d3QQ=3Q 3개월치만
CONTEXT_PERIOD_RE = re.compile(
    r"^(?P<cp>[CP])FY(?P<year>\d{4})(?P<suffix>[edaA-Z0-9]+?)(?:_|$)"
)

# 텍스트에서 분기/반기 감지
PERIOD_TEXT_PATTERNS = [
    (re.compile(r"반기말"), "HY_END"),
    (re.compile(r"반기"), "HY"),
    (re.compile(r"3\s*분기말"), "3Q_END"),
    (re.compile(r"3\s*분기"), "3Q_CUM"),
    (re.compile(r"1\s*분기말"), "1Q_END"),
    (re.compile(r"1\s*분기"), "1Q_CUM"),
    (re.compile(r"기말"), "FY_END"),
]


# ==========================================
# 데이터 클래스
# ==========================================

@dataclass
class XBRLFact:
    """XBRL 태그가 붙은 정형 재무 데이터 한 셀"""
    fact_id: str                 # 고유 식별자
    corp_name: str
    fiscal_year: int
    source_file: str
    # 구조 정보
    statement: str               # "재무상태표" / "포괄손익계산서" / ...
    report_type: str             # "연결" / "별도"
    xbrl_class: str              # 원본 BS_C, IS_C1 등
    statement_title: str         # "2-1. 연결 재무상태표"
    # 계정 정보
    account_code: str            # ifrs-full_CurrentAssets
    account_kr: str              # 유동자산 (한글)
    # 기간 정보
    context_raw: str             # 원본 ACONTEXT 값
    period_tag: str              # 현재기간: CFY2025eHY / PFY2024eHY 등
    is_current_period: bool      # 당기 여부
    # 값
    value: Optional[float]       # 숫자값
    value_raw: str               # 원본 문자열 (콤마 포함)
    unit_hint: Optional[str]     # "원" / "백만원" 등

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TableRecord:
    """표 전체 (마크다운 + 메타데이터). 백업/검증/RAG 폴백용"""
    table_id: str
    corp_name: str
    fiscal_year: int
    source_file: str
    statement: Optional[str]
    report_type: Optional[str]
    xbrl_class: Optional[str]
    statement_title: str
    section_path: list[str]
    unit_hint: Optional[str]
    markdown: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NarrativeSection:
    """섹션 기반 내러티브 텍스트. RAG용"""
    section_id: str
    corp_name: str
    fiscal_year: int
    source_file: str
    section_path: list[str]
    text: str
    char_count: int

    def to_dict(self) -> dict:
        return asdict(self)


# ==========================================
# XML 파서 (lxml)
# ==========================================

def iter_elements(root: etree._Element, tag: str):
    """모든 하위 요소 중 특정 태그만 순회"""
    return root.iter(tag)


def get_text(el: etree._Element) -> str:
    """요소 내부 모든 텍스트를 재귀적으로 결합, 공백 정리"""
    if el is None:
        return ""
    text = " ".join(el.itertext())
    text = re.sub(r"\s+", " ", text).strip()
    # DART 문서에 종종 나오는 U+3000 (ideographic space)도 제거
    text = text.replace("\u3000", " ").strip()
    return text


def parse_value(raw: str) -> Optional[float]:
    """
    '9,933,739,423,065' → 9933739423065.0
    '(58,414,936)' → -58414936.0  (회계식 괄호 음수)
    빈 값이나 파싱 실패 시 None
    """
    if not raw:
        return None
    s = raw.strip().replace(",", "").replace(" ", "")
    if not s or s in {"-", "-　", "　"}:
        return None
    is_neg = False
    if s.startswith("(") and s.endswith(")"):
        is_neg = True
        s = s[1:-1]
    if s.startswith("-"):
        is_neg = not is_neg
        s = s[1:]
    try:
        v = float(s)
        return -v if is_neg else v
    except ValueError:
        return None


def classify_period(context_raw: str, near_text: str = "") -> tuple[str, bool]:
    """
    ACONTEXT 값에서 기간 태그 추출
    """
    m = CONTEXT_PERIOD_RE.match(context_raw or "")
    if m:
        cp = m.group("cp")
        year = m.group("year")
        suffix = m.group("suffix")
        tag = f"{cp}FY{year}{suffix}"
        return tag, (cp == "C")
    # 폴백: 주변 텍스트에서 추정
    for pattern, label in PERIOD_TEXT_PATTERNS:
        if pattern.search(near_text):
            return f"UNK_{label}", True
    return "UNKNOWN", True


def extract_statement_title_date(table_group: etree._Element) -> str:
    """TABLE-GROUP 내부에서 기간 텍스트 추출"""
    date_texts = []
    for p in table_group.iter("P"):
        t = get_text(p)
        if re.search(r"\d{4}[\.\-]\d{2}[\.\-]\d{2}|제\s*\d+\s*기", t):
            date_texts.append(t)
    return " | ".join(date_texts[:3])


def extract_unit_from_table_group(table_group: etree._Element) -> Optional[str]:
    """
    TABLE-GROUP 내부 어디든 '(단위 : 원)' 같은 표기 찾아 반환
    """
    for p in table_group.iter("P"):
        t = get_text(p)
        unit = infer_unit_hint(t)
        if unit:
            return unit
    # TE/TD 태그 확인
    for cell in table_group.iter():
        if cell.tag in {"TE", "TD", "TU"}:
            t = get_text(cell)
            unit = infer_unit_hint(t)
            if unit:
                return unit
    return None


# ==========================================
# 섹션 경로 추적
# ==========================================

class SectionTracker:
    """
    DOM을 순회하면서 현재 섹션 경로를 유지
    """

    def __init__(self):
        self.stack: list[tuple[int, str]] = []  # (level, title)

    def enter_section(self, level: int, title: str):
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        self.stack.append((level, title))

    def current_path(self) -> list[str]:
        return [t for _, t in self.stack]


# ==========================================
# 메인 파서
# ==========================================

def parse_dart_xml(filepath: str) -> dict:
    """
    DART XML 파일 하나를 파싱해서 facts, tables, sections 리스트 반환
    """
    filename = os.path.basename(filepath)
    meta = parse_filename(filename)
    corp_name = meta.corp_name or "UNKNOWN"
    fiscal_year = meta.year or 0

    # lxml로 파싱
    parser = etree.XMLParser(recover=True, encoding="utf-8")
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
        root = etree.fromstring(raw, parser=parser)
    except Exception as e:
        print(f"[ERROR] {filename}: XML 파싱 실패 - {e}")
        return {"facts": [], "tables": [], "sections": []}

    if root is None:
        return {"facts": [], "tables": [], "sections": []}

    # 보고서 종류 (반기/사업/분기)
    doc_name_el = root.find(".//DOCUMENT-NAME")
    report_doc_type = get_text(doc_name_el) if doc_name_el is not None else ""

    company_el = root.find(".//COMPANY-NAME")
    if company_el is not None:
        xml_corp = get_text(company_el)

    facts: list[XBRLFact] = []
    tables: list[TableRecord] = []
    sections: list[NarrativeSection] = []

    # ==========================================
    # 1: XBRL 팩트 추출
    # ==========================================
    table_group_idx = 0
    for tg in root.iter("TABLE-GROUP"):
        aclass = tg.get("ACLASS", "")
        # XBRL 코드 추출: "{XBRL}BS_C" → "BS_C"
        m = re.match(r"\{XBRL\}([A-Z0-9_]+)", aclass)
        if not m:
            continue
        xbrl_code = m.group(1)

        # 주요 재무제표만 팩트 DB에
        if xbrl_code not in XBRL_STATEMENT_MAP:
            continue

        statement, report_type = XBRL_STATEMENT_MAP[xbrl_code]

        # TABLE-GROUP의 제목
        title_el = tg.find("TITLE")
        statement_title = get_text(title_el) if title_el is not None else ""

        # 기간 정보
        period_info = extract_statement_title_date(tg)

        # 단위 힌트
        unit_hint_value = extract_unit_from_table_group(tg)

        # 이 TABLE-GROUP 내부의 모든 TE 셀 순회
        # TE에 ACODE가 있으면 XBRL 태그된 셀
        current_account_kr = ""
        current_account_code = ""

        for row in tg.iter("TR"):
            # 각 행에서 "계정명" 셀(텍스트) + "값" 셀들(숫자)을 쌍으로 찾기
            row_cells = list(row.iter("TE"))
            if not row_cells:
                row_cells = list(row.iter("TD"))

            if not row_cells:
                continue

            first_cell = row_cells[0]
            account_kr = get_text(first_cell)
            if not account_kr or account_kr in {"　", ""}:
                continue

            # 나머지 셀에서 숫자값 추출
            for idx, cell in enumerate(row_cells[1:], start=1):
                acode = cell.get("ACODE", "")
                acontext = cell.get("ACONTEXT", "")
                raw_val = get_text(cell)

                # ACODE가 없는 셀은 XBRL 팩트가 아님
                if not acode:
                    continue

                # 숫자 파싱
                value = parse_value(raw_val)
                if value is None:
                    continue

                # 기간 분류
                period_tag, is_current = classify_period(acontext, period_info)

                fact_id = f"{corp_name}_{fiscal_year}_{xbrl_code}_{acode}_{period_tag}_{table_group_idx}_{idx}"
                fact = XBRLFact(
                    fact_id=fact_id,
                    corp_name=corp_name,
                    fiscal_year=fiscal_year,
                    source_file=filename,
                    statement=statement,
                    report_type=report_type,
                    xbrl_class=xbrl_code,
                    statement_title=statement_title,
                    account_code=acode,
                    account_kr=account_kr,
                    context_raw=acontext,
                    period_tag=period_tag,
                    is_current_period=is_current,
                    value=value,
                    value_raw=raw_val,
                    unit_hint=unit_hint_value,
                )
                facts.append(fact)

        table_group_idx += 1

    # ==========================================
    # 2: 주요 표를 마크다운으로도 보존
    # ==========================================
    table_group_idx = 0
    for tg in root.iter("TABLE-GROUP"):
        aclass = tg.get("ACLASS", "")
        m = re.match(r"\{XBRL\}([A-Z0-9_]+)", aclass)
        xbrl_code = m.group(1) if m else None

        # 주요 재무제표 + 주요 주석(NT_C_D8xxxxx)백업
        keep_as_table = False
        if xbrl_code in XBRL_STATEMENT_MAP:
            keep_as_table = True
        elif xbrl_code and xbrl_code.startswith("NT_"):
            keep_as_table = True

        if not keep_as_table:
            continue

        statement, report_type = XBRL_STATEMENT_MAP.get(xbrl_code, (None, None))
        title_el = tg.find("TITLE")
        statement_title = get_text(title_el) if title_el is not None else ""
        period_info = extract_statement_title_date(tg)
        unit_hint_value = extract_unit_from_table_group(tg)

        md_rows = table_group_to_markdown(tg)
        if not md_rows.strip():
            continue

        tbl = TableRecord(
            table_id=make_table_id(corp_name, fiscal_year, None, table_group_idx),
            corp_name=corp_name,
            fiscal_year=fiscal_year,
            source_file=filename,
            statement=statement,
            report_type=report_type,
            xbrl_class=xbrl_code,
            statement_title=statement_title,
            section_path=[statement_title] if statement_title else [],
            unit_hint=unit_hint_value,
            markdown=md_rows,
        )
        tables.append(tbl)
        table_group_idx += 1

    # ==========================================
    # 3: 내러티브 섹션 텍스트 추출
    # ==========================================
    tracker = SectionTracker()
    section_text_buffer: list[str] = []
    current_section_path: list[str] = []
    section_idx = 0

    # DART XML의 SECTION-1 / SECTION-2 / SECTION-3 순회
    # 재무제표 TABLE-GROUP 내부는 이미 팩트로 추출했으니 제외
    def in_xbrl_statement(el) -> bool:
        """주요 재무제표 TABLE-GROUP 내부 요소인지 확인."""
        parent = el.getparent()
        while parent is not None:
            if parent.tag == "TABLE-GROUP":
                aclass = parent.get("ACLASS", "")
                m2 = re.match(r"\{XBRL\}([A-Z0-9_]+)", aclass)
                if m2 and m2.group(1) in XBRL_STATEMENT_MAP:
                    return True
            parent = parent.getparent()
        return False

    def is_financial_notes_section(section_path: list[str]) -> bool:
        """
        재무제표·주석 관련 섹션인지 판별. 해당 섹션은 숫자 텍스트가 대부분이라
        내러티브 RAG에 부적합하므로 제외
        (재무 수치 질문은 XBRL 팩트 DB로 이미 처리됨)
        
        주의: "III. 재무에 관한 사항" 전체를 막으면 안 됨.
        그 하위에는 '배당에 관한 사항', '증권 발행', '기타 재무' 등
        중요한 narrative 섹션이 있기 때문에 이들은 RAG에 포함
        """
        path_joined = " ".join(section_path)
        
        # 가장 마지막 섹션 제목 기준으로 판단
        leaf = section_path[-1] if section_path else ""
        
        # 명확한 재무제표/주석 계열만 제외
        # - "재무제표", "재무상태표" 등 표 명칭
        # - "재무제표 주석", "연결재무제표 주석" 등 주석
        # - "요약재무정보" (짧지만 숫자 중심)
        block_leaf_keywords = [
            "재무제표",            # "재무제표", "연결재무제표", "재무제표 주석", "연결재무제표 주석" 모두 포함
            "요약재무정보",
            "재무상태표", "손익계산서", "포괄손익계산서",
            "현금흐름표", "자본변동표",
            "감사의견", "감사보고서", "외부감사",
        ]
        for kw in block_leaf_keywords:
            if kw in leaf:
                return True
        
        # 보존 대상:
        #   - "배당에 관한 사항"
        #   - "증권의 발행"
        #   - "기타 재무에 관한 사항"
        #   → narrative라 RAG에서 검색 가능하게
        # 별도 처리 없이 위 block_leaf_keywords에 매칭 안 되면 자동 통과
        return False

    def flush_section():
        """현재 섹션 버퍼를 NarrativeSection으로 저장"""
        nonlocal section_idx
        text = " ".join(section_text_buffer).strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) < 100:  # 너무 짧으면 스킵
            section_text_buffer.clear()
            return
        # 재무제표/주석 섹션은 RAG에서 제외
        if is_financial_notes_section(current_section_path):
            section_text_buffer.clear()
            return
        sec = NarrativeSection(
            section_id=make_narrative_id(corp_name, fiscal_year, None, section_idx),
            corp_name=corp_name,
            fiscal_year=fiscal_year,
            source_file=filename,
            section_path=current_section_path.copy(),
            text=text,
            char_count=len(text),
        )
        sections.append(sec)
        section_idx += 1
        section_text_buffer.clear()

    # DOM 순회
    body = root.find(".//BODY")
    if body is not None:
        for event, el in etree.iterwalk(body, events=("start",)):
            tag = el.tag
            # 섹션 진입
            if tag in {"SECTION-1", "SECTION-2", "SECTION-3"}:
                flush_section()
                level = int(tag.split("-")[1])
                # TITLE 찾기 (direct child)
                title_el = el.find("TITLE")
                title = get_text(title_el) if title_el is not None else ""
                tracker.enter_section(level, title)
                current_section_path = tracker.current_path()
            elif tag == "TITLE":
                pass
            elif tag == "P" and not in_xbrl_statement(el):
                text = get_text(el)
                if text:
                    section_text_buffer.append(text)

    # 마지막 섹션 flush
    flush_section()

    return {
        "facts": [f.to_dict() for f in facts],
        "tables": [t.to_dict() for t in tables],
        "sections": [s.to_dict() for s in sections],
        "meta": {
            "filename": filename,
            "corp_name": corp_name,
            "fiscal_year": fiscal_year,
            "report_doc_type": report_doc_type,
            "num_facts": len(facts),
            "num_tables": len(tables),
            "num_sections": len(sections),
        }
    }


# ==========================================
# 표 → 마크다운 변환
# ==========================================

def table_group_to_markdown(tg: etree._Element) -> str:
    """TABLE-GROUP 내의 모든 TABLE을 마크다운으로 변환"""
    md_parts = []
    for tbl in tg.iter("TABLE"):
        rows = []
        for tr in tbl.iter("TR"):
            cells = []
            for cell in tr:
                if cell.tag in {"TH", "TD", "TE", "TU"}:
                    t = get_text(cell)
                    # 파이프는 이스케이프
                    t = t.replace("|", "\\|").replace("\n", " ")
                    cells.append(t if t else " ")
            if cells:
                rows.append(cells)
        if not rows:
            continue
        # 열 개수 정규화
        max_cols = max(len(r) for r in rows)
        normalized = [r + [" "] * (max_cols - len(r)) for r in rows]
        # 첫 행을 헤더
        header = "| " + " | ".join(normalized[0]) + " |"
        sep = "| " + " | ".join(["---"] * max_cols) + " |"
        body_rows = ["| " + " | ".join(r) + " |" for r in normalized[1:]]
        md_parts.append("\n".join([header, sep] + body_rows))
    return "\n\n".join(md_parts)


# ==========================================
# 배치 처리 + JSONL 저장
# ==========================================

def write_jsonl(items: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def process_directory(input_dir: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)

    all_facts: list[dict] = []
    all_tables: list[dict] = []
    all_sections: list[dict] = []
    manifest = []

    patterns = ["*.xml", "*.XML", "*.html", "*.HTML"]
    files = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(input_dir, pat)))

    if not files:
        print(f"입력 디렉토리에 파일 없음: {input_dir}")
        return

    print(f"{len(files)}개 파일 처리 시작\n")
    for fp in files:
        fn = os.path.basename(fp)
        print(f"[{fn}] 처리 중")
        result = parse_dart_xml(fp)
        all_facts.extend(result["facts"])
        all_tables.extend(result["tables"])
        all_sections.extend(result["sections"])
        manifest.append(result["meta"])
        print(f"  → 팩트 {result['meta']['num_facts']}개 / "
              f"표 {result['meta']['num_tables']}개 / "
              f"섹션 {result['meta']['num_sections']}개\n")

    write_jsonl(all_facts, os.path.join(output_dir, "facts.jsonl"))
    write_jsonl(all_tables, os.path.join(output_dir, "tables.jsonl"))
    write_jsonl(all_sections, os.path.join(output_dir, "sections.jsonl"))
    with open(os.path.join(output_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("=" * 50)
    print(f"전체: 팩트 {len(all_facts)}개 / 표 {len(all_tables)}개 / 섹션 {len(all_sections)}개")
    print(f"저장 경로: {output_dir}")


if __name__ == "__main__":
    import sys
    input_dir = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./processed"
    process_directory(input_dir, output_dir)
