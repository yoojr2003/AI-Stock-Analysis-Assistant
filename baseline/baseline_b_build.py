"""
baseline_b_build.py — Baseline B: Table-aware RAG 구축


차이:
- XBRL 팩트 DB 없음 (라우터도 없음)
- 섹션 경로 메타데이터 없음 (filename만)
- 표는 마크다운 그대로 (구조 보존은 되지만 XBRL처럼 쿼리 가능하진 않음)

동일:
- 같은 임베딩 (text-embedding-3-small)
- 같은 리랭커 (bge-reranker-v2-m3) — 런타임에 사용
- 같은 LLM (HCX-003)
- BM25 + Vector (baseline_run.py에서 구성)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma


def parse_filename_metadata(filename: str) -> dict:
    """파일명에서 기업명, 보고연도 추출."""
    m = re.search(r"[_\[]([가-힣A-Za-z0-9]+)[_\]][_\[]*(\d{4})년도공시", filename)
    if m:
        corp = m.group(1)
        fy = int(m.group(2))
    else:
        corp = "?"
        fy = 0
    return {"corp_name": corp, "fiscal_year": fy}


def build_documents(json_path: str, chunk_size: int = 1200, chunk_overlap: int = 150) -> list[Document]:
    """JSON 파일을 읽어 Document 리스트로 변환."""
    with open(json_path, encoding="utf-8") as f:
        reports = json.load(f)
    
    print(f"▶ 문서 {len(reports)}개 로드")
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n\n", "\n\n", "\n", ". ", " "],
    )
    
    all_docs = []
    for report in reports:
        filename = report.get("filename", "?")
        text = report.get("text", "")
        meta = parse_filename_metadata(filename)
        
        chunks = splitter.split_text(text)
        for i, chunk in enumerate(chunks):
            if len(chunk) < 50:
                continue
            
            enhanced = f"[문서 출처: {filename}]\n\n{chunk}"
            
            all_docs.append(Document(
                page_content=enhanced,
                metadata={
                    "source_file": filename,
                    "corp_name": meta["corp_name"],
                    "fiscal_year": meta["fiscal_year"],
                    "chunk_idx": i,
                }
            ))
    
    print(f" 총 {len(all_docs)}개 청크 생성")
    return all_docs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="/content/parsed_reports_table_aware.json")
    parser.add_argument("--db", default="/content/baseline_b/chroma_db")
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--chunk-overlap", type=int, default=150)
    args = parser.parse_args()
    
    docs = build_documents(args.json, args.chunk_size, args.chunk_overlap)
    
    db_path = Path(args.db)
    if db_path.exists():
        shutil.rmtree(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    embed_model = OpenAIEmbeddings(model="text-embedding-3-small")
    
    batch_size = 100
    print(f"\n▶ Chroma DB 저장 (batch={batch_size})")
    
    vector_db = Chroma.from_documents(
        documents=docs[:batch_size],
        embedding=embed_model,
        persist_directory=str(db_path),
    )
    
    for i in range(batch_size, len(docs), batch_size):
        batch = docs[i:i+batch_size]
        vector_db.add_documents(batch)
        done = min(i + batch_size, len(docs))
        print(f"   저장: {done}/{len(docs)}")
    
    # BM25용 원본 청크 저장
    chunks_path = db_path.parent / "chunks.jsonl"
    with open(chunks_path, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps({
                "page_content": d.page_content,
                "metadata": d.metadata,
            }, ensure_ascii=False) + "\n")
    
    print(f"\n DB 저장 완료: {db_path}")
    print(f" BM25용 chunks: {chunks_path}")


if __name__ == "__main__":
    main()
