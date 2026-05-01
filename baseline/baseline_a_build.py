"""
baseline_a_build.py — Baseline A: Naive RAG 구축

입력: parsed_reports.json (평면 텍스트, 표 없음)
출력: /content/baseline_a/chroma_db

가장 단순한 baseline. "XBRL/라우터/리랭커 없이 단순 RAG로 얼마나 되는지" 기준선.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma


def parse_filename_metadata(filename: str) -> dict:
    m = re.search(r"[_\[]([가-힣A-Za-z0-9]+)[_\]][_\[]*(\d{4})년도공시", filename)
    if m:
        return {"corp_name": m.group(1), "fiscal_year": int(m.group(2))}
    return {"corp_name": "?", "fiscal_year": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="/content/parsed_reports.json")
    parser.add_argument("--db", default="/content/baseline_a/chroma_db")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--chunk-overlap", type=int, default=100)
    args = parser.parse_args()
    
    with open(args.json, encoding="utf-8") as f:
        reports = json.load(f)
    print(f"▶ 문서 {len(reports)}개 로드 (평면 텍스트)")
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        separators=["\n\n", "\n", ". ", " "],
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
            all_docs.append(Document(
                page_content=chunk,
                metadata={
                    "source_file": filename,
                    "corp_name": meta["corp_name"],
                    "fiscal_year": meta["fiscal_year"],
                    "chunk_idx": i,
                }
            ))
    
    print(f"✅ 총 {len(all_docs)}개 청크")
    
    db_path = Path(args.db)
    if db_path.exists():
        shutil.rmtree(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    embed_model = OpenAIEmbeddings(model="text-embedding-3-small")
    
    batch_size = 100
    print(f"\n▶ Chroma DB 저장 (batch={batch_size})")
    
    vector_db = Chroma.from_documents(
        documents=all_docs[:batch_size],
        embedding=embed_model,
        persist_directory=str(db_path),
    )
    
    for i in range(batch_size, len(all_docs), batch_size):
        batch = all_docs[i:i+batch_size]
        
        # OpenAI rate limit (TPM 1M) 대응: 재시도 + 점진적 대기
        for attempt in range(5):
            try:
                vector_db.add_documents(batch)
                break
            except Exception as e:
                msg = str(e)
                if "rate_limit" in msg.lower() or "429" in msg:
                    wait_sec = 30 * (attempt + 1)  # 30, 60, 90, 120초
                    print(f"   [rate limit] {wait_sec}초 대기 후 재시도 ({attempt+1}/5)")
                    time.sleep(wait_sec)
                else:
                    raise
        
        done = min(i + batch_size, len(all_docs))
        if done % 1000 == 0 or done == len(all_docs):
            print(f"   저장: {done}/{len(all_docs)}")
        
        # 배치 간 짧은 대기 — OpenAI TPM 초과 예방 (평균 15초마다 100개)
        time.sleep(3)
    
    print(f"\n✅ Baseline A DB 저장 완료: {db_path}")


if __name__ == "__main__":
    main()
