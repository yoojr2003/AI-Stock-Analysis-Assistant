"""
api_server.py — FastAPI 백엔드

엔드포인트:
  GET  /health                   - 서버 상태
  GET  /companies                - 기업 목록
  GET  /profile/{corp}           - 기업 프로파일 (KPI 8개)
  GET  /ratios/{corp}            - 재무 비율 7개
  GET  /timeseries/{corp}        - 시계열 (기본: 매출액)
  GET  /compare/years/{corp}     - 전년 대비 비교
  GET  /compare/companies        - 기업 간 비교
  GET  /suggested/{corp}         - 기업별 추천 질문
  POST /ask                      - Q&A (5가지 의도 지원)
  GET  /define/{term}            - 용어 사전 정의 조회
  GET  /search-terms             - 용어 부분 검색 (query: q=...)
  GET  /sectors                  - 업종 목록
  GET  /sector-compare/{sector}  - 업종 내 기업 비교
  GET  /interpret-ratios/{corp}  - 재무 비율 + 자동 해석
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, "/content")
sys.path.insert(0, "/content/src")

import analytics
import terms_dictionary
import interpreter

_pipeline = None
FACTS_DB_PATH = "/content/db/facts.db"


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pipeline import QAPipeline
        print("▶ QAPipeline 로딩 중...")
        _pipeline = QAPipeline(
            facts_db_path=FACTS_DB_PATH,
            rag_db_path="/content/db/chroma_rag",
            sections_jsonl="/content/processed/sections.jsonl",
            use_reranker=True,
        )
        print("QAPipeline 준비 완료")
    return _pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print("  DART Q&A + 분석 API 서버 시작 (v3)")
    print("=" * 60)
    print(f"  Facts DB: {FACTS_DB_PATH}")
    print(f"  Analytics + Terms + Interpreter: 로드됨")
    print(f"  용어 사전: {terms_dictionary.get_total_count()}개")
    print(f"  Pipeline: lazy (첫 /ask 요청 시 로드)")
    print("=" * 60)
    yield
    print("서버 종료")


app = FastAPI(
    title="DART 공시 Q&A + 분석 API",
    description="XBRL 팩트 DB 기반 기업 분석 + 용어 사전 + 업종 비교",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# 스키마
# ==========================================

class AskRequest(BaseModel):
    question: str = Field(..., description="사용자 질문")
    debug: bool = Field(False, description="디버그 정보 포함")
    session_id: Optional[str] = Field(None, description="챗봇 세션 ID (선택). 후속 질문 메모리 활용")


class Source(BaseModel):
    source_file: str
    corp_name: Optional[str] = ""
    fiscal_year: Optional[int] = 0
    section_path_str: Optional[str] = ""
    # 뉴스 출처용 (news_context 의도)
    title: Optional[str] = ""
    url: Optional[str] = ""
    type: Optional[str] = "document"  # "document" 또는 "news"


class AskResponse(BaseModel):
    question: str
    answer: str
    intent: str
    confidence: str
    sources: list[Source]
    elapsed_seconds: float


COMPANIES = [
    "삼성전자", "SK하이닉스", "현대자동차", "기아",
    "LG에너지솔루션", "LG화학", "NAVER",
    "삼성바이오로직스", "POSCO홀딩스", "셀트리온",
]


# ==========================================
# 기본 엔드포인트
# ==========================================

@app.get("/")
def root():
    return {
        "service": "DART 공시 Q&A + 분석 API",
        "version": "3.0.0",
        "docs": "/docs",
        "intents_supported": ["fact_lookup", "narrative", "hybrid", "definition", "general", "sector_compare"],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "facts_db": os.path.exists(FACTS_DB_PATH),
        "pipeline_loaded": _pipeline is not None,
        "terms_count": terms_dictionary.get_total_count(),
    }


@app.get("/companies")
def companies():
    return {"companies": COMPANIES, "count": len(COMPANIES)}


# ==========================================
# 기업 분석 엔드포인트
# ==========================================

@app.get("/profile/{corp}")
def profile(corp: str, year: int = Query(2025)):
    try:
        return analytics.get_profile(FACTS_DB_PATH, corp, year)
    except Exception as e:
        raise HTTPException(500, f"프로파일 조회 실패: {e}")


@app.get("/ratios/{corp}")
def ratios(corp: str, year: int = Query(2025)):
    try:
        return analytics.calculate_ratios(FACTS_DB_PATH, corp, year)
    except Exception as e:
        raise HTTPException(500, f"재무 비율 계산 실패: {e}")


@app.get("/timeseries/{corp}")
def timeseries(
    corp: str,
    statement: str = Query("포괄손익계산서"),
    account: str = Query("매출액"),
):
    try:
        return analytics.get_timeseries(FACTS_DB_PATH, corp, statement, account)
    except Exception as e:
        raise HTTPException(500, f"시계열 조회 실패: {e}")


@app.get("/compare/years/{corp}")
def compare_years(corp: str, year: int = Query(2025)):
    try:
        return analytics.compare_years(FACTS_DB_PATH, corp, year)
    except Exception as e:
        raise HTTPException(500, f"전년 대비 비교 실패: {e}")


@app.get("/compare/companies")
def compare_companies(
    corps: str = Query(..., description="쉼표 구분 기업명"),
    year: int = Query(2025),
):
    corp_list = [c.strip() for c in corps.split(",") if c.strip()]
    if len(corp_list) < 2:
        raise HTTPException(400, "최소 2개 기업 필요")
    try:
        return analytics.compare_companies(FACTS_DB_PATH, corp_list, year)
    except Exception as e:
        raise HTTPException(500, f"기업 비교 실패: {e}")


@app.get("/suggested/{corp}")
def suggested_questions(corp: str):
    questions = analytics.get_suggested_questions(corp)
    return {"corp_name": corp, "suggestions": questions}


# ==========================================
# 엔드포인트 — 용어 사전
# ==========================================

@app.get("/define/{term}")
def define_term(term: str):
    """용어 사전 정의 조회 (정확 매칭)."""
    result = terms_dictionary.lookup_term(term)
    if not result:
        # 부분 매칭으로 fallback
        partial = terms_dictionary.search_terms(term, limit=3)
        if partial:
            return {
                "matched": False,
                "exact": None,
                "suggestions": partial,
            }
        raise HTTPException(404, f"'{term}'을(를) 용어 사전에서 찾을 수 없습니다.")
    
    return {
        "matched": True,
        "exact": result,
        "formatted": terms_dictionary.format_term_answer(result),
    }


@app.get("/search-terms")
def search_terms(
    q: str = Query(..., min_length=1, description="검색 키워드"),
    limit: int = Query(5, ge=1, le=20),
):
    """용어 부분 검색."""
    results = terms_dictionary.search_terms(q, limit=limit)
    return {
        "query": q,
        "count": len(results),
        "results": results,
    }


@app.get("/terms/categories")
def list_categories():
    """모든 용어 카테고리."""
    return {"categories": terms_dictionary.get_all_categories()}


@app.get("/terms/category/{category}")
def get_category_terms(category: str):
    """카테고리별 용어 목록."""
    results = terms_dictionary.get_terms_by_category(category)
    return {"category": category, "count": len(results), "terms": results}


# ==========================================
# 엔드포인트 — 업종 비교
# ==========================================

@app.get("/sectors")
def list_sectors():
    """업종 목록 + 각 업종의 기업."""
    sectors = {}
    for sector, corps in analytics.SECTOR_MAPPING.items():
        if sector == "전체":
            continue
        sectors[sector] = {
            "companies": corps,
            "count": len(corps),
        }
    return {"sectors": sectors}


@app.get("/sector-compare/{sector}")
def sector_compare(
    sector: str,
    year: int = Query(2025),
):
    """업종 내 기업 비교."""
    try:
        result = analytics.compare_sector(FACTS_DB_PATH, sector, year)
        if "error" in result:
            raise HTTPException(404, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"업종 비교 실패: {e}")


# ==========================================
# 엔드포인트 — 비율 해석
# ==========================================

@app.get("/interpret-ratios/{corp}")
def interpret_ratios_endpoint(corp: str, year: int = Query(2025)):
    """
    재무 비율 + 자동 해석 결합.
    
    반환:
      - ratios_data: 7개 비율 raw 값
      - interpretations: 각 비율 평가 (등급/해석/아이콘)
      - summary: 종합 평가 텍스트
    """
    try:
        # 1. 비율 계산
        ratios_data = analytics.calculate_ratios(FACTS_DB_PATH, corp, year)
        
        # 2. 해석
        interpretations = interpreter.interpret_ratios(ratios_data)
        
        # 3. YoY 데이터 (종합 평가용)
        try:
            yoy = analytics.get_profile(FACTS_DB_PATH, corp, year)
        except Exception:
            yoy = {}
        
        # 4. 종합 평가
        summary = interpreter.generate_summary(interpretations, yoy)
        
        # 응답 구성
        return {
            "corp_name": corp,
            "year": year,
            "ratios": ratios_data.get("ratios", {}),
            "interpretations": interpreter.format_interpretations(interpretations),
            "summary": summary,
        }
    except Exception as e:
        raise HTTPException(500, f"비율 해석 실패: {e}")


# ==========================================
# Q&A
# ==========================================

@app.get("/session/{session_id}")
def session_info(session_id: str):
    """세션 메모리 상태 조회"""
    try:
        from chat_session import get_global_manager
        session = get_global_manager().get(session_id)
        if not session:
            return {"session_id": session_id, "exists": False}
        return {"exists": True, **session.get_context_summary()}
    except Exception as e:
        raise HTTPException(500, f"세션 조회 실패: {e}")


@app.post("/session/{session_id}/reset")
def session_reset(session_id: str):
    """세션 메모리 초기화"""
    try:
        from chat_session import get_global_manager
        ok = get_global_manager().reset(session_id)
        return {"session_id": session_id, "reset": ok}
    except Exception as e:
        raise HTTPException(500, f"세션 리셋 실패: {e}")


@app.delete("/session/{session_id}")
def session_delete(session_id: str):
    """세션 완전 삭제"""
    try:
        from chat_session import get_global_manager
        ok = get_global_manager().delete(session_id)
        return {"session_id": session_id, "deleted": ok}
    except Exception as e:
        raise HTTPException(500, f"세션 삭제 실패: {e}")


@app.post("/route")
def route_endpoint(req: AskRequest):
    """
    라우팅만 수행
    
    Returns:
        {"intent": "...", "corp_name": "...", "fiscal_year": ..., ...}
    """
    if not req.question or len(req.question.strip()) < 1:
        raise HTTPException(400, "질문이 비어있습니다")
    
    try:
        from router import route
        qi = route(req.question, use_llm=False)
        return qi.to_dict()
    except Exception as e:
        raise HTTPException(500, f"라우팅 실패: {e}")


@app.get("/news/{corp}")
def news_endpoint(corp: str, n: int = 5, sort: str = "date"):
    """
    기업 최근 뉴스 검색
    
    Args:
        corp: 기업명
        n: 1-10 (default 5)
        sort: "date" (최신) 또는 "sim" (관련도)
    """
    try:
        from news_fetcher import fetch_news
        news = fetch_news(corp, n=min(max(n, 1), 10), sort=sort)
        return {
            "corp_name": corp,
            "count": len(news),
            "items": news,
        }
    except Exception as e:
        raise HTTPException(500, f"뉴스 검색 실패: {e}")


@app.get("/report/pdf/{corp}")
def report_pdf_endpoint(
    corp: str,
    year: int = 2025,
    include_news: bool = True,
    include_sector: bool = True,
):
    """
    기업 분석 PDF 보고서 생성 후 다운로드
    
    Args:
        corp: 기업명
        year: 회계연도 (default 2025)
        include_news: 최근 뉴스 섹션
        include_sector: 업종 비교 섹션
    
    Returns:
        application/pdf 바이너리
    """
    from fastapi.responses import Response as FastAPIResponse
    try:
        from pdf_report import generate_company_report
        pdf_bytes = generate_company_report(
            corp_name=corp,
            year=year,
            facts_db=FACTS_DB_PATH,
            api_base="http://localhost:8000",
            include_news=include_news,
            include_sector=include_sector,
        )
        
        # 파일명 (한글 → URL 인코딩)
        from urllib.parse import quote
        filename = f"{corp}_{year}_report.pdf"
        filename_encoded = quote(filename)
        
        return FastAPIResponse(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}",
            },
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"PDF 생성 실패: {str(e)[:200]}")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not req.question or len(req.question.strip()) < 3:
        raise HTTPException(400, "질문이 너무 짧습니다")
    
    try:
        p = get_pipeline()
        resp = p.ask(req.question, include_debug=req.debug, session_id=req.session_id)
        
        return AskResponse(
            question=req.question,
            answer=resp.answer,
            intent=resp.intent,
            confidence=resp.confidence,
            sources=[
                Source(
                    source_file=s.get("source_file", ""),
                    corp_name=s.get("corp_name", ""),
                    fiscal_year=s.get("fiscal_year", 0),
                    section_path_str=s.get("section_path_str", ""),
                    title=s.get("title", ""),
                    url=s.get("url", ""),
                    type=s.get("type", "document"),
                )
                for s in resp.sources
            ],
            elapsed_seconds=resp.elapsed_seconds,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"처리 중 오류: {str(e)[:200]}")


# ==========================================
# 실행
# ==========================================

def run_with_ngrok(port: int = 8000):
    try:
        from pyngrok import ngrok
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        print("⚠️ pyngrok/nest_asyncio 미설치")
        return
    
    for t in ngrok.get_tunnels():
        ngrok.disconnect(t.public_url)
    
    public_url = ngrok.connect(port)
    print(f"\n{'=' * 60}")
    print(f"  🌐 API 공개 URL: {public_url}")
    print(f"  🔗 Swagger: {public_url}/docs")
    print(f"{'=' * 60}\n")
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-ngrok", action="store_true")
    args = parser.parse_args()
    
    if args.no_ngrok:
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        run_with_ngrok(args.port)
