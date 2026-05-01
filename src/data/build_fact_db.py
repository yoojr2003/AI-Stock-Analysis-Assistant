"""
build_fact_db.py — facts.jsonl을 SQLite로 구축

스키마 하이라이트:
  - period_tag를 cp/type/scope로 파싱해서 쿼리 편의성 확보
  - account_kr에 대해 동의어(synonym) 테이블을 별도로 두어
    "매출액 / 매출 / 영업수익 / 수익" 같은 이칭을 정규화
"""

from __future__ import annotations

import sqlite3
import json
import re
import os
from pathlib import Path
from typing import Optional


# ==========================================
# period_scope 매핑
# ==========================================
PERIOD_SCOPE_ALIASES = {
    "FQ": "1Q",
    "SQ": "2Q",
    "TQ": "3Q",
}


def normalize_period_scope(scope: Optional[str]) -> Optional[str]:
    """DART 내부 표기를 사용자 친화적 표기로 정규화."""
    if not scope:
        return scope
    return PERIOD_SCOPE_ALIASES.get(scope, scope)


# ==========================================
# period_tag 파싱
# ==========================================

# period_tag 포맷: <CP>FY<YEAR><type><scope>[<variant>]
# 예시:
#   CFY2025e3Q    = 당기 2025 3분기말 시점
#   CFY2025d3QA   = 당기 2025 3분기 누적 (Accumulated)
#   CFY2025d3QQ   = 당기 2025 3분기 3개월치만 (Quarter only)
#   CFY2025eHY    = 당기 2025 반기말
#   CFY2025dHYA   = 당기 2025 반기 누적
#   PFY2024eFY    = 전기 2024 사업연도말
#   PFY2024dFYA   = 전기 2024 연간 누적

PERIOD_TAG_RE = re.compile(
    r"^(?P<cp>[CP])FY(?P<year>\d{4})"
    r"(?P<ptype>[ed])"
    r"(?P<scope>FY|HY|FQ|SQ|TQ|1Q|2Q|3Q|4Q)"
    r"(?P<variant>[AQ]?)"
    r"$"
)


def parse_period_tag(tag: str) -> dict:
    """period_tag를 구조화된 필드로 분해."""
    if not tag or not tag.startswith(("C", "P")):
        return {
            "period_cp": None, "period_year": None,
            "period_type": None, "period_scope": None, "period_variant": None,
        }
    m = PERIOD_TAG_RE.match(tag)
    if not m:
        # 폴백: 최소한 CP/Year만이라도 추출
        simple = re.match(r"^([CP])FY(\d{4})", tag)
        if simple:
            return {
                "period_cp": simple.group(1),
                "period_year": int(simple.group(2)),
                "period_type": None,
                "period_scope": None,
                "period_variant": None,
            }
        return {
            "period_cp": None, "period_year": None,
            "period_type": None, "period_scope": None, "period_variant": None,
        }

    ptype_map = {"e": "end", "d": "during"}
    return {
        "period_cp": m.group("cp"),
        "period_year": int(m.group("year")),
        "period_type": ptype_map.get(m.group("ptype")),
        "period_scope": normalize_period_scope(m.group("scope")),
        "period_variant": m.group("variant") or None,
    }


# ==========================================
# 회계 계정 동의어 사전
# ==========================================

ACCOUNT_SYNONYMS: dict[str, list[str]] = {
    # 재무상태표
    "유동자산": ["유동자산", "유동 자산", "Current assets"],
    "비유동자산": ["비유동자산", "비유동 자산", "Non-current assets"],
    "자산총계": ["자산총계", "자산 총계", "총자산", "Total assets"],
    "유동부채": ["유동부채", "유동 부채"],
    "비유동부채": ["비유동부채", "비유동 부채"],
    "부채총계": ["부채총계", "총부채", "Total liabilities"],
    "자본총계": ["자본총계", "총자본", "자기자본", "Total equity"],
    "현금및현금성자산": ["현금및현금성자산", "현금 및 현금성 자산", "현금 및 현금성자산", "현금성자산"],
    "매출채권": ["매출채권", "매출채권및기타채권"],
    "재고자산": ["재고자산"],
    # 손익계산서
    "매출액": ["매출액", "매출", "수익", "영업수익", "매출 및 수익", "Revenue"],
    "매출원가": ["매출원가", "매출 원가", "Cost of sales"],
    "매출총이익": ["매출총이익", "매출 총이익"],
    "영업이익": ["영업이익", "영업 이익", "영업손익", "Operating profit", "Operating income"],
    "당기순이익": ["당기순이익", "당기 순이익", "순이익", "Net income"],
    "법인세비용": ["법인세비용", "법인세 비용"],
    # 현금흐름표
    "영업활동현금흐름": ["영업활동현금흐름", "영업활동으로 인한 현금흐름", "영업활동으로인한현금흐름"],
    "투자활동현금흐름": ["투자활동현금흐름", "투자활동으로 인한 현금흐름"],
    "재무활동현금흐름": ["재무활동현금흐름", "재무활동으로 인한 현금흐름"],
}


def build_reverse_synonym_map(synonyms: dict[str, list[str]]) -> dict[str, str]:
    """각 이칭 → 표준명 매핑. 입력 문자열 정규화 후 저장."""
    reverse = {}
    for canonical, aliases in synonyms.items():
        for alias in aliases:
            key = alias.replace(" ", "")
            reverse[key] = canonical
    return reverse


REVERSE_SYN = build_reverse_synonym_map(ACCOUNT_SYNONYMS)


def normalize_account_name(raw: str) -> str:
    """
    입력 계정명을 표준형으로 매핑.
    완전 일치 우선, 매칭 실패 시 공백만 제거한 원본 반환.
    """
    if not raw:
        return ""
    key = raw.replace(" ", "").replace("\u3000", "")
    # 앞뒤 특수문자·공백 제거
    key = re.sub(r"^[\u3000\s\-·、,]+|[\u3000\s\-·、,]+$", "", key)
    # 계정명 끝에 붙는 주석 표시 제거
    key = re.sub(r"\(\s*주[\s\d,]+\)$", "", key)
    key = re.sub(r"\(단위[^)]*\)$", "", key)
    # 공백 다시 제거
    key = key.replace(" ", "").strip()
    # 완전 일치만
    if key in REVERSE_SYN:
        return REVERSE_SYN[key]
    return key


# ==========================================
# DB 스키마
# ==========================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id         TEXT PRIMARY KEY,
    corp_name       TEXT NOT NULL,
    fiscal_year     INTEGER NOT NULL,
    source_file     TEXT NOT NULL,

    statement       TEXT,
    report_type     TEXT,
    xbrl_class      TEXT,
    statement_title TEXT,

    account_code    TEXT,
    account_kr      TEXT,
    account_norm    TEXT,    -- 동의어 정규화된 계정명

    period_tag      TEXT,
    period_cp       TEXT,    -- 'C' or 'P'
    period_year     INTEGER,
    period_type     TEXT,    -- 'end' or 'during'
    period_scope    TEXT,    -- 'FY' / 'HY' / '1Q' / '2Q' / '3Q' / '4Q'
    period_variant  TEXT,    -- 'A' (누적) / 'Q' (3개월치) / NULL
    is_current_period INTEGER,

    value           REAL,
    value_raw       TEXT,
    unit_hint       TEXT
);

CREATE INDEX IF NOT EXISTS idx_corp_stmt ON facts(corp_name, statement, report_type);
CREATE INDEX IF NOT EXISTS idx_period ON facts(period_cp, period_year, period_scope);
CREATE INDEX IF NOT EXISTS idx_account_norm ON facts(account_norm);
CREATE INDEX IF NOT EXISTS idx_xbrl ON facts(xbrl_class);

-- 편의를 위한 뷰: 당기 데이터만
CREATE VIEW IF NOT EXISTS current_facts AS
SELECT * FROM facts WHERE period_cp = 'C';
"""


def build_db(facts_jsonl: str, db_path: str, overwrite: bool = True) -> dict:
    """
    facts.jsonl 읽어 SQLite DB를 구축.
    """
    if overwrite and os.path.exists(db_path):
        os.remove(db_path)

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)
    conn.commit()

    inserted = 0
    skipped = 0

    with open(facts_jsonl, "r", encoding="utf-8") as f:
        batch = []
        for line in f:
            d = json.loads(line)
            period_info = parse_period_tag(d.get("period_tag", ""))
            account_norm = normalize_account_name(d.get("account_kr", ""))

            row = (
                d["fact_id"],
                d["corp_name"],
                d["fiscal_year"],
                d["source_file"],
                d.get("statement"),
                d.get("report_type"),
                d.get("xbrl_class"),
                d.get("statement_title"),
                d.get("account_code"),
                d.get("account_kr"),
                account_norm,
                d.get("period_tag"),
                period_info["period_cp"],
                period_info["period_year"],
                period_info["period_type"],
                period_info["period_scope"],
                period_info["period_variant"],
                1 if d.get("is_current_period") else 0,
                d.get("value"),
                d.get("value_raw"),
                d.get("unit_hint"),
            )
            batch.append(row)

            if len(batch) >= 500:
                try:
                    cur.executemany(
                        "INSERT OR IGNORE INTO facts VALUES ("
                        + ",".join(["?"] * 21) + ")",
                        batch,
                    )
                    inserted += cur.rowcount
                except sqlite3.Error as e:
                    print(f"Batch insert error: {e}")
                    skipped += len(batch)
                batch.clear()

        if batch:
            try:
                cur.executemany(
                    "INSERT OR IGNORE INTO facts VALUES ("
                    + ",".join(["?"] * 21) + ")",
                    batch,
                )
                inserted += cur.rowcount
            except sqlite3.Error as e:
                print(f"Final batch error: {e}")
                skipped += len(batch)

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM facts")
    total = cur.fetchone()[0]

    cur.execute("SELECT corp_name, COUNT(*) FROM facts GROUP BY corp_name")
    per_corp = cur.fetchall()

    cur.execute(
        "SELECT statement, report_type, COUNT(*) FROM facts "
        "WHERE statement IS NOT NULL GROUP BY statement, report_type"
    )
    per_stmt = cur.fetchall()

    conn.close()

    return {
        "db_path": db_path,
        "total": total,
        "inserted": inserted,
        "skipped": skipped,
        "per_corp": per_corp,
        "per_statement": per_stmt,
    }


# ==========================================
# FactRetriever
# ==========================================

class FactRetriever:
    """
    라우터가 추출한 구조 정보를 받아 SQLite에서 조회
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def lookup(
        self,
        corp_name: Optional[str] = None,
        statement: Optional[str] = None,          # 재무상태표 / 포괄손익계산서 / 현금흐름표
        report_type: Optional[str] = None,        # 연결 / 별도
        account_kr: Optional[str] = None,         # 사용자 표현 (자동 정규화)
        account_code: Optional[str] = None,       # IFRS 코드 직접 지정
        fiscal_year: Optional[int] = None,
        period_cp: Optional[str] = None,          # C / P (기본: C)
        period_scope: Optional[str] = None,       # FY / HY / 3Q 등
        period_type: Optional[str] = None,        # end / during
        period_variant: Optional[str] = None,     # A / Q
        limit: int = 5,
    ) -> list[dict]:
        conditions = []
        params = []

        if corp_name:
            conditions.append("corp_name = ?")
            params.append(corp_name)
        if statement:
            conditions.append("statement = ?")
            params.append(statement)
        if report_type:
            conditions.append("report_type = ?")
            params.append(report_type)
        if account_code:
            conditions.append("account_code = ?")
            params.append(account_code)
        elif account_kr:
            norm = normalize_account_name(account_kr)
            conditions.append("account_norm = ?")
            params.append(norm)
        if fiscal_year:
            conditions.append("period_year = ?")
            params.append(fiscal_year)
        if period_cp:
            conditions.append("period_cp = ?")
            params.append(period_cp)
        if period_scope:
            conditions.append("period_scope = ?")
            params.append(period_scope)
        if period_type:
            conditions.append("period_type = ?")
            params.append(period_type)
        if period_variant:
            conditions.append("period_variant = ?")
            params.append(period_variant)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM facts WHERE {where} ORDER BY fact_id LIMIT {int(limit)}"

        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        return rows

    def lookup_auto(self, query_info: dict) -> dict:
        """
        라우터 출력을 그대로 받아 가장 적합한 팩트 1개 반환
        
        query_info 예:
        {
          "corp_name": "NAVER", 
          "statement": "재무상태표", 
          "report_type": "연결",
          "account_kr": "유동자산",
          "fiscal_year": 2025,       # 사용자가 말한 연도 = period_year로 조회됨
          "period_scope": "3Q",      # 또는 "HY", "FY"
          "period_type": "end",      # 재무상태표는 항상 end
          "period_cp": "C",          # C=당기, P=전기 (기본 C)
        }
        
        Fallback 전략:
          1. period_cp=C로 못 찾으면 P로 재시도
          2. period_scope 없으면 FY로 가정 후 재시도
          3. period_variant 제거
        """
        if query_info.get("statement") == "재무상태표" and not query_info.get("period_type"):
            query_info["period_type"] = "end"
        if query_info.get("statement") in {"포괄손익계산서", "현금흐름표"}:
            if not query_info.get("period_type"):
                query_info["period_type"] = "during"
            if not query_info.get("period_variant"):
                query_info["period_variant"] = "A"
        if not query_info.get("period_cp"):
            query_info["period_cp"] = "C"

        ALLOWED_FIELDS = {"corp_name", "statement", "report_type",
                          "account_kr", "account_code",
                          "fiscal_year", "period_cp",
                          "period_scope", "period_type",
                          "period_variant"}

        def _lookup(qinfo):
            return self.lookup(limit=5, **{k: v for k, v in qinfo.items() 
                                             if k in ALLOWED_FIELDS})

        if not query_info.get("period_scope"):
            fy_first = dict(query_info)
            fy_first["period_scope"] = "FY"
            rows = _lookup(fy_first)
            if rows:
                status = "exact_fy_inferred" if len(rows) == 1 else "multiple_fy_inferred"
                return {"status": status, "matches": rows, "query": fy_first}
            
            if query_info.get("period_cp") == "C":
                fy_past = dict(fy_first)
                fy_past["period_cp"] = "P"
                rows = _lookup(fy_past)
                if rows:
                    status = "exact_past_fy" if len(rows) == 1 else "multiple_past_fy"
                    return {"status": status, "matches": rows, "query": fy_past}

        rows = _lookup(query_info)
        if rows:
            status = "exact" if len(rows) == 1 else "multiple"
            return {"status": status, "matches": rows, "query": query_info}

        # Fallback 1: period_cp C → P
        if query_info.get("period_cp") == "C":
            retry1 = dict(query_info)
            retry1["period_cp"] = "P"
            rows = _lookup(retry1)
            if rows:
                status = "exact_past" if len(rows) == 1 else "multiple_past"
                return {"status": status, "matches": rows, "query": retry1}

        # Fallback 2: period_variant 제거
        if query_info.get("period_variant"):
            retry2 = {k: v for k, v in query_info.items() if k != "period_variant"}
            rows = _lookup(retry2)
            if rows:
                return {"status": "partial_match", "matches": rows, "query": retry2}

        return {"status": "not_found", "matches": [], "query": query_info}

    def schema_info(self) -> dict:
        """DB에 뭐가 있는지 요약"""
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS n FROM facts")
            total = cur.fetchone()["n"]
            cur.execute(
                "SELECT corp_name, COUNT(*) AS n FROM facts GROUP BY corp_name"
            )
            corps = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT statement, report_type, COUNT(*) AS n FROM facts "
                "WHERE statement IS NOT NULL GROUP BY statement, report_type"
            )
            stmts = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT period_cp, period_scope, period_type, COUNT(*) AS n FROM facts "
                "GROUP BY period_cp, period_scope, period_type ORDER BY n DESC"
            )
            periods = [dict(r) for r in cur.fetchall()]
        return {"total": total, "corps": corps, "statements": stmts, "periods": periods}


if __name__ == "__main__":
    import sys
    facts_jsonl = sys.argv[1] if len(sys.argv) > 1 else "./processed/facts.jsonl"
    db_path = sys.argv[2] if len(sys.argv) > 2 else "./db/facts.db"

    print(f"Building DB: {facts_jsonl} → {db_path}")
    result = build_db(facts_jsonl, db_path)
    print(f"\n총 {result['total']}개 팩트 저장")
    print("\n기업별:")
    for corp, n in result["per_corp"]:
        print(f"  {corp}: {n}")
    print("\n재무제표별:")
    for stmt, rt, n in result["per_statement"]:
        print(f"  {stmt} ({rt}): {n}")

    print("\n" + "=" * 50)
    print("검증: FactRetriever로 조회 테스트")
    print("=" * 50)

    r = FactRetriever(db_path)

    # 테스트 1: NAVER 2025 반기말 연결 유동자산
    q1 = {
        "corp_name": "NAVER",
        "statement": "재무상태표",
        "report_type": "연결",
        "account_kr": "유동자산",
        "fiscal_year": 2025,
        "period_scope": "HY",
    }
    print(f"\n[1] {q1}")
    result1 = r.lookup_auto(q1)
    print(f"  → status={result1['status']}, {len(result1['matches'])}개 매칭")
    for m in result1["matches"]:
        print(f"    • {m['corp_name']} | {m['account_kr']} | {m['period_tag']} | {m['value_raw']}")

    # 테스트 2: LG에너지솔루션 연결 현금및현금성자산
    q2 = {
        "corp_name": "LG에너지솔루션",
        "statement": "재무상태표",
        "report_type": "연결",
        "account_kr": "현금및현금성자산",
        "fiscal_year": 2025,
        "period_scope": "HY",
    }
    print(f"\n[2] {q2}")
    result2 = r.lookup_auto(q2)
    print(f"  → status={result2['status']}, {len(result2['matches'])}개 매칭")
    for m in result2["matches"]:
        print(f"    • {m['corp_name']} | {m['account_kr']} | {m['period_tag']} | {m['value_raw']}")

    # 테스트 3: 동의어 테스트 ("매출" → "매출액" 정규화)
    q3 = {
        "corp_name": "NAVER",
        "statement": "포괄손익계산서",
        "report_type": "연결",
        "account_kr": "매출", 
        "fiscal_year": 2025,
        "period_scope": "HY",
        "period_variant": "A",
    }
    print(f"\n[3] {q3}")
    result3 = r.lookup_auto(q3)
    print(f"  → status={result3['status']}, {len(result3['matches'])}개 매칭")
    for m in result3["matches"]:
        print(f"    • {m['corp_name']} | {m['account_kr']} (norm={m['account_norm']}) | {m['period_tag']} | {m['value_raw']}")
