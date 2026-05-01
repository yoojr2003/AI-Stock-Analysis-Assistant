"""
baseline_run.py — Baseline A 또는 B 평가 실행

Baseline A: Vector 검색만, 리랭커/BM25 없음
Baseline B: Vector + BM25 + Reranker (우리 시스템과 동일 retrieval 스택)

둘 다 라우터/XBRL 팩트 DB는 없음.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_chroma import Chroma


# ==========================================
# HCX 호출
# ==========================================

CLOVA_URL = "https://clovastudio.stream.ntruss.com/testapp/v1/chat-completions/HCX-003"
CLOVA_API_KEY = os.environ.get("CLOVA_API_KEY", "")


def call_hcx(system_prompt: str, user_prompt: str, max_retries: int = 3) -> tuple[str, Optional[str]]:
    import requests
    
    headers = {
        "Authorization": f"Bearer {CLOVA_API_KEY}",
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
            "temperature": 0.1,
            "maxTokens": 600,
        }
        
        try:
            res = requests.post(CLOVA_URL, headers=headers, json=payload, timeout=30)
            res.raise_for_status()
            return res.json()["result"]["message"]["content"], None
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            body = e.response.text[:300] if e.response is not None else ""
            
            if status == 429 and attempt < max_retries - 1:
                print(f"  [HCX 429] {2**(attempt+1)}초 대기 후 재시도")
                time.sleep(2 ** (attempt + 1))
                continue
            if status == 400 and "Context length" in body and attempt < max_retries - 1:
                keep = int(len(current_user_prompt) * 0.7)
                current_user_prompt = current_user_prompt[:keep] + "\n...(중략)..."
                print(f"  [HCX 400 context] prompt 축약 후 재시도")
                continue
            return "", f"{e} | {body}"
        except Exception as e:
            return "", str(e)
    
    return "", f"재시도 {max_retries}회 실패"


# ==========================================
# Retriever
# ==========================================

@dataclass
class BaselineConfig:
    db_path: str
    chunks_jsonl: Optional[str] = None 
    use_reranker: bool = True           
    use_bm25: bool = True               
    top_k: int = 3
    candidate_k: int = 10
    bm25_weight: float = 0.4
    vector_weight: float = 0.6


class BaselineRetriever:
    
    def __init__(self, config: BaselineConfig):
        self.config = config
        self.embed_model = OpenAIEmbeddings(model="text-embedding-3-small")
        self.vector_db = Chroma(
            persist_directory=config.db_path,
            embedding_function=self.embed_model,
        )
        self._reranker = None
        self._bm25 = None
        
        # BM25 사전 빌드 (Baseline B)
        if config.use_bm25 and config.chunks_jsonl:
            self._load_bm25(config.chunks_jsonl)
    
    def _load_bm25(self, chunks_path: str):
        print(f"▶ BM25 인덱스 빌드: {chunks_path}")
        docs = []
        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                docs.append(Document(page_content=d["page_content"], metadata=d["metadata"]))
        self._bm25 = BM25Retriever.from_documents(docs)
        self._bm25.k = self.config.candidate_k
        print(f"  BM25 문서 수: {len(docs)}")
    
    def _load_reranker(self):
        if self._reranker is not None:
            return self._reranker
        try:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
            return self._reranker
        except Exception as e:
            print(f"[리랭커 로드 실패] {e}")
            return None
    
    def _merge_rrf(self, bm25_docs: list[Document], vector_docs: list[Document]) -> list[Document]:
        scores = {}
        doc_map = {}
        
        for rank, doc in enumerate(bm25_docs):
            key = doc.metadata.get("source_file", "") + "__" + doc.page_content[:60]
            scores[key] = scores.get(key, 0) + self.config.bm25_weight / (rank + 1)
            doc_map[key] = doc
        
        for rank, doc in enumerate(vector_docs):
            key = doc.metadata.get("source_file", "") + "__" + doc.page_content[:60]
            scores[key] = scores.get(key, 0) + self.config.vector_weight / (rank + 1)
            doc_map[key] = doc
        
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [doc_map[k] for k, _ in ranked]
    
    def retrieve(self, query: str) -> list[Document]:
        k = self.config.candidate_k if (self.config.use_reranker or self.config.use_bm25) else self.config.top_k
        
        # Vector 검색
        vector_docs = self.vector_db.similarity_search(query, k=k)
        
        # BM25 (Baseline B)
        if self.config.use_bm25 and self._bm25:
            bm25_docs = self._bm25.invoke(query)
            candidates = self._merge_rrf(bm25_docs, vector_docs)
        else:
            candidates = vector_docs
        
        # Reranker (Baseline B)
        if self.config.use_reranker and len(candidates) > self.config.top_k:
            reranker = self._load_reranker()
            if reranker:
                pairs = [(query, d.page_content[:1500]) for d in candidates[:self.config.candidate_k]]
                try:
                    scores = reranker.predict(pairs, batch_size=4, show_progress_bar=False)
                    ranked = sorted(zip(candidates[:self.config.candidate_k], scores), key=lambda x: -x[1])
                    return [d for d, _ in ranked[:self.config.top_k]]
                except Exception as e:
                    print(f"[리랭킹 오류] {e}")
                    return candidates[:self.config.top_k]
                finally:
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except Exception:
                        pass
        
        return candidates[:self.config.top_k]


# ==========================================
# 답변 생성
# ==========================================

SYSTEM_PROMPT = (
    "당신은 한국 기업 공시 자료 기반 Q&A 비서입니다. "
    "제공된 자료만 근거로 답변하고, 없으면 '제공된 공시 자료에서 정보를 찾을 수 없습니다'라고 답하세요. "
    "수치는 반드시 자료에 있는 그대로 정확히 인용하고, 단위(백만원/원)를 명시하세요. "
    "답변 마지막에 출처(문서 출처)를 짧게 표시하세요."
)


def generate_answer(query: str, docs: list[Document]) -> tuple[str, Optional[str]]:
    if not docs:
        return "제공된 공시 자료에서 해당 정보를 찾을 수 없습니다.", None
    
    contexts = []
    for i, doc in enumerate(docs, 1):
        src = doc.metadata.get("source_file", "?")
        content = doc.page_content[:1500]
        contexts.append(f"[자료 {i}] 출처: {src}\n{content}")
    
    user_prompt = (
        f"질문: {query}\n\n"
        f"=== 참고 자료 ===\n" + "\n\n".join(contexts)
    )
    
    return call_hcx(SYSTEM_PROMPT, user_prompt)


# ==========================================
# 메인
# ==========================================

def run_eval(config: BaselineConfig, eval_dataset: list[dict], output_path: str):
    retriever = BaselineRetriever(config)
    
    results = []
    total = len(eval_dataset)
    print(f"▶ {total}개 질문 평가 시작\n")
    
    for i, item in enumerate(eval_dataset, 1):
        t0 = time.time()
        q = item["question"]
        gt = item["ground_truth"]
        
        docs = retriever.retrieve(q)
        answer, err = generate_answer(q, docs)
        if err:
            answer = f"답변 생성 중 오류가 발생했습니다: {err[:200]}"
        
        elapsed = time.time() - t0
        
        print(f"[{i}/{total}] ({elapsed:.1f}s)")
        print(f"  Q: {q[:80]}")
        print(f"  A: {answer[:180]}")
        print(f"  GT: {gt[:100]}")
        print()
        
        results.append({
            "question": q,
            "ground_truth": gt,
            "answer": answer,
            "intent": "rag",
            "confidence": "N/A",
            "sources": [
                {"source_file": d.metadata.get("source_file", "?"),
                 "corp_name": d.metadata.get("corp_name", ""),
                 "fiscal_year": d.metadata.get("fiscal_year", 0),
                 "section_path_str": d.metadata.get("section_path_str", ""),
                 "chunk_idx": d.metadata.get("chunk_idx", -1)}
                for d in docs
            ],
            "elapsed": elapsed,
        })
        
        if i < total:
            time.sleep(1.5)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 결과 저장: {output_path}")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", choices=["a", "b"], required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--chunks", help="BM25용 chunks.jsonl (baseline b만 필요)")
    parser.add_argument("--eval-data", default="/content/eval_data.py")
    parser.add_argument("--output", default="/content/baseline_eval_results.json")
    args = parser.parse_args()
    
    sys.path.insert(0, str(os.path.dirname(os.path.abspath(args.eval_data))))
    mod_name = os.path.basename(args.eval_data).replace(".py", "")
    eval_module = __import__(mod_name)
    eval_dataset = eval_module.eval_dataset
    
    if args.baseline == "a":
        config = BaselineConfig(
            db_path=args.db,
            use_reranker=False,
            use_bm25=False,
        )
    else:
        config = BaselineConfig(
            db_path=args.db,
            chunks_jsonl=args.chunks,
            use_reranker=True,
            use_bm25=True,
        )
    
    print(f"   Baseline {args.baseline.upper()} 실행   ")
    print(f"DB: {args.db}")
    print(f"BM25: {'ON' if config.use_bm25 else 'OFF'}")
    print(f"리랭커: {'ON' if config.use_reranker else 'OFF'}")
    print(f"평가: {len(eval_dataset)}개 질문\n")
    
    run_eval(config, eval_dataset, args.output)


if __name__ == "__main__":
    main()
