"""
generator.py — HCX-003 기반 답변 생성기

입력 케이스:
  1) fact_lookup: FactRetriever 결과(정확한 수치 1개) → 구조화 답변
  2) narrative:   RAGRetriever 결과(top-k 컨텍스트)  → 근거 기반 요약

환각 방지:
  - fact_lookup은 값·단위·출처가 명확하므로 LLM은 포맷팅만
  - narrative는 근거에 없는 내용 추측 금지 강제 프롬프트
"""

from __future__ import annotations

import os
import re
import json
import requests
from dataclasses import dataclass
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.documents import Document


# ==========================================
# HCX 설정
# ==========================================

CLOVA_API_KEY = os.environ.get("CLOVA_API_KEY", "")
CLOVA_URL = "https://clovastudio.stream.ntruss.com/testapp/v1/chat-completions/HCX-003"


def call_hcx(
    system_prompt: str,
    user_prompt: str,
    api_key: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 600,
    timeout: int = 30,
    max_retries: int = 3,
) -> tuple[str, Optional[str]]:
    """
    HCX-003 호출. 성공 시 (content, None), 실패 시 (fallback_msg, error_str) 반환
    
    429 (rate limit) 발생 시 exponential backoff로 재시도
    400 (context length exceeded) 발생 시 user_prompt 마지막을 트렁케이트 후 재시도
    """
    import time as _time
    
    key = api_key or CLOVA_API_KEY
    if not key:
        return "", "CLOVA_API_KEY 미설정"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    current_user_prompt = user_prompt
    
    for attempt in range(max_retries):
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": current_user_prompt},
            ],
            "topP": 0.8,
            "temperature": temperature,
            "maxTokens": max_tokens,
        }

        try:
            res = requests.post(CLOVA_URL, headers=headers, json=payload, timeout=timeout)
            res.raise_for_status()
            content = res.json()["result"]["message"]["content"]
            return content, None
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            body = ""
            try:
                body = e.response.text[:300] if e.response is not None else ""
            except Exception:
                pass
            
            # 429: rate limit → exponential backoff
            if status == 429 and attempt < max_retries - 1:
                wait_sec = 2 ** (attempt + 1)  # 2, 4, 8초
                print(f"  [HCX 429] {wait_sec}초 대기 후 재시도 ({attempt+1}/{max_retries})")
                _time.sleep(wait_sec)
                continue
            
            # 400 context length: prompt를 절반 줄이고 재시도
            if status == 400 and "Context length" in body and attempt < max_retries - 1:
                keep = int(len(current_user_prompt) * 0.7)
                current_user_prompt = current_user_prompt[:keep] + "\n...(중략)..."
                print(f"  [HCX 400 context] prompt 축약 후 재시도 ({attempt+1}/{max_retries})")
                continue
            
            # 에러 반환
            return "", f"{e} | response: {body}"
        except requests.RequestException as e:
            return "", str(e)
        except (KeyError, json.JSONDecodeError) as e:
            return "", f"응답 파싱 실패: {e}"
    
    return "", f"재시도 {max_retries}회 모두 실패"


# ==========================================
# 숫자 포맷팅
# ==========================================

def format_value_with_unit(value_raw: str, unit_hint: Optional[str]) -> str:
    if unit_hint:
        return f"{value_raw} {unit_hint}"
    return value_raw


def pretty_period_label(period_scope: Optional[str], period_type: Optional[str], period_cp: Optional[str]) -> str:
    if not period_scope:
        return ""
    scope_map = {"FY": "연간", "HY": "반기", "3Q": "3분기", "1Q": "1분기", "2Q": "2분기", "4Q": "4분기"}
    scope_kr = scope_map.get(period_scope, period_scope)
    type_kr = ""
    if period_type == "end" and period_scope != "FY":
        type_kr = "말"
    elif period_type == "during":
        type_kr = " 누적"
    cp_kr = "전기 " if period_cp == "P" else ""
    return f"{cp_kr}{scope_kr}{type_kr}".strip()


# ==========================================
# fact_lookup 답변 생성
# ==========================================

FACT_SYSTEM_PROMPT = """당신은 한국 기업 재무 공시 데이터 안내 전문가입니다.
사용자 질문과 데이터베이스에서 정확히 조회된 수치가 주어집니다.
조회 결과를 바탕으로 자연스러운 한국어 문장 한두 문장으로 답변하세요.

엄격한 규칙:
- 숫자·단위는 주어진 값 그대로 쓰세요. 변환하지 마세요.
- 조회된 값 외의 다른 수치나 해석을 추가하지 마세요.
- "약", "대략" 같은 표현 쓰지 마세요. 정확한 값을 말하세요.
- 답변 끝에 [출처: 파일명]을 덧붙이세요."""


def generate_fact_answer(
    query: str,
    fact_match: dict,
    query_info: Any,
    api_key: Optional[str] = None,
) -> str:
    """
    FactRetriever가 찾은 단일 매치를 자연어 답변
    """
    value_str = format_value_with_unit(fact_match["value_raw"], fact_match.get("unit_hint"))
    corp = fact_match.get("corp_name", "")
    account = fact_match.get("account_kr", "")
    period_tag = fact_match.get("period_tag", "")
    statement = fact_match.get("statement", "")
    report_type = fact_match.get("report_type", "")
    source = fact_match.get("source_file", "")
    
    # 기간
    period_label = pretty_period_label(
        getattr(query_info, "period_scope", None),
        getattr(query_info, "period_type", None),
        getattr(query_info, "period_cp", None),
    )

    user_prompt = f"""[사용자 질문]
{query}

[데이터베이스 조회 결과]
- 기업: {corp}
- 재무제표: {statement} ({report_type})
- 항목: {account}
- 기간: {period_label} (내부 태그: {period_tag})
- 값: {value_str}
- 출처 파일: {source}

위 조회 결과를 바탕으로 사용자 질문에 자연스럽게 답하세요."""

    answer, err = call_hcx(FACT_SYSTEM_PROMPT, user_prompt, api_key=api_key, max_tokens=300)
    if err:
        # LLM 실패 시 폴백
        return (
            f"{corp}의 {period_label} {statement}({report_type}) 기준 "
            f"{account}은(는) {value_str}입니다. [출처: {source}]"
        )
    return answer.strip()


# ==========================================
# narrative 답변 생성
# ==========================================

NARRATIVE_SYSTEM_PROMPT = """당신은 한국 기업 공시 자료를 분석해 사용자에게 설명하는 전문가입니다.
주어진 [공시 자료]만을 근거로 사용자 질문에 답하세요.

엄격한 규칙:
- 자료에 없는 내용을 추측하거나 일반 상식으로 메우지 마세요.
- 자료에 답이 없으면 "제공된 공시 자료에서 해당 정보를 찾을 수 없습니다"라고 답하세요.
- 답변은 3~5문장으로 간결하게 작성하세요.
- 구체적 사실(회사명, 제품명, 수치, 일자)은 자료에 등장한 대로 정확히 인용하세요.
- 답변 끝에 어느 섹션에서 가져온 정보인지 [출처: 섹션 경로] 형식으로 표시하세요."""


def generate_narrative_answer(
    query: str,
    documents: list["Document"],
    api_key: Optional[str] = None,
) -> str:
    """
    RAG 검색 결과로 답변 생성.
    """
    if not documents:
        return "제공된 공시 자료에서 해당 정보를 찾을 수 없습니다."

    context_parts = []
    for i, doc in enumerate(documents, 1):
        meta = doc.metadata
        path = meta.get("section_path_str", "")
        corp = meta.get("corp_name", "")
        year = meta.get("fiscal_year", "")
        body = doc.page_content
        body = re.sub(r"^\[.*?\]\n", "", body, count=1)
        context_parts.append(
            f"[자료 {i}] {corp} / {year}년 / {path}\n{body}"
        )
    context_str = "\n\n---\n\n".join(context_parts)

    user_prompt = f"""[사용자 질문]
{query}

[공시 자료]
{context_str}

위 [공시 자료]만을 근거로 사용자 질문에 답변하세요."""

    answer, err = call_hcx(
        NARRATIVE_SYSTEM_PROMPT, user_prompt, api_key=api_key,
        temperature=0.2, max_tokens=600,
    )
    if err:
        return f"답변 생성 중 오류가 발생했습니다: {err}"
    return answer.strip()


# ==========================================
# hybrid 답변 (fact + narrative)
# ==========================================

HYBRID_SYSTEM_PROMPT = """당신은 한국 기업 재무 공시를 분석하는 전문가입니다.
[확정 수치]와 [공시 서술 자료]를 함께 근거로 사용자 질문에 답하세요.

엄격한 규칙:
- 확정 수치는 변환/추정 없이 주어진 대로 쓰세요.
- 서술 자료의 내용 외에는 추측하지 마세요.
- 답변은 5문장 이내로 간결하게 작성하세요.
- 답변 끝에 [출처: ...]를 덧붙이세요."""


def generate_hybrid_answer(
    query: str,
    fact_matches: list[dict],
    documents: list["Document"],
    query_info: Any,
    api_key: Optional[str] = None,
) -> str:
    """
    fact + narrative 결과를 함께 써서 답변 생성
    """
    # fact 부분 구성
    fact_lines = []
    for m in fact_matches[:3]:
        value_str = format_value_with_unit(m["value_raw"], m.get("unit_hint"))
        fact_lines.append(
            f"- {m.get('corp_name')} {m.get('account_kr')} ({m.get('period_tag')}): {value_str}"
        )
    fact_str = "\n".join(fact_lines) if fact_lines else "(확정 수치 없음)"

    # narrative 부분 구성
    if documents:
        narr_parts = []
        for i, doc in enumerate(documents, 1):
            path = doc.metadata.get("section_path_str", "")
            body = re.sub(r"^\[.*?\]\n", "", doc.page_content, count=1)
            narr_parts.append(f"[자료 {i}] {path}\n{body[:1200]}")
        narr_str = "\n\n".join(narr_parts)
    else:
        narr_str = "(서술 자료 없음)"

    user_prompt = f"""[사용자 질문]
{query}

[확정 수치]
{fact_str}

[공시 서술 자료]
{narr_str}

두 종류 근거를 모두 활용해 답변하세요."""

    answer, err = call_hcx(HYBRID_SYSTEM_PROMPT, user_prompt, api_key=api_key, max_tokens=600)
    if err:
        return f"답변 생성 중 오류: {err}"
    return answer.strip()
