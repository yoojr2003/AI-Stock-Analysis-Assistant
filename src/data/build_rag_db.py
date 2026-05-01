"""
build_rag_db.py — 섹션 기반 RAG DB 구축
"""

from __future__ import annotations

import os
import json
import shutil
import argparse
from typing import Optional
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma


# ==========================================
# 청크 설정
# ==========================================
MAX_SECTION_CHARS = 3000
CHUNK_OVERLAP = 300


def make_enhanced_content(section: dict) -> str:
    corp = section.get("corp_name", "")
    year = section.get("fiscal_year", "")
    path = " > ".join(section.get("section_path", []))
    header = f"[{corp} / {year}년 / {path}]"
    body = section.get("text", "")
    return f"{header}\n{body}"


def section_to_documents(section: dict, splitter: RecursiveCharacterTextSplitter) -> list[Document]:
    enhanced = make_enhanced_content(section)
    
    # 메타데이터 (Chroma는 스칼라/리스트만 받음, 리스트는 문자열로 직렬화)
    base_meta = {
        "corp_name": section.get("corp_name") or "",
        "fiscal_year": int(section.get("fiscal_year") or 0),
        "source_file": section.get("source_file") or "",
        "section_id": section.get("section_id") or "",
        "section_path_str": " > ".join(section.get("section_path", [])),
        "char_count": section.get("char_count", 0),
    }
    
    # 짧은 섹션: 그대로
    if len(enhanced) <= MAX_SECTION_CHARS:
        return [Document(page_content=enhanced, metadata={**base_meta, "chunk_idx": 0})]
    
    # 긴 섹션: split + overlap
    pieces = splitter.split_text(enhanced)
    docs = []
    for i, piece in enumerate(pieces):
        meta = {**base_meta, "chunk_idx": i}
        docs.append(Document(page_content=piece, metadata=meta))
    return docs


# ==========================================
# 임베딩 모델 로더
# ==========================================

def load_embeddings(provider: str = "openai", model_name: Optional[str] = None):
    """
    임베딩 모델 로드
    provider='openai': text-embedding-3-small (기본)
    provider='hf': HuggingFace 한국어 모델
    """
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY 환경 변수를 설정하세요")
        return OpenAIEmbeddings(model=model_name or "text-embedding-3-small")
    elif provider == "hf":
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name=model_name or "jhgan/ko-sroberta-multitask",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    else:
        raise ValueError(f"알 수 없는 provider: {provider}")


# ==========================================
# DB 구축
# ==========================================

def build_rag_db(
    sections_jsonl: str,
    db_path: str,
    provider: str = "openai",
    model_name: Optional[str] = None,
    batch_size: int = 100,
    overwrite: bool = True,
) -> dict:
    """
    sections.jsonl → Chroma DB.
    """
    if overwrite and os.path.exists(db_path):
        print(f"기존 DB 삭제: {db_path}")
        shutil.rmtree(db_path)
    os.makedirs(db_path, exist_ok=True)

    # 텍스트 분할기
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=MAX_SECTION_CHARS,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", "。", " ", ""],
    )

    # 섹션 로드
    print(f"\n섹션 로드: {sections_jsonl}")
    sections = []
    with open(sections_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            sections.append(json.loads(line))
    print(f"  → {len(sections)}개 섹션")

    # Document 생성
    print("\nDocument 생성")
    all_docs = []
    for s in sections:
        docs = section_to_documents(s, splitter)
        all_docs.extend(docs)
    print(f"  → {len(all_docs)}개 청크 (섹션당 평균 {len(all_docs)/max(1,len(sections)):.1f}개)")

    # 통계
    corps = {}
    for d in all_docs:
        c = d.metadata["corp_name"]
        corps[c] = corps.get(c, 0) + 1
    print("\n기업별 청크 분포:")
    for c, n in sorted(corps.items()):
        print(f"  {c:18} {n:>5}")

    # 임베딩 & DB 구축
    print(f"\n임베딩 모델 로드 (provider={provider})")
    embeddings = load_embeddings(provider=provider, model_name=model_name)

    print(f"\nChroma DB 구축 시작 (batch_size={batch_size})")
    # 배치로 나눠서 저장 (limit 고려)
    db = None
    for i in range(0, len(all_docs), batch_size):
        batch = all_docs[i:i + batch_size]
        if db is None:
            db = Chroma.from_documents(
                documents=batch,
                embedding=embeddings,
                persist_directory=db_path,
            )
        else:
            db.add_documents(batch)
        print(f"  진행: {min(i + batch_size, len(all_docs))}/{len(all_docs)}")

    count = db._collection.count()
    print(f"\nDB 구축 완료: {count}개 문서 저장")

    return {
        "db_path": db_path,
        "total_sections": len(sections),
        "total_chunks": len(all_docs),
        "corps": corps,
        "provider": provider,
    }


# ==========================================
# CLI
# ==========================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sections", default="./processed/sections.jsonl")
    parser.add_argument("--db", default="./db/chroma_rag")
    parser.add_argument("--provider", default="openai", choices=["openai", "hf"])
    parser.add_argument("--model", default=None, help="임베딩 모델 이름 (기본값 사용 시 생략)")
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args()

    result = build_rag_db(
        sections_jsonl=args.sections,
        db_path=args.db,
        provider=args.provider,
        model_name=args.model,
        batch_size=args.batch,
    )
    print(f"\n완료: {json.dumps({k: v for k, v in result.items() if k != 'corps'}, ensure_ascii=False, indent=2)}")
