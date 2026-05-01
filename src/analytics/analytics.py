"""
analytics.py — 대시보드용 분석 유틸리티

제공 기능:
  1. get_profile(corp, year) — 기업 프로파일 (주요 지표 + 메타)
  2. compare_years(corp, account, years) — 전년 대비 비교
  3. compare_companies(corps, account, year) — 기업 간 비교
  4. get_timeseries(corp, account, periods) — 시계열 데이터
  5. calculate_ratios(corp, year) — 재무 비율 자동 계산
  6. get_suggested_questions(corp) — 기업별 추천 질문

모두 facts.db에서 동작 (XBRL 구조화 팩트 활용).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

# ==========================================
# 기업명 정규화 (사용자 친화적 호칭 → DB 정식명)
# ==========================================

CORP_NAME_ALIASES = {
    "현대자동차": "현대차",
    "현대자동차주식회사": "현대차",
    "네이버": "NAVER",
    "naver": "NAVER",
    "포스코홀딩스": "POSCO홀딩스",
    "포스코": "POSCO홀딩스",
    "sk하이닉스": "SK하이닉스",
    "엘지에너지솔루션": "LG에너지솔루션",
    "엘지화학": "LG화학",
    "LG엔솔": "LG에너지솔루션",
}


def normalize_corp_name(name: str) -> str:
    if not name:
        return name
   
    if name in CORP_NAME_ALIASES:
        return CORP_NAME_ALIASES[name]
    
    lower = name.lower()
    if lower in CORP_NAME_ALIASES:
        return CORP_NAME_ALIASES[lower]
    return name


# ==========================================
# DB 조회 저수준 유틸
# ==========================================

def _fetch_value(
    db_path: str,
    corp_name: str,
    statement: str,
    account_kr: str,
    period_year: int,
    period_scope: str = None,
    period_cp: str = "C",
    report_type: str = "연결",
    period_variant: str = None,
) -> Optional[dict]:
    """
    단일 팩트 조회. period_scope 미지정 시 FY → HY → 3Q 순으로 fallback.
    """
    # 기업명 정규화
    corp_name = normalize_corp_name(corp_name)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    scopes = [period_scope] if period_scope else ["FY", "3Q", "HY"]
    
    # "당기순이익" → scope별 대체 명 매핑
    # 일부 기업은 "(손실)"이 병기되거나 "연결/계속영업" 접두사가 붙음
    SCOPE_ALIASES = {
        "당기순이익": {
            "3Q": ["분기순이익", "분기순이익(손실)", "연결분기순이익", "당기순이익"],
            "HY": ["반기순이익", "반기순이익(손실)", "연결반기순이익", "당기순이익"],
            "FY": ["당기순이익", "당기순이익(손실)", "연결당기순이익"],
        },
        "순이익": {
            "3Q": ["분기순이익", "분기순이익(손실)", "연결분기순이익", "당기순이익"],
            "HY": ["반기순이익", "반기순이익(손실)", "연결반기순이익", "당기순이익"],
            "FY": ["당기순이익", "당기순이익(손실)", "연결당기순이익"],
        },
        "영업이익": {
            "3Q": ["영업이익", "영업이익(손실)", "계속영업이익", "계속영업이익(손실)"],
            "HY": ["영업이익", "영업이익(손실)", "계속영업이익", "계속영업이익(손실)"],
            "FY": ["영업이익", "영업이익(손실)", "계속영업이익", "계속영업이익(손실)"],
        },
        "매출액": {
            "3Q": ["매출액", "매출", "수익", "영업수익"],
            "HY": ["매출액", "매출", "수익", "영업수익"],
            "FY": ["매출액", "매출", "수익", "영업수익"],
        },
    }
    
    for scope in scopes:
        # 시도할 account 이름 리스트 (원본 + alias)
        acc_candidates = [account_kr]
        if account_kr in SCOPE_ALIASES and scope in SCOPE_ALIASES[account_kr]:
            aliases = SCOPE_ALIASES[account_kr][scope]
            if isinstance(aliases, list):
                acc_candidates.extend(aliases)
            else:
                acc_candidates.append(aliases)
        
        for acc_try in acc_candidates:
            conditions = [
                "corp_name = ?", "statement = ?", "report_type = ?",
                "account_norm = ?", "period_year = ?", "period_cp = ?",
                "period_scope = ?"
            ]
            params = [corp_name, statement, report_type, acc_try,
                      period_year, period_cp, scope]
            
            if period_variant:
                conditions.append("(period_variant = ? OR period_variant IS NULL)")
                params.append(period_variant)
            
            sql = f"SELECT * FROM facts WHERE {' AND '.join(conditions)} LIMIT 1"
            cur.execute(sql, params)
            row = cur.fetchone()
            
            if row:
                conn.close()
                try:
                    v = float(row["value_raw"].replace(",", ""))
                except (ValueError, AttributeError):
                    v = None
                return {
                    "value": v,
                    "value_raw": row["value_raw"],
                    "unit": row["unit_hint"] or "원",
                    "period_tag": row["period_tag"],
                    "period_scope": row["period_scope"],
                    "source_file": row["source_file"],
                }
    
    conn.close()
    return None


def _unit_to_won(value: float, unit: str) -> float:
    """단위를 원 단위로 정규화."""
    if value is None:
        return None
    unit_lower = (unit or "").lower().replace(" ", "")
    if "백만" in unit_lower or "million" in unit_lower:
        return value * 1_000_000
    if "천" in unit_lower or "thousand" in unit_lower:
        return value * 1_000
    if "억" in unit_lower:
        return value * 100_000_000
    return value


def _format_won(value: float, use_hangeul: bool = True) -> str:
    """큰 숫자를 읽기 편한 형식으로 (조/억/만)."""
    if value is None:
        return "N/A"
    
    abs_v = abs(value)
    sign = "-" if value < 0 else ""
    
    if use_hangeul:
        if abs_v >= 1_000_000_000_000:
            trillions = abs_v / 1_000_000_000_000
            return f"{sign}{trillions:,.1f}조원"
        elif abs_v >= 100_000_000:  # 1억
            billions = abs_v / 100_000_000
            return f"{sign}{billions:,.0f}억원"
        elif abs_v >= 10_000:  # 1만
            return f"{sign}{abs_v/10_000:,.0f}만원"
        else:
            return f"{sign}{abs_v:,.0f}원"
    else:
        return f"{sign}{abs_v:,.0f}"


# ==========================================
# 1. 기업 프로파일
# ==========================================

@dataclass
class ProfileMetric:
    label: str
    value: Optional[float]
    display: str
    raw_value: Optional[str]
    unit: Optional[str]
    period_tag: Optional[str]


def get_profile(db_path: str, corp_name: str, year: int = 2025) -> dict:
    """
    기업의 주요 지표 프로파일 반환 (대시보드 카드용).
    
    Returns:
        {
          "corp_name": str,
          "year": int,
          "metrics": {"매출액": ProfileMetric, "영업이익": ProfileMetric, ...},
          "yoy": {"매출액": {"current": X, "previous": Y, "change_pct": Z}, ...}
        }
    """
    metrics_def = [
        # (label, statement, account_kr, preferred_scope)
        ("매출액", "포괄손익계산서", "매출액", None),
        ("영업이익", "포괄손익계산서", "영업이익", None),
        ("당기순이익", "포괄손익계산서", "당기순이익", None),
        ("자산총계", "재무상태표", "자산총계", None),
        ("부채총계", "재무상태표", "부채총계", None),
        ("자본총계", "재무상태표", "자본총계", None),
        ("유동자산", "재무상태표", "유동자산", None),
        ("현금및현금성자산", "재무상태표", "현금및현금성자산", None),
    ]
    
    metrics = {}
    yoy = {}
    
    for label, stmt, acc, scope in metrics_def:
        # 당기 (C)
        current = _fetch_value(db_path, corp_name, stmt, acc, year,
                              period_scope=scope, period_cp="C",
                              period_variant="A" if stmt == "포괄손익계산서" else None)
        
        if current:
            won_value = _unit_to_won(current["value"], current["unit"])
            metrics[label] = {
                "label": label,
                "value_won": won_value,
                "display": _format_won(won_value),
                "raw_value": current["value_raw"],
                "unit": current["unit"],
                "period_tag": current["period_tag"],
                "period_scope": current["period_scope"],
            }
            
            # 전년 동기 (P)
            prev = _fetch_value(db_path, corp_name, stmt, acc, year - 1,
                               period_scope=current["period_scope"], period_cp="P",
                               period_variant="A" if stmt == "포괄손익계산서" else None)
            if prev:
                prev_won = _unit_to_won(prev["value"], prev["unit"])
                if prev_won and won_value is not None:
                    change_pct = (won_value - prev_won) / abs(prev_won) * 100
                    yoy[label] = {
                        "current": won_value,
                        "previous": prev_won,
                        "change_pct": round(change_pct, 2),
                        "direction": "up" if change_pct > 0 else "down",
                    }
        else:
            metrics[label] = None
    
    return {
        "corp_name": corp_name,
        "year": year,
        "metrics": metrics,
        "yoy": yoy,
    }


# ==========================================
# 2. 전년 대비 비교
# ==========================================

def compare_years(db_path: str, corp_name: str, year: int = 2025,
                  accounts: Optional[list] = None) -> dict:
    """
    당기 vs 전기 비교 표.
    기본 지표 리스트로 시작, 사용자 지정 가능.
    """
    default_accounts = [
        ("포괄손익계산서", "매출액"),
        ("포괄손익계산서", "매출원가"),
        ("포괄손익계산서", "영업이익"),
        ("포괄손익계산서", "당기순이익"),
        ("재무상태표", "자산총계"),
        ("재무상태표", "부채총계"),
        ("재무상태표", "자본총계"),
    ]
    
    targets = accounts if accounts else default_accounts
    rows = []
    
    for stmt, acc in targets:
        current = _fetch_value(db_path, corp_name, stmt, acc, year, period_cp="C",
                              period_variant="A" if stmt == "포괄손익계산서" else None)
        prev = _fetch_value(db_path, corp_name, stmt, acc, year - 1, period_cp="P",
                           period_variant="A" if stmt == "포괄손익계산서" else None)
        
        cur_won = _unit_to_won(current["value"], current["unit"]) if current else None
        prev_won = _unit_to_won(prev["value"], prev["unit"]) if prev else None
        
        if cur_won is not None and prev_won is not None and prev_won != 0:
            change_pct = (cur_won - prev_won) / abs(prev_won) * 100
            change_abs = cur_won - prev_won
        else:
            change_pct = None
            change_abs = None
        
        rows.append({
            "statement": stmt,
            "account": acc,
            "current": {
                "value": cur_won,
                "display": _format_won(cur_won),
                "period_tag": current["period_tag"] if current else None,
            } if current else None,
            "previous": {
                "value": prev_won,
                "display": _format_won(prev_won),
                "period_tag": prev["period_tag"] if prev else None,
            } if prev else None,
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "change_abs": change_abs,
            "change_display": _format_won(change_abs) if change_abs else None,
        })
    
    return {
        "corp_name": corp_name,
        "current_year": year,
        "previous_year": year - 1,
        "comparisons": rows,
    }


# ==========================================
# 3. 기업 간 비교
# ==========================================

def compare_companies(db_path: str, corp_names: list[str], year: int = 2025,
                      accounts: Optional[list] = None) -> dict:
    """
    여러 기업의 동일 지표를 나란히 비교.
    """
    default_accounts = [
        ("포괄손익계산서", "매출액"),
        ("포괄손익계산서", "영업이익"),
        ("포괄손익계산서", "당기순이익"),
        ("재무상태표", "자산총계"),
        ("재무상태표", "자본총계"),
    ]
    targets = accounts if accounts else default_accounts
    
    result = {
        "year": year,
        "companies": corp_names,
        "metrics": [],
    }
    
    for stmt, acc in targets:
        metric_row = {
            "account": acc,
            "statement": stmt,
            "values": {},
        }
        for corp in corp_names:
            d = _fetch_value(db_path, corp, stmt, acc, year, period_cp="C",
                            period_variant="A" if stmt == "포괄손익계산서" else None)
            if d:
                won = _unit_to_won(d["value"], d["unit"])
                metric_row["values"][corp] = {
                    "value": won,
                    "display": _format_won(won),
                    "period_tag": d["period_tag"],
                }
            else:
                metric_row["values"][corp] = None
        result["metrics"].append(metric_row)
    
    return result


# ==========================================
# 4. 시계열 데이터
# ==========================================

def get_timeseries(db_path: str, corp_name: str, statement: str,
                   account_kr: str, scopes: list[str] = None) -> dict:
    """
    단일 계정의 시계열 데이터.
    scopes: ["HY", "3Q", "FY"] 같은 순서로 수집 (기본: 가능한 모든 기간).
    
    기업명 자동 정규화 (현대자동차 → 현대차) 및
    계정명 alias 지원 (영업이익 → 영업이익(손실), 당기순이익 → 반기/분기순이익 등).
    """
    # 기업명 정규화
    corp_name = normalize_corp_name(corp_name)
    
    # 계정명 후보 리스트 (alias 포함)
    ACCOUNT_ALIASES = {
        "영업이익": ["영업이익", "영업이익(손실)", "계속영업이익", "계속영업이익(손실)"],
        "매출액": ["매출액", "매출", "수익", "영업수익"],
        "당기순이익": ["당기순이익", "당기순이익(손실)",
                   "반기순이익", "반기순이익(손실)",
                   "분기순이익", "분기순이익(손실)",
                   "연결당기순이익", "연결반기순이익", "연결분기순이익"],
        "매출원가": ["매출원가"],
    }
    acc_candidates = ACCOUNT_ALIASES.get(account_kr, [account_kr])
    if account_kr not in acc_candidates:
        acc_candidates = [account_kr] + acc_candidates
    
    all_rows = []
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 당기(C) 데이터
    placeholders = ",".join(["?"] * len(acc_candidates))
    sql_c = f"""
        SELECT period_year, period_scope, period_cp, period_tag,
               value_raw, unit_hint, source_file, account_norm
        FROM facts
        WHERE corp_name=? AND statement=? AND report_type='연결'
          AND account_norm IN ({placeholders})
          AND period_cp='C'
          AND (period_variant IS NULL OR period_variant='A')
        ORDER BY period_year, period_scope
    """
    cur.execute(sql_c, [corp_name, statement] + acc_candidates)
    current_rows = cur.fetchall()
    
    # 전기(P) 데이터
    sql_p = f"""
        SELECT period_year, period_scope, period_tag, value_raw, unit_hint, account_norm
        FROM facts
        WHERE corp_name=? AND statement=? AND report_type='연결'
          AND account_norm IN ({placeholders})
          AND period_cp='P'
          AND (period_variant IS NULL OR period_variant='A')
        ORDER BY period_year, period_scope
    """
    cur.execute(sql_p, [corp_name, statement] + acc_candidates)
    prev_rows = cur.fetchall()
    conn.close()
    
    series = []
    seen_keys = set()  # (year, scope) 중복 방지
    
    # 당기 데이터 먼저 (우선순위)
    for r in current_rows:
        key = (r["period_year"], r["period_scope"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        try:
            v = float(r["value_raw"].replace(",", ""))
        except (ValueError, AttributeError):
            continue
        won = _unit_to_won(v, r["unit_hint"])
        series.append({
            "period_year": r["period_year"],
            "period_scope": r["period_scope"],
            "label": f"{r['period_year']}.{r['period_scope']}",
            "value_won": won,
            "display": _format_won(won),
            "period_tag": r["period_tag"],
            "account_norm": r["account_norm"],
        })
    
    # 전기 데이터: 당기에 없는 (연도, scope)만 추가
    for r in prev_rows:
        key = (r["period_year"], r["period_scope"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        try:
            v = float(r["value_raw"].replace(",", ""))
        except (ValueError, AttributeError):
            continue
        won = _unit_to_won(v, r["unit_hint"])
        series.append({
            "period_year": r["period_year"],
            "period_scope": r["period_scope"],
            "label": f"{r['period_year']}.{r['period_scope']}",
            "value_won": won,
            "display": _format_won(won),
            "period_tag": r["period_tag"],
            "account_norm": r["account_norm"],
        })
    
    # 정렬: 연도 → scope (HY→3Q→FY 순)
    scope_order = {"HY": 0, "3Q": 1, "FY": 2}
    series.sort(key=lambda s: (s["period_year"], scope_order.get(s["period_scope"], 99)))
    
    return {
        "corp_name": corp_name,
        "statement": statement,
        "account": account_kr,
        "series": series,
    }


# ==========================================
# 5. 재무 비율 자동 계산
# ==========================================

def calculate_ratios(db_path: str, corp_name: str, year: int = 2025) -> dict:
    """
    재무 비율 자동 계산.
    
    비율:
      - 유동비율 = 유동자산 / 유동부채
      - 부채비율 = 부채총계 / 자본총계
      - 자기자본비율 = 자본총계 / 자산총계
      - 영업이익률 = 영업이익 / 매출액
      - 순이익률 = 당기순이익 / 매출액
      - ROA = 당기순이익 / 자산총계
      - ROE = 당기순이익 / 자본총계
    """
    def fetch(stmt, acc, scope=None, cp="C", variant=None):
        d = _fetch_value(db_path, corp_name, stmt, acc, year,
                        period_scope=scope, period_cp=cp, period_variant=variant)
        if d:
            return _unit_to_won(d["value"], d["unit"])
        return None
    
    # 필요한 값들 미리 조회
    current_assets = fetch("재무상태표", "유동자산")
    current_liab = fetch("재무상태표", "유동부채")
    total_liab = fetch("재무상태표", "부채총계")
    total_equity = fetch("재무상태표", "자본총계")
    total_assets = fetch("재무상태표", "자산총계")
    revenue = fetch("포괄손익계산서", "매출액", variant="A")
    op_profit = fetch("포괄손익계산서", "영업이익", variant="A")
    net_profit = fetch("포괄손익계산서", "당기순이익", variant="A")
    
    def safe_ratio(numerator, denominator):
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator
    
    ratios = {
        "유동비율": {
            "value": safe_ratio(current_assets, current_liab),
            "formula": "유동자산 / 유동부채",
            "unit": "배",
            "interpretation": "1.0 이상이면 단기 지급 능력 양호",
        },
        "부채비율": {
            "value": safe_ratio(total_liab, total_equity),
            "formula": "부채총계 / 자본총계",
            "unit": "배",
            "interpretation": "낮을수록 재무 안정성 높음",
        },
        "자기자본비율": {
            "value": safe_ratio(total_equity, total_assets),
            "formula": "자본총계 / 자산총계",
            "unit": "%",
            "interpretation": "높을수록 재무 안정성 높음",
            "display_multiplier": 100,
        },
        "영업이익률": {
            "value": safe_ratio(op_profit, revenue),
            "formula": "영업이익 / 매출액",
            "unit": "%",
            "interpretation": "본업 수익성 지표",
            "display_multiplier": 100,
        },
        "순이익률": {
            "value": safe_ratio(net_profit, revenue),
            "formula": "당기순이익 / 매출액",
            "unit": "%",
            "interpretation": "최종 수익성 지표",
            "display_multiplier": 100,
        },
        "ROA": {
            "value": safe_ratio(net_profit, total_assets),
            "formula": "당기순이익 / 자산총계",
            "unit": "%",
            "interpretation": "총자산 수익률",
            "display_multiplier": 100,
        },
        "ROE": {
            "value": safe_ratio(net_profit, total_equity),
            "formula": "당기순이익 / 자본총계",
            "unit": "%",
            "interpretation": "자기자본 수익률",
            "display_multiplier": 100,
        },
    }
    
    # display 값 포맷
    for name, r in ratios.items():
        if r["value"] is not None:
            mult = r.get("display_multiplier", 1)
            r["display"] = f"{r['value']*mult:.2f}{r['unit']}"
        else:
            r["display"] = "N/A"
    
    return {
        "corp_name": corp_name,
        "year": year,
        "ratios": ratios,
    }


# ==========================================
# 6. 기업별 추천 질문
# ==========================================

CORP_SPECIFIC_QUESTIONS = {
    "삼성전자": [
        "삼성전자의 사업 부문 중 DX와 DS 부문의 차이는?",
        "삼성전자의 배당 정책과 주주 환원 계획은?",
        "삼성전자의 2025년 3분기 영업이익은 얼마인가요?",
    ],
    "SK하이닉스": [
        "SK하이닉스의 주요 제품과 시장 여건은?",
        "SK하이닉스의 최대주주는 누구인가요?",
        "SK하이닉스의 2025년 연간 매출액은?",
    ],
    "현대자동차": [
        "현대자동차의 자율주행/친환경차 연구개발 성과는?",
        "현대자동차의 주요 금융 자회사는?",
        "현대차의 2025년 3분기 매출액은?",
    ],
    "기아": [
        "기아의 글로벌 시장 판매 전략은?",
        "기아의 최대주주는 누구인가요?",
        "기아의 2025년 연간 매출액은?",
    ],
    "LG에너지솔루션": [
        "LG에너지솔루션의 주요 고객사와의 JV 설립 현황은?",
        "LG에너지솔루션의 원재료 가격 관리 방안은?",
        "LG에너지솔루션의 2025년 3분기 현금성자산 잔액은?",
    ],
    "LG화학": [
        "LG화학의 3대 신성장 동력은?",
        "LG화학의 사업부문과 매출 비중은?",
        "LG화학의 2025년 자본총계는?",
    ],
    "NAVER": [
        "NAVER의 주요 플랫폼 서비스 부문은?",
        "NAVER의 최대주주는 누구인가요?",
        "NAVER의 2025년 3분기 영업수익은?",
    ],
    "삼성바이오로직스": [
        "삼성바이오로직스의 CMO 공장 증설 계획은?",
        "삼성바이오로직스의 2025년 3분기 영업이익은?",
        "삼성바이오로직스의 자산총계는?",
    ],
    "POSCO홀딩스": [
        "POSCO홀딩스의 이차전지소재 사업 계획은?",
        "POSCO홀딩스의 7대 핵심 사업은?",
        "POSCO홀딩스의 2025년 3분기 자산총계는?",
    ],
    "셀트리온": [
        "셀트리온의 주요 바이오시밀러 파이프라인은?",
        "셀트리온의 2025년 반기 자산총계는?",
        "셀트리온의 2025년 매출액은?",
    ],
}


def get_suggested_questions(corp_name: str) -> list[str]:
    """기업별 추천 질문 반환."""
    return CORP_SPECIFIC_QUESTIONS.get(corp_name, [
        f"{corp_name}의 주요 사업 부문은?",
        f"{corp_name}의 2025년 3분기 매출액은?",
        f"{corp_name}의 최대주주는?",
    ])


# ==========================================
# 업종 매핑 + 업종 비교
# ==========================================

SECTOR_MAPPING = {
    "반도체": ["삼성전자", "SK하이닉스"],
    "자동차": ["현대차", "기아"],
    "이차전지": ["LG에너지솔루션", "LG화학"],
    "배터리": ["LG에너지솔루션", "LG화학"],
    "바이오": ["삼성바이오로직스", "셀트리온"],
    "제약": ["삼성바이오로직스", "셀트리온"],
    "철강": ["POSCO홀딩스"],
    "IT": ["NAVER"],
    "플랫폼": ["NAVER"],
    "전체": ["삼성전자", "SK하이닉스", "현대차", "기아",
            "LG에너지솔루션", "LG화학", "NAVER",
            "삼성바이오로직스", "POSCO홀딩스", "셀트리온"],
}


def get_sector_companies(sector: str) -> list[str]:
    """업종명 → 해당 기업 리스트."""
    return SECTOR_MAPPING.get(sector, [])


def compare_sector(db_path: str, sector: str, year: int = 2025,
                   metric: str = "수익성") -> dict:
    """
    업종 내 기업들을 비교 + 우수 기업 자동 선정.
    
    Args:
        sector: 업종명 (예: "반도체", "자동차")
        year: 비교 연도
        metric: 비교 기준 (예: "수익성", "안정성", "성장성", "전체")
    Returns:
        {
            "sector": str,
            "year": int,
            "metric": str,
            "companies": list[str],
            "rankings": [
                {"corp_name": str, "ratios": {..}, "rank": {..}},
                ...
            ],
            "winner": {
                "수익성": str,  # 영업이익률 1위
                "안정성": str,  # 부채비율 가장 낮은
                ...
            }
        }
    """
    if sector == "전체":
        corps = SECTOR_MAPPING["전체"]
    else:
        corps = SECTOR_MAPPING.get(sector, [])
    
    if len(corps) < 2 and sector != "전체":
        if len(corps) == 1:
            ratios = calculate_ratios(db_path, corps[0], year)
            return {
                "sector": sector,
                "year": year,
                "metric": metric,
                "companies": corps,
                "rankings": [
                    {"corp_name": corps[0], "ratios": ratios.get("ratios", {}), "rank": {}}
                ],
                "winner": {},
                "note": f"{sector} 업종은 보유 데이터에 1개 기업만 있어 비교가 제한적입니다.",
            }
        return {
            "sector": sector,
            "year": year,
            "companies": [],
            "error": f"'{sector}' 업종에 대한 데이터가 없습니다.",
        }
    
    # 각 기업의 비율 수집
    rankings = []
    for corp in corps:
        ratios_data = calculate_ratios(db_path, corp, year)
        ratios = ratios_data.get("ratios", {})
        rankings.append({
            "corp_name": corp,
            "ratios": ratios,
        })
    
    # 비율별 순위 매기기
    winners = {}
    
    def rank_by_metric(metric_name: str, higher_is_better: bool = True):
        """특정 비율로 정렬 후 winner 반환."""
        valid = [(r["corp_name"], r["ratios"].get(metric_name, {}).get("value"))
                 for r in rankings]
        valid = [(c, v) for c, v in valid if v is not None]
        if not valid:
            return None
        valid.sort(key=lambda x: x[1], reverse=higher_is_better)
        return valid[0][0]  # 1위 기업명
    
    winners["영업이익률"] = rank_by_metric("영업이익률", True)
    winners["순이익률"] = rank_by_metric("순이익률", True)
    winners["ROE"] = rank_by_metric("ROE", True)
    winners["ROA"] = rank_by_metric("ROA", True)
    winners["유동비율"] = rank_by_metric("유동비율", True)
    winners["부채비율"] = rank_by_metric("부채비율", False)
    winners["자기자본비율"] = rank_by_metric("자기자본비율", True)
    
    if len(rankings) >= 2:
        scored = []
        for r in rankings:
            score = 0
            count = 0
            for k in ["영업이익률", "순이익률", "ROE", "ROA"]:
                v = r["ratios"].get(k, {}).get("value")
                if v is not None:
                    score += v
                    count += 1
            if count > 0:
                scored.append((r["corp_name"], score / count))
        if scored:
            scored.sort(key=lambda x: -x[1])
            winners["종합_수익성"] = scored[0][0]
    
    for r in rankings:
        ranks = {}
        for metric_name in ["영업이익률", "ROE", "ROA"]:
            valid = [(rk["corp_name"], rk["ratios"].get(metric_name, {}).get("value"))
                     for rk in rankings]
            valid = [(c, v) for c, v in valid if v is not None]
            valid.sort(key=lambda x: -x[1])
            for i, (c, _) in enumerate(valid):
                if c == r["corp_name"]:
                    ranks[metric_name] = f"{i+1}/{len(valid)}"
                    break
        r["rank"] = ranks
    
    return {
        "sector": sector,
        "year": year,
        "metric": metric,
        "companies": corps,
        "rankings": rankings,
        "winner": winners,
    }


def get_corp_sector(corp_name: str) -> Optional[str]:
    """기업명 → 업종 (역매핑)."""
    corp_norm = normalize_corp_name(corp_name)
    for sector, corps in SECTOR_MAPPING.items():
        if sector == "전체":
            continue
        if corp_norm in corps:
            return sector
    return None