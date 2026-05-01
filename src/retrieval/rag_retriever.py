"""
rag_retriever.py — RAG 경로의 검색 엔진

역할:
  라우터가 intent=narrative로 분류한 쿼리에 대해,
  최종적으로 LLM에 전달할 top-k 컨텍스트 Document를 반환.

파이프라인:
  1) 메타 필터링 (Chroma where 절): corp_name, fiscal_year로 사전 축소
  2) 하이브리드 검색 (top-10): BM25(0.4) + Vector(0.6) 앙상블
  3) 리랭커 (top-3): cross-encoder로 정밀 재정렬

fallback:
  메타 필터가 너무 엄격해 결과 0개면 필터 완화 재시도
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Optional, Any
from pathlib import Path

from langchain_core.documents import Document
from langchain_chroma import Chroma


# ==========================================
# 데이터 클래스
# ==========================================

@dataclass
class RetrievalResult:
    """rag_retriever 출력 단위."""
    documents: list[Document]       # top-k 최종 문서
    raw_candidates: list[Document]  # 리랭킹 전 후보
    filter_applied: dict            # 실제 적용된 메타 필터
    filter_relaxed: bool            # fallback
    num_candidates: int             # 후보 개수
    reranker_used: bool             # 리랭커 적용 여부


# ==========================================
# 메인 검색기
# ==========================================

class RAGRetriever:
    """
    하이브리드 검색 + 리랭커.
    사용 예:
        r = RAGRetriever(db_path="./db/chroma_rag", sections_jsonl="./processed/sections.jsonl")
        result = r.retrieve(query="현대차 연구개발 성과", corp_name="현대차", k=3)
        for doc in result.documents:
            print(doc.page_content, doc.metadata)
    """

    def __init__(
        self,
        db_path: str = "./db/chroma_rag",
        sections_jsonl: str = "./processed/sections.jsonl",
        embedding_provider: str = "openai",
        embedding_model: Optional[str] = None,
        reranker_model: str = "BAAI/bge-reranker-v2-m3",
        use_reranker: bool = True,
        bm25_weight: float = 0.4,
        vector_weight: float = 0.6,
    ):
        self.db_path = db_path
        self.sections_jsonl = sections_jsonl
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.reranker_model_name = reranker_model
        self.use_reranker = use_reranker
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight

        self._vector_db: Optional[Chroma] = None
        self._bm25_docs: Optional[list[Document]] = None
        self._reranker = None  # lazy load

    # ------------------------------
    # Lazy loaders
    # ------------------------------

    def _load_vector_db(self) -> Chroma:
        if self._vector_db is None:
            from build_rag_db import load_embeddings
            embeddings = load_embeddings(
                provider=self.embedding_provider,
                model_name=self.embedding_model,
            )
            self._vector_db = Chroma(
                persist_directory=self.db_path,
                embedding_function=embeddings,
            )
        return self._vector_db

    def _load_bm25_corpus(self) -> list[Document]:
        """
        BM25용 Document 리스트. sections.jsonl을 직접 읽어 생성
        """
        if self._bm25_docs is None:
            from build_rag_db import make_enhanced_content
            docs = []
            with open(self.sections_jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    s = json.loads(line)
                    content = make_enhanced_content(s)
                    meta = {
                        "corp_name": s.get("corp_name") or "",
                        "fiscal_year": int(s.get("fiscal_year") or 0),
                        "source_file": s.get("source_file") or "",
                        "section_id": s.get("section_id") or "",
                        "section_path_str": " > ".join(s.get("section_path", [])),
                    }
                    docs.append(Document(page_content=content, metadata=meta))
            self._bm25_docs = docs
        return self._bm25_docs

    def _load_reranker(self):
        if self._reranker is None and self.use_reranker:
            try:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(self.reranker_model_name)
            except ImportError:
                print("[경고] sentence-transformers가 설치되지 않음. 리랭커 비활성화.")
                self.use_reranker = False
            except Exception as e:
                print(f"[경고] 리랭커 로드 실패: {e}. 리랭커 비활성화.")
                self.use_reranker = False
        return self._reranker

    # ------------------------------
    # 내부 검색 단계
    # ------------------------------

    def _build_filter(
        self,
        corp_name: Optional[str],
        fiscal_year: Optional[int],
    ) -> dict:
        """Chroma where 절 빌드"""
        conditions = []
        if corp_name:
            conditions.append({"corp_name": corp_name})
        if fiscal_year:
            conditions.append({"fiscal_year": int(fiscal_year)})
        
        if len(conditions) == 0:
            return {}
        elif len(conditions) == 1:
            return conditions[0]
        else:
            return {"$and": conditions}

    def _vector_search(self, query: str, k: int, where: dict) -> list[Document]:
        """Chroma 벡터 검색"""
        db = self._load_vector_db()
        kwargs = {"k": k}
        if where:
            kwargs["filter"] = where
        return db.similarity_search(query, **kwargs)

    def _bm25_search(
        self,
        query: str,
        k: int,
        corp_name: Optional[str],
        fiscal_year: Optional[int],
    ) -> list[Document]:
        """BM25 검색. Chroma에 where가 없어 Python으로 메타 필터링"""
        from langchain_community.retrievers import BM25Retriever

        docs = self._load_bm25_corpus()
        # 메타 필터
        if corp_name:
            docs = [d for d in docs if d.metadata.get("corp_name") == corp_name]
        if fiscal_year:
            docs = [d for d in docs if d.metadata.get("fiscal_year") == int(fiscal_year)]
        
        if not docs:
            return []
        
        retriever = BM25Retriever.from_documents(docs)
        retriever.k = k
        return retriever.invoke(query)

    def _merge_candidates(
        self,
        bm25_docs: list[Document],
        vector_docs: list[Document],
    ) -> list[Document]:
        """
        두 검색 결과를 score 기반으로 병합
        """
        scores: dict[str, float] = {}
        doc_map: dict[str, Document] = {}
        
        for rank, doc in enumerate(bm25_docs):
            key = doc.metadata.get("section_id") or doc.page_content[:100]
            scores[key] = scores.get(key, 0) + self.bm25_weight / (rank + 1)
            doc_map[key] = doc
        
        for rank, doc in enumerate(vector_docs):
            key = doc.metadata.get("section_id") or doc.page_content[:100]
            scores[key] = scores.get(key, 0) + self.vector_weight / (rank + 1)
            doc_map[key] = doc
        
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [doc_map[k] for k, _ in ranked]

    def _rerank(self, query: str, candidates: list[Document], top_k: int) -> list[Document]:
        """
        Cross-encoder로 재정렬
        GPU 메모리 관리
        """
        if not candidates or not self.use_reranker:
            return candidates[:top_k]
        
        reranker = self._load_reranker()
        if reranker is None:
            return candidates[:top_k]
        
        # 긴 섹션 텍스트 트렁케이트
        MAX_CHARS_PER_DOC = 1500
        pairs = [
            (query, doc.page_content[:MAX_CHARS_PER_DOC])
            for doc in candidates
        ]
        
        # 배치 크기 제한
        try:
            scores = reranker.predict(pairs, batch_size=4, show_progress_bar=False)
        except Exception as e:
            print(f"[리랭커 오류: {type(e).__name__}] 원 순서 유지")
            return candidates[:top_k]
        finally:
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        
        # score 높은 순
        ranked = sorted(zip(candidates, scores), key=lambda x: -x[1])
        return [doc for doc, _ in ranked[:top_k]]

    # ------------------------------
    # API
    # ------------------------------

    def retrieve(
        self,
        query: str,
        corp_name: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        k: int = 3,
        candidate_k: int = 10,
    ) -> RetrievalResult:
        """
        쿼리 → top-k Document
        
        Args:
            query: 사용자 자연어 질문
            corp_name: 라우터가 추출한 기업명 (필터링용)
            fiscal_year: 연도 필터 (선택)
            k: 최종 반환 문서 수
            candidate_k: 리랭킹 전 후보 수
        """
        filter_relaxed = False
        applied_filter = {"corp_name": corp_name, "fiscal_year": fiscal_year}

        # 1: 전체 필터 적용
        where = self._build_filter(corp_name, fiscal_year)
        vector_docs = self._vector_search(query, candidate_k, where)
        bm25_docs = self._bm25_search(query, candidate_k, corp_name, fiscal_year)

        # Fallback 1: 연도 필터 제거
        if not vector_docs and not bm25_docs and fiscal_year:
            filter_relaxed = True
            applied_filter = {"corp_name": corp_name, "fiscal_year": None}
            where = self._build_filter(corp_name, None)
            vector_docs = self._vector_search(query, candidate_k, where)
            bm25_docs = self._bm25_search(query, candidate_k, corp_name, None)

        # Fallback 2: 기업 필터도 제거
        if not vector_docs and not bm25_docs and corp_name:
            filter_relaxed = True
            applied_filter = {"corp_name": None, "fiscal_year": None}
            vector_docs = self._vector_search(query, candidate_k, {})
            bm25_docs = self._bm25_search(query, candidate_k, None, None)

        # 2: 병합
        candidates = self._merge_candidates(bm25_docs, vector_docs)

        # 3: 리랭킹
        final = self._rerank(query, candidates[:candidate_k], k)

        return RetrievalResult(
            documents=final,
            raw_candidates=candidates,
            filter_applied=applied_filter,
            filter_relaxed=filter_relaxed,
            num_candidates=len(candidates),
            reranker_used=(self.use_reranker and self._reranker is not None),
        )


# ==========================================
# 테스트
# ==========================================

if __name__ == "__main__":
    import argparse
    from router import route

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="./db/chroma_rag")
    parser.add_argument("--sections", default="./processed/sections.jsonl")
    parser.add_argument("--no-rerank", action="store_true", help="리랭커 끄기 (빠른 테스트)")
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--candidate-k", type=int, default=10)
    args = parser.parse_args()

    retriever = RAGRetriever(
        db_path=args.db,
        sections_jsonl=args.sections,
        use_reranker=not args.no_rerank,
    )

    # eval_data 비정형 질문 샘플
    test_queries = [
        "삼성전자의 사업 부문 중 DX 부문과 DS 부문이 각각 담당하는 주요 사업 내용 및 제품은 무엇인가요?",
        "현대자동차의 연구개발실적 중 자율주행이나 친환경차와 관련된 최근 개발 성과는 무엇인가요?",
        "LG에너지솔루션의 주요 고객사와의 합작법인(JV) 설립 현황이나 향후 투자 계획은?",
        "셀트리온이 현재 연구개발 중이거나 상업화한 주요 바이오시밀러 파이프라인의 시장 진출 현황은?",
        "POSCO홀딩스가 미래 성장동력으로 추진 중인 이차전지소재 관련 사업의 현황 및 투자 계획은?",
    ]

    for q in test_queries:
        print("=" * 80)
        print(f"질문: {q[:70]}...")
        
        # 라우터로 메타 추출
        qi = route(q, use_llm=False)
        print(f"라우터: intent={qi.intent}, corp={qi.corp_name}, year={qi.fiscal_year}")
        
        # 검색
        result = retriever.retrieve(
            query=q,
            corp_name=qi.corp_name,
            fiscal_year=qi.fiscal_year,
            k=args.k,
            candidate_k=args.candidate_k,
        )
        
        print(f"후보 {result.num_candidates}개, 리랭커={'ON' if result.reranker_used else 'OFF'}, "
              f"필터 완화={result.filter_relaxed}")
        print(f"적용 필터: {result.filter_applied}")
        print(f"\n최종 top-{args.k}:")
        for i, doc in enumerate(result.documents, 1):
            corp = doc.metadata.get("corp_name", "?")
            year = doc.metadata.get("fiscal_year", "?")
            path = doc.metadata.get("section_path_str", "")
            preview = doc.page_content.replace("\n", " ")[:180]
            print(f"  [{i}] {corp} / {year}년 / {path}")
            print(f"      {preview}...")
        print()
