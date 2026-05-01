"""
compare_results.py — 3개 시스템 결과 비교 (시스템 vs Baseline A vs Baseline B)

출력:
1. 카테고리별 답변 성공률 표
2. fact 질문 GT 정확도 표
3. 개별 질문별 비교 CSV
4. 논문용 요약 통계
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path


def load_results(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def status(answer: str) -> str:
    if not answer:
        return "빈답변"
    if "답변 생성 중 오류가 발생" in answer or "답변 생성 중 오류" in answer:
        return "오류"
    if "찾을 수 없" in answer or "확인할 수 없" in answer:
        return "정보없음"
    return "답변완료"


def extract_main_number(text: str) -> str | None:
    nums = re.findall(r"[\d,]+", text or "")
    nums = [n.replace(",", "") for n in nums if len(n.replace(",", "")) >= 4]
    if not nums:
        return None
    return max(nums, key=len)


def check_fact_accuracy(answer: str, ground_truth: str) -> bool:
    gt_nums = re.findall(r"[\d,]+", ground_truth)
    gt_nums = [n.replace(",", "") for n in gt_nums if len(n.replace(",", "")) >= 4]
    if not gt_nums:
        return False
    main_gt = max(gt_nums, key=len)
    
    ans_nums = re.findall(r"[\d,]+", answer or "")
    ans_nums = [n.replace(",", "") for n in ans_nums if len(n.replace(",", "")) >= 4]
    
    return main_gt in ans_nums


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ours", required=True, help="시스템 결과 JSON")
    parser.add_argument("--baseline-a", help="Baseline A (Naive RAG) 결과 JSON")
    parser.add_argument("--baseline-b", help="Baseline B (Table-to-Text) 결과 JSON")
    parser.add_argument("--eval-data", default="/content/eval_data.py",
                       help="eval_dataset 위치")
    parser.add_argument("--output-dir", default="/content/comparison",
                       help="CSV/요약 저장 경로")
    args = parser.parse_args()
    
    # eval_dataset 로드
    sys.path.insert(0, str(Path(args.eval_data).parent))
    mod_name = Path(args.eval_data).stem
    eval_module = __import__(mod_name)
    eval_dataset = eval_module.eval_dataset
    
    # 결과 로드
    systems = {"ours": load_results(args.ours)}
    if args.baseline_a:
        systems["baseline_a"] = load_results(args.baseline_a)
    if args.baseline_b:
        systems["baseline_b"] = load_results(args.baseline_b)
    
    # 결과 검증
    for name, results in systems.items():
        if len(results) != len(eval_dataset):
            print(f"⚠️ 경고: {name} 결과 {len(results)}개, eval 데이터 {len(eval_dataset)}개 — 크기 불일치")
    
    # 카테고리 추출
    def get_category(item, idx):
        if "_meta" in item:
            return item["_meta"].get("category", "원본")
        return "원본"
    
    # ==========================================
    # 1. 카테고리별 답변 성공률
    # ==========================================
    
    print("\n" + "=" * 90)
    print("1. 카테고리 별 답변 성공률")
    print("=" * 90)
    
    categories = {}  # {cat: [idx, ...]}
    for i, item in enumerate(eval_dataset):
        cat = get_category(item, i)
        categories.setdefault(cat, []).append(i)
    
    # 헤더
    headers = ["Category", "Total"] + list(systems.keys())
    print(f"{'Category':<18} | {'Total':>5} | " + " | ".join(f"{s:>14}" for s in systems.keys()))
    print("-" * 90)
    
    summary_table = []
    for cat, indices in categories.items():
        row = [cat, len(indices)]
        for sname, results in systems.items():
            ok = sum(1 for i in indices if status(results[i].get("answer", "")) == "답변완료")
            row.append(f"{ok}/{len(indices)} ({100*ok/len(indices):.0f}%)")
        summary_table.append(row)
        print(f"{cat:<18} | {len(indices):>5} | " + " | ".join(f"{v:>14}" for v in row[2:]))
    
    # 전체 합계
    print("-" * 90)
    total_row = ["전체", len(eval_dataset)]
    for sname, results in systems.items():
        ok = sum(1 for r in results if status(r.get("answer", "")) == "답변완료")
        total_row.append(f"{ok}/{len(results)} ({100*ok/len(results):.0f}%)")
    print(f"{'전체':<18} | {len(eval_dataset):>5} | " + " | ".join(f"{v:>14}" for v in total_row[2:]))
    
    # ==========================================
    # 2. Fact 질문 GT 정확도
    # ==========================================
    
    print("\n" + "=" * 90)
    print("2. Fact 질문 GT 숫자 매칭 (Fact 26개)")
    print("=" * 90)
    
    fact_cats = {"원본", "FY_fact", "HY_fact", "별도_fact", "전기_fact"}
    fact_indices = []
    for i, item in enumerate(eval_dataset):
        cat = get_category(item, i)
        if i < 10 or cat in {"FY_fact", "HY_fact", "별도_fact", "전기_fact"}:
            fact_indices.append(i)
    
    print(f"{'Category':<18} | {'Total':>5} | " + " | ".join(f"{s:>14}" for s in systems.keys()))
    print("-" * 90)
    
    for cat, indices in categories.items():
        fact_in_cat = [i for i in indices if i in fact_indices]
        if not fact_in_cat:
            continue
        row = [cat, len(fact_in_cat)]
        for sname, results in systems.items():
            correct = sum(1 for i in fact_in_cat 
                         if check_fact_accuracy(results[i].get("answer", ""), 
                                                eval_dataset[i]["ground_truth"]))
            row.append(f"{correct}/{len(fact_in_cat)} ({100*correct/len(fact_in_cat):.0f}%)")
        print(f"{cat:<18} | {len(fact_in_cat):>5} | " + " | ".join(f"{v:>14}" for v in row[2:]))
    
    print("-" * 90)
    row = ["전체 fact", len(fact_indices)]
    for sname, results in systems.items():
        correct = sum(1 for i in fact_indices 
                     if check_fact_accuracy(results[i].get("answer", ""), 
                                            eval_dataset[i]["ground_truth"]))
        row.append(f"{correct}/{len(fact_indices)} ({100*correct/len(fact_indices):.0f}%)")
    print(f"{'전체 fact':<18} | {len(fact_indices):>5} | " + " | ".join(f"{v:>14}" for v in row[2:]))
    
    # ==========================================
    # 3. 개별 비교 CSV
    # ==========================================
    
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    csv_path = Path(args.output_dir) / "per_question.csv"
    
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        cols = ["#", "category", "question", "ground_truth"]
        for sname in systems.keys():
            cols.extend([f"{sname}_status", f"{sname}_fact_correct", f"{sname}_answer"])
        writer.writerow(cols)
        
        for i, item in enumerate(eval_dataset):
            row = [i+1, get_category(item, i), item["question"], item["ground_truth"]]
            for sname, results in systems.items():
                ans = results[i].get("answer", "")
                row.append(status(ans))
                row.append("✓" if check_fact_accuracy(ans, item["ground_truth"]) else "")
                row.append(ans[:500])
            writer.writerow(row)
    
    print(f"\n▶ 개별 비교 CSV: {csv_path}")
    
    # ==========================================
    # 4. 요약 JSON
    # ==========================================
    
    summary = {"systems": {}}
    
    for sname, results in systems.items():
        total_ans = sum(1 for r in results if status(r.get("answer", "")) == "답변완료")
        total_err = sum(1 for r in results if status(r.get("answer", "")) == "오류")
        total_none = sum(1 for r in results if status(r.get("answer", "")) == "정보없음")
        
        fact_correct = sum(1 for i in fact_indices 
                          if check_fact_accuracy(results[i].get("answer", ""), 
                                                 eval_dataset[i]["ground_truth"]))
        
        summary["systems"][sname] = {
            "total_questions": len(results),
            "answered": total_ans,
            "errors_external": total_err,
            "info_not_found": total_none,
            "answer_rate_pct": round(100 * total_ans / len(results), 1),
            "fact_accuracy": f"{fact_correct}/{len(fact_indices)}",
            "fact_accuracy_pct": round(100 * fact_correct / len(fact_indices), 1),
            "avg_elapsed_sec": round(sum(r.get("elapsed", 0) for r in results) / len(results), 2),
        }
    
    summary_path = Path(args.output_dir) / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"▶ 요약 JSON: {summary_path}")
    
    # 최종 요약 테이블 (논문용)
    print("\n" + "=" * 90)
    print("논문용 최종 요약")
    print("=" * 90)
    for sname, stats in summary["systems"].items():
        print(f"\n[{sname}]")
        for k, v in stats.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
