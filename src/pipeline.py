"""
pipeline.py — 전체 Q&A 시스템의 통합 인터페이스

흐름:
  사용자 쿼리
    ↓
  [router.route()] intent + 엔티티 추출
    ↓
  [intent 분기]
    - fact_lookup → FactRetriever.lookup_auto() → generate_fact_answer()
    - narrative   → RAGRetriever.retrieve()    → generate_narrative_answer()
    - hybrid      → 둘 다 실행             → generate_hybrid_answer()
    ↓
  Response(answer, sources, confidence, ...)
"""

from __future__ import annotations

import os
import time
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Any

from router import route, QueryInfo
from build_fact_db import FactRetriever
from generator import (
    generate_fact_answer,
    generate_narrative_answer,
    generate_hybrid_answer,
)


# ==========================================
# 응답 객체
# ==========================================

@dataclass
class Response:
    """파이프라인 최종 출력"""
    answer: str
    intent: str
    confidence: str                   # "high" / "medium" / "low" / "not_found"
    sources: list[dict] = field(default_factory=list)
    query_info: dict = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    debug: Optional[dict] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if d.get("debug") is None:
            d.pop("debug", None)
        return d

    def __str__(self) -> str:
        s = f"[{self.intent} / {self.confidence} / {self.elapsed_seconds:.2f}s]\n"
        s += self.answer
        if self.sources:
            s += "\n\n출처:"
            for src in self.sources[:3]:
                s += f"\n  · {src.get('source_file') or src.get('section_path_str', '')}"
        return s


# ==========================================
# 파이프라인 클래스
# ==========================================

class QAPipeline:
    """
    통합 Q&A 파이프라인. 한 번 초기화 후 여러 쿼리 처리 가능
    """

    def __init__(
        self,
        facts_db_path: str = "./db/facts.db",
        rag_db_path: str = "./db/chroma_rag",
        sections_jsonl: str = "./processed/sections.jsonl",
        embedding_provider: str = "openai",
        embedding_model: Optional[str] = None,
        use_reranker: bool = True,
        clova_api_key: Optional[str] = None,
        use_llm_router: bool = False,
    ):
        self.clova_api_key = clova_api_key or os.environ.get("CLOVA_API_KEY", "")
        self.use_llm_router = use_llm_router
        self.facts_db_path = facts_db_path

        self.fact_retriever = FactRetriever(facts_db_path)

        # RAGRetriever는 lazy init — Chroma 로드 비용 큼
        self._rag_retriever = None
        self._rag_kwargs = dict(
            db_path=rag_db_path,
            sections_jsonl=sections_jsonl,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            use_reranker=use_reranker,
        )

    @property
    def rag_retriever(self):
        if self._rag_retriever is None:
            from rag_retriever import RAGRetriever
            self._rag_retriever = RAGRetriever(**self._rag_kwargs)
        return self._rag_retriever

    # ------------------------------
    # 경로별 처리
    # ------------------------------

    def _handle_fact(self, query: str, qi: QueryInfo) -> Response:
        """fact_lookup 경로"""
        # FactRetriever에 전달할 인자
        query_info_dict = {k: v for k, v in {
            "corp_name": qi.corp_name,
            "statement": qi.statement,
            "report_type": qi.report_type,
            "account_kr": qi.account_kr,
            "fiscal_year": qi.fiscal_year,
            "period_cp": qi.period_cp,
            "period_scope": qi.period_scope,
            "period_type": qi.period_type,
            "period_variant": qi.period_variant,
        }.items() if v is not None}

        result = self.fact_retriever.lookup_auto(query_info_dict)
        matches = result.get("matches", [])

        if result["status"] == "not_found" or not matches:
            return Response(
                answer="제공된 공시 자료에서 해당 수치를 찾을 수 없습니다. 기업명·연도·계정명을 다시 확인해주세요.",
                intent="fact_lookup",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
                debug={"fact_status": result["status"], "query": query_info_dict},
            )

        # exact match이면 high, multiple이면 medium
        confidence = "high" if result["status"] == "exact" else "medium"
        chosen = matches[0]  # 여러 개면 첫 번째

        answer = generate_fact_answer(query, chosen, qi, api_key=self.clova_api_key)

        sources = [{
            "source_file": chosen.get("source_file"),
            "account_kr": chosen.get("account_kr"),
            "period_tag": chosen.get("period_tag"),
            "value_raw": chosen.get("value_raw"),
            "unit_hint": chosen.get("unit_hint"),
        }]

        return Response(
            answer=answer,
            intent="fact_lookup",
            confidence=confidence,
            sources=sources,
            query_info=qi.to_dict(),
            debug={"fact_status": result["status"], "n_matches": len(matches)},
        )

    def _handle_narrative(self, query: str, qi: QueryInfo) -> Response:
        """narrative 경로 (RAG)"""
        result = self.rag_retriever.retrieve(
            query=query,
            corp_name=qi.corp_name,
            fiscal_year=qi.fiscal_year,
            k=3,
            candidate_k=15,
        )

        docs = result.documents
        if not docs:
            return Response(
                answer="제공된 공시 자료에서 해당 정보를 찾을 수 없습니다.",
                intent="narrative",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
                debug={"filter_applied": result.filter_applied, "filter_relaxed": result.filter_relaxed},
            )

        answer = generate_narrative_answer(query, docs, api_key=self.clova_api_key)

        # 신뢰도 판정
        if result.filter_relaxed:
            confidence = "low"
        elif result.reranker_used and result.num_candidates >= 3:
            confidence = "high"
        else:
            confidence = "medium"

        sources = []
        for d in docs:
            sources.append({
                "source_file": d.metadata.get("source_file"),
                "section_path_str": d.metadata.get("section_path_str"),
                "corp_name": d.metadata.get("corp_name"),
                "fiscal_year": d.metadata.get("fiscal_year"),
            })

        return Response(
            answer=answer,
            intent="narrative",
            confidence=confidence,
            sources=sources,
            query_info=qi.to_dict(),
            debug={
                "filter_applied": result.filter_applied,
                "filter_relaxed": result.filter_relaxed,
                "num_candidates": result.num_candidates,
                "reranker_used": result.reranker_used,
            },
        )

    def _handle_hybrid(self, query: str, qi: QueryInfo) -> Response:
        """hybrid 경로 (fact + narrative)"""
        # fact 먼저
        query_info_dict = {k: v for k, v in {
            "corp_name": qi.corp_name, "statement": qi.statement,
            "report_type": qi.report_type, "account_kr": qi.account_kr,
            "fiscal_year": qi.fiscal_year, "period_cp": qi.period_cp,
            "period_scope": qi.period_scope, "period_type": qi.period_type,
            "period_variant": qi.period_variant,
        }.items() if v is not None}

        fact_result = self.fact_retriever.lookup_auto(query_info_dict)
        fact_matches = fact_result.get("matches", [])

        # narrative 검색
        rag_result = self.rag_retriever.retrieve(
            query=query,
            corp_name=qi.corp_name,
            fiscal_year=qi.fiscal_year,
            k=3,
            candidate_k=15,
        )
        docs = rag_result.documents

        # not_found
        if not fact_matches and not docs:
            return Response(
                answer="제공된 공시 자료에서 해당 정보를 찾을 수 없습니다.",
                intent="hybrid",
                confidence="not_found",
                query_info=qi.to_dict(),
            )

        answer = generate_hybrid_answer(
            query, fact_matches, docs, qi, api_key=self.clova_api_key
        )

        # 신뢰도
        if fact_matches and docs:
            confidence = "high"
        else:
            confidence = "medium"

        sources = []
        for m in fact_matches[:2]:
            sources.append({
                "type": "fact",
                "source_file": m.get("source_file"),
                "account_kr": m.get("account_kr"),
                "value_raw": m.get("value_raw"),
                "unit_hint": m.get("unit_hint"),
            })
        for d in docs[:2]:
            sources.append({
                "type": "narrative",
                "source_file": d.metadata.get("source_file"),
                "section_path_str": d.metadata.get("section_path_str"),
            })

        return Response(
            answer=answer,
            intent="hybrid",
            confidence=confidence,
            sources=sources,
            query_info=qi.to_dict(),
        )

    # ------------------------------
    # 핸들러: definition / general / sector_compare
    # ------------------------------
    
    def _handle_definition(self, query: str, qi: QueryInfo) -> Response:
        """용어 사전 조회 — LLM 호출 없이 사전 직접 응답"""
        try:
            from terms_dictionary import lookup_term, search_terms, format_term_answer
        except ImportError:
            return Response(
                answer="용어 사전 모듈이 설치되지 않았습니다.",
                intent="definition",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
            )
        
        term_query = qi.term_query or query
        result = lookup_term(term_query)
        
        # 매칭 실패 → 부분 검색
        if not result:
            partial = search_terms(term_query, limit=3)
            if partial:
                result = partial[0]
                others = ", ".join(p["term"] for p in partial[1:])
                answer = format_term_answer(result)
                if others:
                    answer += f"\n\n_관련 용어 후보: {others}_"
                
                return Response(
                    answer=answer,
                    intent="definition",
                    confidence="medium",
                    sources=[{"source_file": "terms_dictionary",
                              "section_path_str": f"용어 사전 / {result['category']}"}],
                    query_info=qi.to_dict(),
                )
            else:
                return Response(
                    answer=f"'{term_query}'에 대한 정의를 용어 사전에서 찾을 수 없습니다. "
                           f"다른 표현으로 다시 질문해보세요.",
                    intent="definition",
                    confidence="not_found",
                    sources=[],
                    query_info=qi.to_dict(),
                )
        
        # 매칭 성공
        return Response(
            answer=format_term_answer(result),
            intent="definition",
            confidence="high",
            sources=[{"source_file": "terms_dictionary",
                      "section_path_str": f"용어 사전 / {result['category']}",
                      "corp_name": "", "fiscal_year": 0}],
            query_info=qi.to_dict(),
        )
    
    def _handle_general(self, query: str, qi: QueryInfo) -> Response:
        """
        일반 질문 — 시스템 데이터 외 영역. HCX 일반 지식으로 답변
        명시적 면책: '시스템 외부 일반 지식 기반' 표시
        """
        from generator import call_hcx
        
        system_prompt = (
            "당신은 한국어 투자/금융 일반 상담 비서입니다. "
            "사용자 질문이 일반적 투자 지식·전략·용어에 관련된 것이라면 친절하게 답변하세요. "
            "단, 다음 원칙을 지키세요:\n"
            "1. 특정 종목 매수/매도를 직접 추천하지 않습니다.\n"
            "2. 미래 주가 예측은 하지 않습니다.\n"
            "3. 정보가 불확실하면 솔직히 모른다고 답변하세요.\n"
            "4. 답변은 200자 이내로 간결하게 작성하세요."
        )
        
        try:
            answer, err = call_hcx(
                system_prompt=system_prompt,
                user_prompt=query,
                api_key=self.clova_api_key,
            )
            if err or not answer:
                # 에러 원인 명시
                err_detail = err if err else "빈 답변 반환"
                if "API_KEY" in str(err_detail) or not self.clova_api_key:
                    answer = (
                        "이 질문은 시스템의 공시 데이터 범위를 벗어난 일반 질문입니다.\n\n"
                        "일반 답변을 생성하려면 CLOVA_API_KEY가 필요합니다. "
                        "구체적인 기업·재무 지표에 대한 질문을 하시면 데이터 기반으로 정확하게 답변드릴 수 있습니다.\n\n"
                        f"_(내부 정보: {err_detail[:100]})_"
                    )
                else:
                    answer = (
                        f"답변 생성에 실패했습니다 (사유: {err_detail[:120]}).\n\n"
                        "이 질문은 시스템의 공시 데이터 범위를 벗어난 일반 질문입니다. "
                        "특정 기업의 공시 자료에 대해 질문해보세요."
                    )
                confidence = "low"
            else:
                # 답변에 면책 추가
                answer = (
                    f"일반 지식 기반 답변 (DART 공시 자료 기반 아님)\n\n"
                    f"{answer}\n\n"
                    f"_더 정확한 분석을 위해 특정 기업의 공시 자료에 대해 질문해보세요._"
                )
                confidence = "medium"
        except Exception as e:
            answer = f"답변 생성 중 오류: {e}"
            confidence = "not_found"
        
        return Response(
            answer=answer,
            intent="general",
            confidence=confidence,
            sources=[],
            query_info=qi.to_dict(),
        )
    
    def _handle_news_context(self, query: str, qi: QueryInfo) -> Response:
        """
        뉴스 컨텍스트: 회사명 + 최근 동향 키워드
        
        흐름:
          1. 네이버 뉴스 API에서 최근 뉴스 5개 검색
          2. 공시 fact DB에서 최신 KPI (매출, 영업이익) 가져옴 (참고용)
          3. LLM (HCX)에 뉴스 + fact 통합 프롬프트 → 답변
          4. CoT 프롬프트로 환각 방지: 뉴스 출처 명시 + 추측 금지
        """
        if not qi.corp_name:
            return Response(
                answer="기업명을 명확히 알려주세요. 예: '삼성전자 최근 동향'",
                intent="news_context",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
            )
        
        # 1. 뉴스 검색
        try:
            from news_fetcher import fetch_news, format_news_for_llm
        except ImportError:
            return Response(
                answer="뉴스 모듈이 설치되지 않았습니다.",
                intent="news_context",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
            )
        
        news_list = fetch_news(qi.corp_name, n=5, sort="date")
        
        if not news_list:
            return Response(
                answer=(
                    f"{qi.corp_name}의 최근 뉴스를 가져오지 못했습니다. "
                    "잠시 후 다시 시도해주세요."
                ),
                intent="news_context",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
            )
        
        # 2. 공시 fact
        fact_context = ""
        try:
            import analytics
            # 최신 연도 자동 추정 (2025 → 2024 → 2023 순서)
            for year in (2025, 2024, 2023):
                profile = analytics.get_profile(self.facts_db_path, qi.corp_name, year)
                metrics = profile.get("metrics", {})
                if metrics.get("매출액"):
                    rev = metrics["매출액"]["display"]
                    op = (metrics.get("영업이익") or {}).get("display", "N/A")
                    ni = (metrics.get("당기순이익") or {}).get("display", "N/A")
                    fact_context = (
                        f"최근 공시 데이터 ({year}년):\n"
                        f"  - 매출액: {rev}\n"
                        f"  - 영업이익: {op}\n"
                        f"  - 당기순이익: {ni}\n"
                    )
                    break
        except Exception:
            pass 
        
        # 3. LLM 프롬프트 (CoT + 환각 방지)
        news_text = format_news_for_llm(news_list, max_items=5)
        
        system_prompt = (
            "당신은 한국어 기업 분석 비서입니다. "
            "사용자에게 뉴스와 공시 데이터를 통합해 답변합니다. "
            "다음 규칙을 반드시 지키세요:\n"
            "1. 뉴스에서 가져온 정보는 반드시 [뉴스 N] 형식으로 출처를 표시합니다.\n"
            "2. 공시 데이터는 객관적 사실로, 뉴스는 동향 참고로 명확히 구분합니다.\n"
            "3. 뉴스에 없는 내용을 추측하거나 만들어내지 않습니다.\n"
            "4. 투자 권유나 매매 추천은 하지 않습니다.\n"
            "5. 답변 마지막에는 '※ 뉴스 기반 답변으로 공시 자료가 아닙니다' 면책을 붙입니다."
        )
        
        user_prompt = f"""질문: {query}

[참고 정보]

{fact_context if fact_context else '(최근 공시 데이터 없음)'}

최근 뉴스 (네이버 검색):
{news_text}

위 정보를 바탕으로 한국어로 명확하고 간결하게 답변하세요.
공시 데이터(객관적 숫자)와 뉴스(동향)를 분리해서 설명하세요.
"""
        
        # 4. HCX 호출
        try:
            from generator import call_hcx
            answer, err = call_hcx(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=self.clova_api_key,
            )
            if err:
                # HCX 실패 시 뉴스 목록만 반환
                answer = self._format_news_fallback(qi.corp_name, news_list)
        except Exception as e:
            answer = self._format_news_fallback(qi.corp_name, news_list)
        
        # 5. 출처
        sources = []
        for i, n in enumerate(news_list[:5], 1):
            sources.append({
                "type": "news",
                "index": i,
                "title": n.get("title", ""),
                "source_file": f"{n.get('source', '')} | {n.get('pub_date_relative', '')}",
                "url": n.get("url", ""),
            })
        
        return Response(
            answer=answer,
            intent="news_context",
            confidence="medium",
            sources=sources,
            query_info=qi.to_dict(),
        )
    
    @staticmethod
    def _format_news_fallback(corp: str, news_list: list) -> str:
        """LLM 실패 시 뉴스 리스트 기반 폴백 답변"""
        if not news_list:
            return f"{corp}의 최근 뉴스를 가져오지 못했습니다."
        
        lines = [f"📰 {corp}의 최근 주요 뉴스 ({len(news_list)}개)\n"]
        for i, n in enumerate(news_list[:5], 1):
            title = n.get("title", "")
            date = n.get("pub_date_relative", "")
            source = n.get("source", "")
            lines.append(f"{i}. [{date}, {source}] {title}")
        
        lines.append("\n※ 뉴스 기반 답변으로 공시 자료가 아닙니다.")
        return "\n".join(lines)
        """업종 내 기업 비교"""
        try:
            import analytics
        except ImportError:
            return Response(
                answer="분석 모듈이 설치되지 않았습니다.",
                intent="sector_compare",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
            )
        
        sector = qi.sector_name
        if not sector:
            return Response(
                answer="업종명을 인식하지 못했습니다. 예: '반도체 업종 비교'",
                intent="sector_compare",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
            )
        
        year = qi.fiscal_year or 2025
        
        try:
            result = analytics.compare_sector(self.facts_db_path, sector, year=year)
        except Exception as e:
            return Response(
                answer=f"업종 비교 중 오류: {e}",
                intent="sector_compare",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
            )
        
        if "error" in result:
            return Response(
                answer=result["error"],
                intent="sector_compare",
                confidence="not_found",
                sources=[],
                query_info=qi.to_dict(),
            )
        
        # 답변 텍스트 구성
        lines = [f"**{sector} 업종 비교 ({year}년 기준)**\n"]
        
        if result.get("note"):
            lines.append(result["note"])
            lines.append("")
        
        # 각 기업 핵심 비율
        lines.append("**기업별 주요 재무 비율**\n")
        for r in result["rankings"]:
            corp = r["corp_name"]
            ratios = r["ratios"]
            opm = ratios.get("영업이익률", {}).get("display", "N/A")
            netm = ratios.get("순이익률", {}).get("display", "N/A")
            roe = ratios.get("ROE", {}).get("display", "N/A")
            roa = ratios.get("ROA", {}).get("display", "N/A")
            debt = ratios.get("부채비율", {}).get("display", "N/A")
            
            lines.append(
                f"• **{corp}** — 영업이익률: {opm}, 순이익률: {netm}, "
                f"ROE: {roe}, ROA: {roa}, 부채비율: {debt}"
            )
        
        # 부문별 1위
        winners = result.get("winner", {})
        if winners and len(result["companies"]) >= 2:
            lines.append("")
            lines.append("**🏆 부문별 우수 기업**\n")
            if winners.get("종합_수익성"):
                lines.append(f"• 종합 수익성: **{winners['종합_수익성']}**")
            if winners.get("영업이익률"):
                lines.append(f"• 영업이익률 1위: {winners['영업이익률']}")
            if winners.get("ROE"):
                lines.append(f"• ROE 1위: {winners['ROE']}")
            if winners.get("부채비율"):
                lines.append(f"• 재무 안정성 1위 (부채비율 최저): {winners['부채비율']}")
        
        answer = "\n".join(lines)
        
        # 출처
        sources = [
            {"source_file": f"facts.db (XBRL)", "corp_name": c,
             "fiscal_year": year, "section_path_str": "재무 비율 자동 계산"}
            for c in result["companies"]
        ]
        
        return Response(
            answer=answer,
            intent="sector_compare",
            confidence="high",
            sources=sources,
            query_info=qi.to_dict(),
        )

    # ------------------------------
    # 공개 API
    # ------------------------------

    def ask(self, query: str, include_debug: bool = False,
            session_id: Optional[str] = None) -> Response:
        """
        질문 하나 처리
        
        Args:
            query: 사용자 질문
            include_debug: 디버그 정보 포함 여부
            session_id: 챗봇 세션 ID (선택). 제공 시 후속 질문 메모리 활용.
        """
        start = time.time()

        # 1: 라우터
        qi = route(query, use_llm=self.use_llm_router, api_key=self.clova_api_key)
        
        # 1b: 세션 메모리 보강
        memory_used = False
        if session_id:
            try:
                from chat_session import get_global_manager
                from router import classify_intent_rule
                session = get_global_manager().get_or_create(session_id)
                
                # 메모리로 query 보강 (corp_name, year 등 후속 질문 해결)
                qi_before = (qi.corp_name, qi.fiscal_year, qi.account_kr)
                qi = session.resolve_query(qi, query)
                qi_after = (qi.corp_name, qi.fiscal_year, qi.account_kr)
                memory_used = qi_before != qi_after
                
                # 메모리로 corp이 채워졌으면 intent 재분류
                # 이전엔 corp 없어서 general로 분류된 케이스를 fact/narrative로 바로잡기
                if memory_used and qi.intent == "general" and qi.corp_name:
                    qi.intent = classify_intent_rule(qi, query)
                    # account가 메모리에서 추론됐거나 새로 잡혔으면 fact_lookup 유력
                    # narrative 키워드 있으면 narrative로
            except Exception as e:
                # 메모리 실패해도 일반 흐름 진행
                pass

        # 2: intent 분기
        if qi.intent == "fact_lookup":
            resp = self._handle_fact(query, qi)
        elif qi.intent == "narrative":
            resp = self._handle_narrative(query, qi)
        elif qi.intent == "hybrid":
            resp = self._handle_hybrid(query, qi)
        elif qi.intent == "definition":
            resp = self._handle_definition(query, qi)
        elif qi.intent == "general":
            resp = self._handle_general(query, qi)
        elif qi.intent == "sector_compare":
            resp = self._handle_sector_compare(query, qi)
        elif qi.intent == "news_context":
            resp = self._handle_news_context(query, qi)
        else:
            # unknown - narrative로 시도
            resp = self._handle_narrative(query, qi)
            resp.intent = "unknown_fallback_narrative"

        resp.elapsed_seconds = time.time() - start
        
        # 3: 세션 메모리 저장
        if session_id:
            try:
                from chat_session import get_global_manager
                session = get_global_manager().get_or_create(session_id)
                session.add_turn(query, qi, resp.answer or "")
                
                if not resp.debug:
                    resp.debug = {}
                resp.debug["memory_used"] = memory_used
                resp.debug["session_id"] = session_id
                resp.debug["turn_count"] = len(session.history)
            except Exception:
                pass

        if not include_debug:
            resp.debug = None

        return resp

    def ask_batch(self, queries: list[str]) -> list[Response]:
        """여러 쿼리 순차 처리."""
        return [self.ask(q) for q in queries]


# ==========================================
# CLI
# ==========================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--facts-db", default="./db/facts.db")
    parser.add_argument("--rag-db", default="./db/chroma_rag")
    parser.add_argument("--sections", default="./processed/sections.jsonl")
    parser.add_argument("--query", help="단일 질문 실행")
    parser.add_argument("--eval", action="store_true", help="eval_data 전체 실행")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--json", action="store_true", help="Response를 JSON으로 출력")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    pipeline = QAPipeline(
        facts_db_path=args.facts_db,
        rag_db_path=args.rag_db,
        sections_jsonl=args.sections,
        use_reranker=not args.no_rerank,
    )

    if args.query:
        resp = pipeline.ask(args.query, include_debug=args.debug)
        if args.json:
            print(json.dumps(resp.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(resp)
    elif args.eval:
        import sys
        sys.path.insert(0, ".")
        from eval_data import eval_dataset

        print(f"총 {len(eval_dataset)}개 질문 처리 시작\n")
        results = []
        for i, item in enumerate(eval_dataset, 1):
            q = item["question"]
            gt = item["ground_truth"]
            resp = pipeline.ask(q)
            
            print(f"[{i}/{len(eval_dataset)}] [{resp.intent}/{resp.confidence}/{resp.elapsed_seconds:.1f}s]")
            print(f"  Q: {q[:80]}")
            print(f"  A: {resp.answer[:200]}")
            print(f"  GT: {gt[:100]}")
            print()
            
            results.append({
                "question": q, "ground_truth": gt,
                "answer": resp.answer, "intent": resp.intent,
                "confidence": resp.confidence, "sources": resp.sources,
                "elapsed": resp.elapsed_seconds,
            })
            
            # HCX rate limit 예방
            # fact_lookup도 간격
            if i < len(eval_dataset):
                time.sleep(1.5)
        
        # 요약
        from collections import Counter
        intents = Counter(r["intent"] for r in results)
        confs = Counter(r["confidence"] for r in results)
        print("\n=== 요약 ===")
        print(f"Intent 분포: {dict(intents)}")
        print(f"Confidence 분포: {dict(confs)}")
        print(f"평균 응답 시간: {sum(r['elapsed'] for r in results)/len(results):.2f}s")
        
        # 결과 저장
        out_path = "./pipeline_eval_results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {out_path}")
    else:
        # 대화형
        print("대화형 모드 (종료: 'quit' 또는 Ctrl+C)")
        print("-" * 60)
        try:
            while True:
                q = input("\n질문> ").strip()
                if q.lower() in {"quit", "exit", "q"}:
                    break
                if not q:
                    continue
                resp = pipeline.ask(q, include_debug=args.debug)
                print(f"\n{resp}")
        except (KeyboardInterrupt, EOFError):
            print("\n종료")
