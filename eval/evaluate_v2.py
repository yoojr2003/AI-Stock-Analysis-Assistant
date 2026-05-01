from __future__ import annotations

import os
import re
import json
import time
import argparse
import locale
from typing import Optional, Any
from pathlib import Path

import pandas as pd

os.environ["PYTHONIOENCODING"] = "utf-8"
try:
    locale.getpreferredencoding = lambda do_setlocale=True: "UTF-8"
except Exception:
    pass


NUMBER_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def extract_numbers(text: str) -> list[str]:
    matches = NUMBER_RE.findall(text or "")
    return [m.replace(",", "") for m in matches if len(m.replace(",", "")) >= 4]


def exact_number_match(answer: str, ground_truth: str) -> float:
    gt_nums = extract_numbers(ground_truth)
    if not gt_nums:
        return -1.0
    ans_nums = extract_numbers(answer)
    main_gt = max(gt_nums, key=len)
    return 1.0 if main_gt in ans_nums else 0.0


def tokenize_korean(text: str) -> list[str]:
    cleaned = re.sub(r"[^\w가-힣]+", " ", text or "")
    tokens = cleaned.split()
    tokens = [t for t in tokens if len(t) >= 2]
    suffixes = ["입니다", "이며", "이다", "합니다", "있습니다", "하고", "에서", "으로", "부터", "까지", "등이", "등은", "되어", "되고"]
    cleaned_tokens = []
    for t in tokens:
        for sfx in suffixes:
            if t.endswith(sfx) and len(t) > len(sfx) + 1:
                t = t[:-len(sfx)]
                break
        cleaned_tokens.append(t)
    return cleaned_tokens


STOPWORDS_KR = {
    "있습니다", "입니다", "합니다", "하고", "있으며", "있다", "이다", "되고", "되어",
    "기준", "관련", "주요", "다음", "같은", "통해", "위한", "위해", "대한", "대해",
    "이러한", "그리고", "또한", "또는", "그러나", "하지만",
    "당사", "회사", "당기", "전기", "우리",
    "습니다", "니다",
}


def keyword_coverage(answer: str, ground_truth: str, threshold: float = 0.3) -> dict:
    gt_tokens = tokenize_korean(ground_truth)
    gt_keywords = []
    seen = set()
    for t in gt_tokens:
        if t not in STOPWORDS_KR and t not in seen and len(t) >= 2:
            gt_keywords.append(t)
            seen.add(t)
    
    if not gt_keywords:
        return {"coverage": -1.0, "matched": [], "missed": [], "gt_keywords": []}
    
    ans_text = (answer or "").replace(" ", "")
    matched = []
    missed = []
    for kw in gt_keywords:
        if kw in ans_text or (len(kw) > 2 and kw[:-1] in ans_text):
            matched.append(kw)
        else:
            missed.append(kw)
    
    coverage = len(matched) / len(gt_keywords)
    return {
        "coverage": round(coverage, 3),
        "matched": matched,
        "missed": missed,
        "gt_keywords": gt_keywords,
    }


def evaluate_custom_metrics(results: list[dict]) -> pd.DataFrame:
    rows = []
    for i, item in enumerate(results):
        q = item["question"]
        gt = item["ground_truth"]
        ans = item["answer"]
        intent = item.get("intent", "unknown")
        confidence = item.get("confidence", "unknown")
        elapsed = item.get("elapsed", 0.0)
        
        num_match = exact_number_match(ans, gt)
        kw_result = keyword_coverage(ans, gt)
        
        gt_has_number = len(extract_numbers(gt)) > 0
        if gt_has_number and intent == "fact_lookup":
            intent_correct = 1
        elif not gt_has_number and intent == "narrative":
            intent_correct = 1
        elif intent == "hybrid":
            intent_correct = 1
        else:
            intent_correct = 0
        
        rows.append({
            "idx": i,
            "question": q[:80],
            "intent": intent,
            "intent_correct": intent_correct,
            "confidence": confidence,
            "exact_number_match": num_match,
            "kw_coverage": kw_result["coverage"],
            "matched_kw_count": len(kw_result["matched"]),
            "missed_kw_count": len(kw_result["missed"]),
            "elapsed": elapsed,
            "answer_preview": (ans or "")[:120],
        })
    return pd.DataFrame(rows)


def summarize_custom(df: pd.DataFrame) -> dict:
    total = len(df)
    
    fact_df = df[df["intent"] == "fact_lookup"]
    narr_df = df[df["intent"] == "narrative"]
    hybrid_df = df[df["intent"] == "hybrid"]
    
    fact_scorable = fact_df[fact_df["exact_number_match"] != -1.0]
    fact_accuracy = fact_scorable["exact_number_match"].mean() if len(fact_scorable) > 0 else float("nan")
    
    narr_scorable = narr_df[narr_df["kw_coverage"] != -1.0]
    narr_coverage = narr_scorable["kw_coverage"].mean() if len(narr_scorable) > 0 else float("nan")
    
    intent_accuracy = df["intent_correct"].mean()
    avg_elapsed = df["elapsed"].mean()
    
    return {
        "total_questions": total,
        "fact_lookup_n": len(fact_df),
        "narrative_n": len(narr_df),
        "hybrid_n": len(hybrid_df),
        "fact_number_accuracy": round(fact_accuracy, 3) if not pd.isna(fact_accuracy) else None,
        "narrative_kw_coverage_avg": round(narr_coverage, 3) if not pd.isna(narr_coverage) else None,
        "intent_classification_accuracy": round(intent_accuracy, 3),
        "avg_elapsed_seconds": round(avg_elapsed, 2),
    }


def prepare_ragas_dataset(results: list[dict]):
    from datasets import Dataset
    
    data = {"question": [], "answer": [], "contexts": [], "ground_truth": []}
    for item in results:
        data["question"].append(item["question"])
        data["answer"].append(item["answer"] or "")
        
        contexts = []
        for src in item.get("sources", []):
            parts = []
            if src.get("type") == "fact" or "account_kr" in src:
                acc = src.get("account_kr", "")
                val = src.get("value_raw", "")
                unit = src.get("unit_hint", "")
                parts.append(f"{acc} = {val} {unit}")
            if "section_path_str" in src:
                parts.append(src["section_path_str"])
            if src.get("source_file"):
                parts.append(f"출처: {src['source_file']}")
            if parts:
                contexts.append(" | ".join(parts))
        if not contexts:
            contexts = [item["answer"] or "(근거 없음)"]
        
        data["contexts"].append(contexts)
        data["ground_truth"].append(item["ground_truth"])
    
    return Dataset.from_dict(data)


def run_ragas_evaluation(results, openai_model="gpt-4o-mini", timeout_per_item=60, sleep_between=1.0):
    from ragas import evaluate as ragas_evaluate
    from ragas.metrics import faithfulness, answer_relevancy, context_precision
    from ragas.run_config import RunConfig
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    
    judge_llm = ChatOpenAI(model_name=openai_model, temperature=0)
    judge_embeddings = OpenAIEmbeddings()
    metrics = [faithfulness, answer_relevancy, context_precision]
    run_config = RunConfig(timeout=timeout_per_item, max_retries=2, max_workers=1)
    
    ds = prepare_ragas_dataset(results)
    
    all_rows = []
    print(f"\nRAGAS 평가 시작: {len(ds)}개")
    
    for i in range(len(ds)):
        subset = ds.select([i])
        print(f"[{i+1}/{len(ds)}] 평가 중...", end=" ", flush=True)
        
        try:
            res = ragas_evaluate(
                subset, metrics=metrics, llm=judge_llm,
                embeddings=judge_embeddings, run_config=run_config,
                show_progress=False,
            )
            df_one = res.to_pandas()
            all_rows.append(df_one)
            if not df_one.empty:
                row = df_one.iloc[0]
                f = row.get("faithfulness")
                r = row.get("answer_relevancy")
                p = row.get("context_precision")
                def fmt(x): return f"{x:.2f}" if x is not None and not pd.isna(x) else "nan"
                print(f"faith={fmt(f)}, rel={fmt(r)}, prec={fmt(p)}")
            time.sleep(sleep_between)
        except Exception as e:
            print(f"오류 (skip): {str(e)[:100]}")
            all_rows.append(pd.DataFrame([{
                "question": ds[i]["question"],
                "answer": ds[i]["answer"],
                "ground_truth": ds[i]["ground_truth"],
                "faithfulness": None,
                "answer_relevancy": None,
                "context_precision": None,
                "error": str(e)[:200],
            }]))
            time.sleep(3)
    
    return pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()


def summarize_ragas(df: pd.DataFrame) -> dict:
    metrics = ["faithfulness", "answer_relevancy", "context_precision"]
    summary = {}
    for m in metrics:
        if m in df.columns:
            valid = df[m].dropna()
            if len(valid) > 0:
                summary[f"{m}_mean"] = round(valid.mean(), 3)
                summary[f"{m}_std"] = round(valid.std(), 3)
                summary[f"{m}_n_valid"] = len(valid)
            else:
                summary[f"{m}_mean"] = None
    return summary


def compare_systems(paths, labels):
    all_summaries = []
    for path, label in zip(paths, labels):
        df = pd.read_csv(path)
        summary = summarize_ragas(df)
        summary["system"] = label
        summary["n_total"] = len(df)
        all_summaries.append(summary)
    
    result = pd.DataFrame(all_summaries)
    cols = ["system", "n_total"]
    for m in ["faithfulness", "answer_relevancy", "context_precision"]:
        for suffix in ["_mean", "_std", "_n_valid"]:
            col = f"{m}{suffix}"
            if col in result.columns:
                cols.append(col)
    return result[cols]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", help="파이프라인 결과 JSON 경로")
    parser.add_argument("--out", default="./eval_output.csv", help="출력 CSV 경로")
    parser.add_argument("--ragas", action="store_true", help="RAGAS 평가 실행")
    parser.add_argument("--compare", nargs=2, metavar=("CSV1", "CSV2"), help="두 CSV 비교")
    parser.add_argument("--labels", nargs="+", default=["new", "baseline"])
    parser.add_argument("--openai-model", default="gpt-4o-mini")
    args = parser.parse_args()
    
    if args.compare:
        result = compare_systems(args.compare, args.labels)
        print("\n=== 시스템 비교 ===")
        print(result.to_string(index=False))
        result.to_csv(args.out, index=False)
        print(f"\n저장: {args.out}")
        return
    
    if not args.results:
        parser.error("results 또는 compare 필요")
    
    with open(args.results, encoding="utf-8") as f:
        results = json.load(f)
    print(f"결과 로드: {len(results)}개 항목 ({args.results})")
    
    print("\n   1: 커스텀 지표   ")
    custom_df = evaluate_custom_metrics(results)
    custom_summary = summarize_custom(custom_df)
    
    print("\n커스텀 지표 요약:")
    for k, v in custom_summary.items():
        print(f"  {k}: {v}")
    
    custom_out = args.out.replace(".csv", "_custom.csv")
    custom_df.to_csv(custom_out, index=False, encoding="utf-8-sig")
    print(f"\n저장: {custom_out}")
    
    print("\nIntent별 정확도:")
    for intent in custom_df["intent"].unique():
        sub = custom_df[custom_df["intent"] == intent]
        print(f"  {intent}: {len(sub)}개")
        fact_acc = sub[sub["exact_number_match"] != -1.0]["exact_number_match"].mean()
        kw_cov = sub[sub["kw_coverage"] != -1.0]["kw_coverage"].mean()
        if not pd.isna(fact_acc):
            print(f"    숫자 정확도: {fact_acc:.2%}")
        if not pd.isna(kw_cov):
            print(f"    키워드 커버리지: {kw_cov:.2%}")
    
    if args.ragas:
        print("\n   2: RAGAS 평가   ")
        if not os.environ.get("OPENAI_API_KEY"):
            print("OPENAI_API_KEY 없음. RAGAS 건너뜀.")
            return
        
        ragas_df = run_ragas_evaluation(results, openai_model=args.openai_model)
        ragas_summary = summarize_ragas(ragas_df)
        
        print("\nRAGAS 요약:")
        for k, v in ragas_summary.items():
            print(f"  {k}: {v}")
        
        ragas_out = args.out.replace(".csv", "_ragas.csv")
        ragas_df.to_csv(ragas_out, index=False, encoding="utf-8-sig")
        print(f"\n저장: {ragas_out}")


if __name__ == "__main__":
    main()