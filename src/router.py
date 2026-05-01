"""
router.py — 사용자 질문을 구조화된 쿼리 정보로 변환

전략:
1) 규칙 기반 1차 추출: 기업명·연도·분기·계정명 등을 정규식/동의어 맵으로 잡음
2) 신뢰도 평가: 회사명과 (계정명 또는 기간 키워드) 둘 다 잡혔으면 OK
3) 신뢰도 낮으면 HCX-003 LLM 라우터 호출
4) intent 분류: fact_lookup / narrative / hybrid

출력: QueryInfo
"""

from __future__ import annotations

import re
import os
import json
import requests
from dataclasses import dataclass, field, asdict
from typing import Optional
from functools import lru_cache

from build_fact_db import (
    ACCOUNT_SYNONYMS,
    REVERSE_SYN,
    normalize_account_name,
)
from utils import KNOWN_CORPS


# ==========================================
# 데이터 클래스
# ==========================================

@dataclass
class QueryInfo:
    """
    라우터 출력
    """
    # 원본
    raw_query: str
    
    # 분류
    intent: str = "unknown"   # fact_lookup / narrative / hybrid / definition / general / sector_compare / news_context / unknown
    
    # 엔티티
    corp_name: Optional[str] = None
    corp_name_raw: Optional[str] = None   # 사용자가 쓴 원 표현
    fiscal_year: Optional[int] = None
    period_scope: Optional[str] = None    # "FY" / "HY" / "3Q" / "1Q" / "2Q" / "4Q"
    period_cp: Optional[str] = None       # "C" (당기, 기본) / "P" (전기)
    period_type: Optional[str] = None     # "end" / "during"
    period_variant: Optional[str] = None  # "A" 누적 / "Q" 3개월치
    report_type: Optional[str] = None     # "연결" / "별도"
    statement: Optional[str] = None       # "재무상태표" / "포괄손익계산서" / ...
    account_kr: Optional[str] = None      # 사용자 표현 계정명
    account_norm: Optional[str] = None    # 정규화된 계정명
    
    # v7 신규: 용어/업종 추출
    term_query: Optional[str] = None      # 용어 사전 매칭 키
    sector_name: Optional[str] = None     # 업종명
    
    # 디버깅
    source: str = "rule"          # "rule" / "llm" / "hybrid"
    confidence: float = 0.0       # 0~1 신뢰도
    llm_raw_response: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)


# ==========================================
# 규칙 기반 추출 패턴
# ==========================================

# 연도
YEAR_RE = re.compile(r"(20\d{2})\s*년?(?:도)?")

# 분기
QUARTER_RE = re.compile(
    r"(?P<q>[1-4])\s*분기|"
    r"Q\s*(?P<q2>[1-4])|"
    r"(?P<q3>[1-4])\s*Q"
    , re.IGNORECASE
)

# 반기
HALF_RE = re.compile(r"반기|상반기|H1|2분기말")

# 말 vs 누적 구분
END_KEYWORDS_RE = re.compile(r"말\b|시점|기준|현재")
CUM_KEYWORDS_RE = re.compile(r"누적|지금까지|총")

# 연결 vs 별도
CONSOLIDATED_RE = re.compile(r"연결(?!감사)")
SEPARATE_RE = re.compile(r"별도|개별")

# 재무제표 종류
STATEMENT_PATTERNS = [
    (re.compile(r"재무상태표|대차대조표|재무\s*상태"), "재무상태표"),
    (re.compile(r"포괄손익|손익계산서|손익|손실"), "포괄손익계산서"),
    (re.compile(r"현금흐름"), "현금흐름표"),
    (re.compile(r"자본변동"), "자본변동표"),
]

# 전기/당기
CURRENT_PERIOD_RE = re.compile(r"당기|당분기|당년도|금년")
PRIOR_PERIOD_RE = re.compile(r"전기|전년|작년|전분기")

# Narrative 키워드
NARRATIVE_KEYWORDS = [
    "사업", "개요", "전략", "연혁", "역사", "연구개발", "R&D",
    "어떤", "무엇", "왜", "어떻게", "설명", "분석", "평가",
    "부문", "제품", "서비스", "시장", "경쟁", "전망",
    "정책", "계획", "방침", "방향", "주요", "성과",
]


# ==========================================
# 의도 키워드
# ==========================================

# definition: 용어/지표 정의 질문
# 예: "PER이 뭐야?", "ROE 설명해줘", "유동비율이 뭐지"
DEFINITION_KEYWORDS = [
    "뭐야", "뭐지", "무엇", "무슨", "뭐냐", "뭔가요",
    "정의", "의미", "뜻", "개념",
    "설명해", "알려줘", "알려주세요", "가르쳐", "이란", "이라는",
]

# 용어 사전과 정확히 일치하는 키워드
DEFINITION_TERMS = [
    "PER", "PBR", "EPS", "ROE", "ROA", "EBITDA",
    "유동비율", "부채비율", "자기자본비율", "이자보상비율", "당좌비율",
    "영업이익률", "순이익률", "매출성장률", "EPS성장률",
    "자산회전율", "재고자산회전율", "매출채권회전율",
    "시가총액", "거래량", "배당수익률", "배당성향", "주가",
    "DART", "XBRL", "사업보고서", "반기보고서", "분기보고서", "연결재무제표",
    "발생주의", "감가상각", "잉여현금흐름", "영업현금흐름",
]

# sector_compare: 업종/peer 비교 질문
# 예: "반도체 기업 중 어디가 가장 수익성 좋아?", "자동차 업종 비교"
SECTOR_KEYWORDS = [
    "업종", "산업", "섹터", "peer", "비교해", "비교 해",
]

SECTOR_NAMES = {
    "반도체": ["삼성전자", "SK하이닉스"],
    "자동차": ["현대차", "기아"],
    "배터리": ["LG에너지솔루션", "LG화학", "삼성SDI"],  # 삼성SDI는 미보유, 시연용
    "이차전지": ["LG에너지솔루션", "LG화학"],
    "바이오": ["삼성바이오로직스", "셀트리온"],
    "제약": ["삼성바이오로직스", "셀트리온"],
    "철강": ["POSCO홀딩스"],
    "IT": ["NAVER"],
    "플랫폼": ["NAVER"],
}

# general: 시스템 데이터에 없지만 LLM 일반 지식으로 답할 만한 질문
GENERAL_KEYWORDS = [
    "추천", "어떻게 시작", "초보", "입문", "공부", "배우",
    "방법", "전략", "투자",
]

# news_context: 회사 + 최근 동향/이슈 키워드
# 공시 데이터와 별개로 실시간 뉴스 검색 + 통합 답변
NEWS_KEYWORDS = [
    "최근", "요즘", "이슈", "동향", "현황", "분위기",
    "뉴스", "소식", "근황", "어떻게 되", "어떻게 돌아",
    "상황", "변화", "트렌드", "이슈는",
]


# ==========================================
# 기업명 별칭 맵
# ==========================================
CORP_ALIASES: dict[str, str] = {
    # 삼성전자
    "삼성전자": "삼성전자", "Samsung Electronics": "삼성전자",
    # SK하이닉스
    "SK하이닉스": "SK하이닉스", "sk하이닉스": "SK하이닉스", "하이닉스": "SK하이닉스",
    "SK Hynix": "SK하이닉스",
    # LG에너지솔루션
    "LG에너지솔루션": "LG에너지솔루션", "엘지에너지솔루션": "LG에너지솔루션",
    "LG에너지": "LG에너지솔루션", "LGES": "LG에너지솔루션",
    # 삼성바이오로직스
    "삼성바이오로직스": "삼성바이오로직스", "삼성바이오": "삼성바이오로직스",
    # 현대차
    "현대차": "현대차", "현대자동차": "현대차",
    # LG화학
    "LG화학": "LG화학", "엘지화학": "LG화학",
    # 기아
    "기아": "기아", "기아차": "기아", "기아자동차": "기아",
    # 셀트리온
    "셀트리온": "셀트리온",
    # POSCO홀딩스
    "POSCO홀딩스": "POSCO홀딩스", "포스코": "POSCO홀딩스",
    "포스코홀딩스": "POSCO홀딩스", "POSCO": "POSCO홀딩스",
    # NAVER
    "NAVER": "NAVER", "Naver": "NAVER", "naver": "NAVER",
    "네이버": "NAVER", "네이버(주)": "NAVER", "(주)네이버": "NAVER",
}


def extract_corp_name(query: str) -> tuple[Optional[str], Optional[str]]:
    """
    쿼리에서 기업명 추출
    긴 별칭부터 매칭 시도
    """
    sorted_aliases = sorted(CORP_ALIASES.keys(), key=lambda k: -len(k))
    for alias in sorted_aliases:
        if alias in query:
            return CORP_ALIASES[alias], alias
    return None, None


def extract_account_name(query: str) -> tuple[Optional[str], Optional[str]]:
    """
    쿼리에서 계정명 추출
    반환: (사용자 원본 표현, 정규화된 이름)
    """
    # REVERSE_SYN의 모든 alias (이미 공백 제거된 형태) 길이순으로 정렬
    # "매출원가"가 "매출"보다 먼저 매칭되도록
    sorted_aliases = sorted(REVERSE_SYN.keys(), key=lambda k: -len(k))
    query_clean = query.replace(" ", "")
    for alias in sorted_aliases:
        if alias and alias in query_clean:
            canonical = REVERSE_SYN[alias]
            return alias, canonical
    return None, None


def extract_period(query: str) -> dict:
    """
    기간 정보 추출. 반환 딕셔너리에 최대한 채움
    """
    info = {
        "fiscal_year": None,
        "period_scope": None,
        "period_cp": None,
        "period_type": None,
        "period_variant": None,
    }
    
    m = YEAR_RE.search(query)
    if m:
        info["fiscal_year"] = int(m.group(1))
    
    qm = QUARTER_RE.search(query)
    if qm:
        q_num = qm.group("q") or qm.group("q2") or qm.group("q3")
        info["period_scope"] = f"{q_num}Q"
    elif HALF_RE.search(query):
        info["period_scope"] = "HY"
    # FY는 기본값으로 두지 않음 — 명시적으로 "연간", "사업연도" 등이 있을 때만
    elif re.search(r"연간|사업연도|사업\s*\(년\)|연말|12월\s*말", query):
        info["period_scope"] = "FY"
    # 폴백: "당분기말"처럼 분기 숫자가 명시 안 된 경우 → 3Q 가정
    # (데이터셋에서 eval_data 시점 기준 최신 분기보고서가 3Q)
    elif re.search(r"당분기|이번\s*분기", query):
        info["period_scope"] = "3Q"
    
    # 당기/전기
    if PRIOR_PERIOD_RE.search(query):
        info["period_cp"] = "P"
    elif CURRENT_PERIOD_RE.search(query) or "기준" in query:
        info["period_cp"] = "C"
    
    # 시점 vs 기간
    if END_KEYWORDS_RE.search(query):
        info["period_type"] = "end"
    elif CUM_KEYWORDS_RE.search(query):
        info["period_type"] = "during"
        info["period_variant"] = "A"  # 누적
    
    return info


def extract_report_type(query: str) -> Optional[str]:
    """연결 / 별도 추출"""
    if CONSOLIDATED_RE.search(query):
        return "연결"
    if SEPARATE_RE.search(query):
        return "별도"
    return None


def extract_statement(query: str) -> Optional[str]:
    """재무제표 종류 추출"""
    for pattern, label in STATEMENT_PATTERNS:
        if pattern.search(query):
            return label
    return None


# ==========================================
# Intent 분류
# ==========================================

def extract_term_query(query: str) -> Optional[str]:
    """
    쿼리에서 용어 사전에 등록된 용어 추출
    DEFINITION_TERMS 리스트와 매칭. 가장 긴 매칭 우선
    
    영문 약어(PER, ROE 등): 앞뒤가 영문/숫자가 아니어야 매칭 
    한글 용어(유동비율 등): 단순 substring 매칭
    """
    if not query:
        return None
    
    # 길이 내림차순 정렬해서 긴 것부터 매칭 (주가수익비율 > 주가)
    sorted_terms = sorted(DEFINITION_TERMS, key=lambda x: -len(x))
    
    for term in sorted_terms:
        if term.isascii():
            # 영문/숫자/약어: 앞뒤가 영숫자가 아닌 경우만 매칭
            # \W 대신 명시적으로 [^a-zA-Z0-9]로 처리
            pattern = rf"(?:^|[^a-zA-Z0-9]){re.escape(term)}(?:[^a-zA-Z0-9]|$)"
            if re.search(pattern, query, re.IGNORECASE):
                return term
        else:
            # 한글
            if term in query:
                return term
    
    return None


def extract_sector(query: str) -> Optional[str]:
    """쿼리에서 업종명 추출"""
    if not query:
        return None
    
    sorted_sectors = sorted(SECTOR_NAMES.keys(), key=lambda x: -len(x))
    for sector in sorted_sectors:
        if sector in query:
            return sector
    
    return None


def classify_intent_rule(qi: QueryInfo, query: str) -> str:
    """
    규칙 기반 intent 분류
    
    우선순위:
      1. definition: 용어 사전 매칭 + 정의 요청 키워드
      2. sector_compare: 업종명 + 비교 키워드 (회사명 없을 때)
      3. fact_lookup: 회사 + 재무 항목/기간
      4. hybrid: 회사 + 재무 + 서술 키워드
      5. narrative: 회사 + 서술 키워드
      6. general: 위 모두 매칭 안 됨 (일반 LLM 폴백)
    """
    # ==========================================
    # Definition 우선 매칭
    # ==========================================
    term_match = extract_term_query(query)
    if term_match:
        # 용어가 매칭됐고, 회사명이 없거나 "정의 요청 키워드"가 있으면 definition
        has_definition_kw = any(kw in query for kw in DEFINITION_KEYWORDS)
        # 회사명 없으면 거의 확실히 definition
        if not qi.corp_name:
            qi.term_query = term_match
            return "definition"
        # 회사명이 있어도 "PER이 뭐야?" 같은 명확한 정의 요청이면 definition
        if has_definition_kw and not qi.account_kr and not qi.statement:
            qi.term_query = term_match
            return "definition"
    
    # ==========================================
    # Sector compare 매칭
    # ==========================================
    sector_match = extract_sector(query)
    if sector_match and not qi.corp_name:
        # 업종 + 비교 키워드 = sector_compare
        has_sector_kw = any(kw in query for kw in SECTOR_KEYWORDS)
        if has_sector_kw or "어디" in query or "가장" in query:
            qi.sector_name = sector_match
            return "sector_compare"
    
    # ==========================================
    # 기존 분류 (fact_lookup / narrative / hybrid)
    # ==========================================
    has_fact_signal = (
        qi.account_kr is not None
        or qi.statement is not None
    )
    has_narrative_signal = any(kw in query for kw in NARRATIVE_KEYWORDS)
    has_news_signal = any(kw in query for kw in NEWS_KEYWORDS)
    has_period = qi.period_scope is not None or qi.fiscal_year is not None
    has_corp = qi.corp_name is not None
    
    # ==========================================
    # News context: 회사 + 뉴스 키워드, fact 신호 약함
    # 명시적 fact 요구(계정명 + 기간)는 우선
    # ==========================================
    if has_corp and has_news_signal and not (has_fact_signal and has_period):
        return "news_context"
    
    # 명시적 narrative 우선 (회사명 + narrative 키워드)
    if has_corp and has_narrative_signal and not has_fact_signal:
        return "narrative"
    
    # 명확한 fact (회사 + 재무 항목 + 기간)
    if has_corp and has_fact_signal and has_period:
        if has_narrative_signal:
            return "hybrid"
        return "fact_lookup"
    
    if has_corp and has_fact_signal:
        return "fact_lookup"
    
    if has_corp and has_narrative_signal:
        return "narrative"
    
    # 회사명만 있고 키워드 없음 → narrative
    if has_corp:
        return "narrative"
    
    # ==========================================
    # General fallback (회사명 없고 위 모든 매칭 실패)
    # ==========================================
    has_general_kw = any(kw in query for kw in GENERAL_KEYWORDS)
    if has_general_kw:
        return "general"
    
    # 마지막 fallback: 쿼리가 짧고 키워드 없으면 general
    return "general"


def compute_confidence(qi: QueryInfo) -> float:
    """
    추출된 엔티티들 기반으로 신뢰도 점수 계산
    0.0 ~ 1.0
    """
    score = 0.0
    if qi.corp_name:
        score += 0.4
    if qi.account_kr:
        score += 0.3
    if qi.fiscal_year:
        score += 0.15
    if qi.period_scope:
        score += 0.15
    return min(1.0, score)


# ==========================================
# 규칙 기반 전체 파서
# ==========================================

def route_rule_based(query: str) -> QueryInfo:
    """규칙만으로 쿼리를 파싱. LLM 호출 없음"""
    qi = QueryInfo(raw_query=query, source="rule")
    
    corp, corp_raw = extract_corp_name(query)
    qi.corp_name = corp
    qi.corp_name_raw = corp_raw
    
    acc_alias, acc_canonical = extract_account_name(query)
    qi.account_kr = acc_alias
    qi.account_norm = acc_canonical
    
    period = extract_period(query)
    qi.fiscal_year = period["fiscal_year"]
    qi.period_scope = period["period_scope"]
    qi.period_cp = period["period_cp"] or "C"
    qi.period_type = period["period_type"]
    qi.period_variant = period["period_variant"]
    
    qi.report_type = extract_report_type(query)
    qi.statement = extract_statement(query)
    
    # 통계: 재무제표 종류에 따라 period_type 자동 보정
    # - 재무상태표는 시점 데이터 → end
    # - 손익계산서/현금흐름표는 기간 데이터 → during
    # (사용자가 "손익계산서 기준"처럼 쓸 수 있으므로 statement 유형이 더 권위 있음)
    if qi.statement == "재무상태표":
        qi.period_type = "end"
        qi.period_variant = None
    elif qi.statement in {"포괄손익계산서", "현금흐름표"}:
        qi.period_type = "during"
        if qi.period_variant is None:
            qi.period_variant = "A" 
    
    # Intent 분류
    qi.intent = classify_intent_rule(qi, query)
    
    # 신뢰도
    qi.confidence = compute_confidence(qi)
    
    return qi


# ==========================================
# LLM 라우터
# ==========================================

CLOVA_API_KEY = os.environ.get("CLOVA_API_KEY", "")
CLOVA_URL = "https://clovastudio.stream.ntruss.com/testapp/v1/chat-completions/HCX-003"

LLM_SYSTEM_PROMPT = """당신은 한국 금융 공시 질의 분석기입니다. 사용자의 질문에서 구조화된 정보를 추출하여 JSON으로만 출력하세요.

출력 JSON 스키마:
{
  "intent": "fact_lookup" | "narrative" | "hybrid",
  "corp_name": 기업명 또는 null,
  "fiscal_year": 연도(정수) 또는 null,
  "period_scope": "FY" | "HY" | "1Q" | "2Q" | "3Q" | "4Q" 또는 null,
  "period_cp": "C" | "P" 또는 null,
  "period_type": "end" | "during" 또는 null,
  "period_variant": "A" | "Q" 또는 null,
  "report_type": "연결" | "별도" 또는 null,
  "statement": "재무상태표" | "포괄손익계산서" | "현금흐름표" | "자본변동표" 또는 null,
  "account_kr": 계정 한글명 또는 null
}

규칙:
- 구체적 숫자를 묻는 질문 → intent="fact_lookup"
- 사업 개요/전략/연구개발 등 서술형 질문 → intent="narrative"  
- 숫자와 설명을 모두 요구 → intent="hybrid"
- "3분기말" 처럼 시점 → period_type="end", period_scope="3Q"
- "3분기 누적" 처럼 기간 → period_type="during", period_scope="3Q", period_variant="A"
- "당분기", "당기" → period_cp="C" (전기는 "P")

예시 1:
질문: "삼성전자의 2025년 3분기말 연결재무상태표 기준 유동자산 총계는 얼마인가요?"
출력: {"intent":"fact_lookup","corp_name":"삼성전자","fiscal_year":2025,"period_scope":"3Q","period_cp":"C","period_type":"end","period_variant":null,"report_type":"연결","statement":"재무상태표","account_kr":"유동자산"}

예시 2:
질문: "현대차의 연구개발 성과는 어떠한가요?"
출력: {"intent":"narrative","corp_name":"현대차","fiscal_year":null,"period_scope":null,"period_cp":null,"period_type":null,"period_variant":null,"report_type":null,"statement":null,"account_kr":null}

JSON만 출력하세요. 설명 금지."""


def call_hcx_router(query: str, api_key: Optional[str] = None, timeout: int = 20) -> Optional[dict]:
    """HCX-003 LLM 라우터 호출"""
    key = api_key or CLOVA_API_KEY
    if not key:
        return None
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        "topP": 0.3,
        "temperature": 0.0,
        "maxTokens": 300,
    }
    
    try:
        res = requests.post(CLOVA_URL, headers=headers, json=payload, timeout=timeout)
        res.raise_for_status()
        raw = res.json()["result"]["message"]["content"].strip()
        
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE)
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < 0:
            return None
        parsed = json.loads(raw[start:end+1])
        parsed["_raw"] = raw
        return parsed
    except (requests.RequestException, KeyError, json.JSONDecodeError, TimeoutError):
        return None


def merge_llm_result(qi: QueryInfo, llm_result: dict) -> QueryInfo:
    """
    LLM 결과를 QueryInfo에 병합. 규칙 기반 결과가 있으면 유지, 없는 것만 LLM으로
    """
    qi.source = "hybrid"
    qi.llm_raw_response = llm_result.get("_raw")
    
    # intent는 LLM이 더 정확할 수 있으므로 덮어씀
    if llm_result.get("intent") in {"fact_lookup", "narrative", "hybrid",
                                     "definition", "general", "sector_compare",
                                     "news_context"}:
        qi.intent = llm_result["intent"]
    
    # 규칙 기반에서 못 뽑은 것만
    def fill(attr: str, llm_key: str):
        if getattr(qi, attr) is None and llm_result.get(llm_key):
            setattr(qi, attr, llm_result[llm_key])
    
    fill("corp_name", "corp_name")
    fill("fiscal_year", "fiscal_year")
    fill("period_scope", "period_scope")
    fill("period_cp", "period_cp")
    fill("period_type", "period_type")
    fill("period_variant", "period_variant")
    fill("report_type", "report_type")
    fill("statement", "statement")
    
    if qi.account_kr is None and llm_result.get("account_kr"):
        qi.account_kr = llm_result["account_kr"]
        qi.account_norm = normalize_account_name(llm_result["account_kr"])
    
    # 통계 재보정
    if qi.statement == "재무상태표":
        qi.period_type = "end"
        qi.period_variant = None
    elif qi.statement in {"포괄손익계산서", "현금흐름표"}:
        qi.period_type = "during"
        if qi.period_variant is None:
            qi.period_variant = "A"
    
    # 신뢰도 재계산
    qi.confidence = compute_confidence(qi)
    
    return qi


# ==========================================
# 최종 라우터
# ==========================================

CONFIDENCE_THRESHOLD = 0.6  # 이하면 LLM 폴백


def route(query: str, use_llm: bool = True, api_key: Optional[str] = None) -> QueryInfo:
    """
    사용자 쿼리 → QueryInfo
    
    1) 규칙 기반 추출 시도
    2) 신뢰도 >= 0.6 이면 그대로 반환 (LLM 호출 없음)
    3) 신뢰도 < 0.6 이고 use_llm=True 이면 HCX 호출
    """
    qi = route_rule_based(query)
    
    if qi.confidence >= CONFIDENCE_THRESHOLD:
        return qi
    
    if not use_llm:
        return qi
    
    llm_result = call_hcx_router(query, api_key=api_key)
    if llm_result is None:
        return qi  # LLM 실패 시 규칙 결과 반환
    
    return merge_llm_result(qi, llm_result)


# ==========================================
# 테스트
# ==========================================

if __name__ == "__main__":
    test_queries = [
        # eval_data 표 질문들
        "삼성전자의 2025년 3분기말(당분기말) 연결재무상태표 기준 유동자산 총계는 얼마인가요?",
        "SK하이닉스의 2025년 3분기 누적 연결포괄손익계산서 상 매출원가는 얼마인가요?",
        "현대자동차의 2025년 3분기 누적 연결손익계산서 기준 매출액은 얼마인가요?",
        "LG에너지솔루션의 2025년 당분기말 기준 연결재무상태표 상 현금및현금성자산의 잔액은 얼마인가요?",
        "POSCO홀딩스의 2025년 3분기말 연결재무상태표 기준 자산총계는 얼마인가요?",
        "NAVER의 2025년 3분기 누적 연결포괄손익계산서 기준 영업수익(매출액)은 얼마인가요?",
        # 내러티브 질문들
        "삼성전자의 사업 부문 중 DX 부문과 DS 부문이 각각 담당하는 주요 사업 내용은 무엇인가요?",
        "현대자동차의 연구개발실적 중 자율주행이나 친환경차와 관련된 최근 개발 성과는 무엇인가요?",
        "LG화학의 3대 신성장 동력과 관련된 주요 사업 추진 현황은 어떠한가요?",
        # 축약형
        "네이버 매출은?",
        "포스코 영업이익 알려줘",
        # 애매한 것
        "삼성전자는 어떤 회사인가요?",
    ]
    
    print("=" * 70)
    print("라우터 규칙 기반 테스트 (LLM 호출 없음)")
    print("=" * 70)
    
    for q in test_queries:
        qi = route(q, use_llm=False)
        print(f"\n📝 {q[:60]}{'...' if len(q) > 60 else ''}")
        print(f"  intent={qi.intent}, conf={qi.confidence:.2f}")
        print(f"  corp={qi.corp_name}, year={qi.fiscal_year}, scope={qi.period_scope}")
        print(f"  stmt={qi.statement}, report={qi.report_type}")
        print(f"  account_kr={qi.account_kr} (norm={qi.account_norm})")
        print(f"  period_type={qi.period_type}, variant={qi.period_variant}, cp={qi.period_cp}")
