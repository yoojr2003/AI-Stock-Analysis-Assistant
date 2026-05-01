"""
run_evaluation.py — 45개 평가 질문을 pipeline에 실행
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/content")
sys.path.insert(0, ".")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/content/pipeline_eval_results.json")
    parser.add_argument("--limit", type=int, default=None,
                        help="처음 N개만 실행 (디버깅용)")
    parser.add_argument("--start", type=int, default=0,
                        help="N번째부터 시작 (재개용)")
    args = parser.parse_args()
    
    # 데이터셋 로드
    from eval_data_extended import eval_dataset
    
    if args.limit:
        cases = eval_dataset[args.start:args.start + args.limit]
    else:
        cases = eval_dataset[args.start:]
    
    print(f"평가 대상: {len(cases)}개 질문 (전체 {len(eval_dataset)}개 중)")
    
    # 이전 결과 로드 (재개)
    results = []
    if args.start > 0 and os.path.exists(args.output):
        with open(args.output, "r", encoding="utf-8") as f:
            results = json.load(f)
        results = results[:args.start]
        print(f"기존 결과 {len(results)}개 로드")
    
    # Pipeline 초기화
    print("\nPipeline 로딩 중...")
    from pipeline import QAPipeline
    p = QAPipeline(
        facts_db_path="/content/db/facts.db",
        rag_db_path="/content/db/chroma_rag",
        sections_jsonl="/content/processed/sections.jsonl",
        use_reranker=True,
    )
    print(" Pipeline 준비 완료\n")
    
    # 평가 실행
    start_time = time.time()
    
    for i, case in enumerate(cases, start=args.start + 1):
        question = case["question"]
        gt = case["ground_truth"]
        
        t0 = time.time()
        try:
            resp = p.ask(question)
            answer = resp.answer
            intent = resp.intent
            confidence = str(resp.confidence)
            sources = [s.get("source_file", "") for s in resp.sources[:3]]
            error = None
        except Exception as e:
            answer = ""
            intent = "error"
            confidence = "error"
            sources = []
            error = str(e)
        
        elapsed = time.time() - t0
        
        result = {
            "id": i,
            "question": question,
            "ground_truth": gt,
            "answer": answer,
            "intent": intent,
            "confidence": confidence,
            "sources": sources,
            "elapsed": elapsed,
            "error": error,
        }
        results.append(result)
        
        # 진행 상황 출력
        status = "✅" if not error else "❌"
        snippet = answer[:50].replace("\n", " ") if answer else (error or "")
        print(f"[{i:2}/{len(eval_dataset)}] {status} {intent:15} ({elapsed:5.1f}s) {snippet[:60]}")
        
        # 매 5개마다 중간 저장
        if i % 5 == 0:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
    
    # 최종 저장
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    total_time = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  ✅ 평가 완료")
    print(f"{'=' * 60}")
    print(f"  총 {len(results)}개 질문")
    print(f"  소요 시간: {total_time/60:.1f}분")
    print(f"  결과 저장: {args.output}")
    
    # 의도별 통계
    from collections import Counter
    intent_count = Counter(r["intent"] for r in results)
    print(f"\n  의도별 분포:")
    for intent, cnt in intent_count.most_common():
        print(f"    {intent:20} {cnt}개")


if __name__ == "__main__":
    main()
