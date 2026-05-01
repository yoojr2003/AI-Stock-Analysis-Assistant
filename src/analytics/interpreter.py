"""
interpreter.py — 재무 비율 자동 해석 모듈

7개 재무 비율에 대해 자동 생성:
  1. 절대 수준 평가 (우수/양호/주의/위험)
  2. 의미 해석
  3. 종합 평가
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ==========================================
# 비율 해석 정의
# ==========================================

# 등급: "excellent" (매우 우수), "good" (양호), "fair" (보통), "warning" (주의), "danger" (위험)

RATIO_THRESHOLDS = {
    "유동비율": {
        "thresholds": [(2.0, "excellent"), (1.5, "good"), (1.0, "fair"), (0.5, "warning")],
        "default": "danger",
        "higher_is_better": True,
        "unit": "배",
        "labels": {
            "excellent": "매우 우수",
            "good": "양호",
            "fair": "보통",
            "warning": "단기 지급 능력 약함",
            "danger": "심각한 유동성 위험",
        },
        "explanations": {
            "excellent": "1년 내 갚아야 할 빚의 2배 이상 현금성 자산을 보유하고 있어, 단기 지급 능력이 매우 안정적입니다.",
            "good": "유동부채를 충분히 감당할 수 있는 수준입니다.",
            "fair": "유동부채 정도의 자산을 보유 중. 큰 위험은 없으나 안전 마진이 적습니다.",
            "warning": "유동부채를 모두 갚기에 자산이 부족합니다. 추가 현금 확보가 필요합니다.",
            "danger": "단기 채무 불이행 위험이 매우 높습니다.",
        },
    },
    "부채비율": {
        "thresholds": [(1.0, "excellent"), (2.0, "good"), (4.0, "fair"), (8.0, "warning")],
        "default": "danger",
        "higher_is_better": False,  # 낮을수록 좋음
        "unit": "배",
        "labels": {
            "excellent": "매우 안정",
            "good": "양호",
            "fair": "보통",
            "warning": "부채 부담 큼",
            "danger": "심각한 재무 위험",
        },
        "explanations": {
            "excellent": "자기자본이 부채보다 많아 매우 안정적인 재무 구조입니다.",
            "good": "자기자본 대비 부채 수준이 적정 범위입니다.",
            "fair": "부채가 자기자본의 2-4배 수준. 일부 산업(통신·항공)에서는 일반적입니다.",
            "warning": "부채 비중이 매우 큽니다. 금리 인상이나 실적 악화 시 위험합니다.",
            "danger": "재무 안정성이 심각하게 위협받는 수준입니다.",
        },
    },
    "자기자본비율": {
        "thresholds": [(50.0, "excellent"), (35.0, "good"), (25.0, "fair"), (15.0, "warning")],
        "default": "danger",
        "higher_is_better": True,
        "unit": "%",
        "labels": {
            "excellent": "매우 안정",
            "good": "양호",
            "fair": "보통",
            "warning": "재무 취약",
            "danger": "재무 위험",
        },
        "explanations": {
            "excellent": "자산의 절반 이상이 자기자본. 매우 보수적이고 안정적인 재무 구조입니다.",
            "good": "건전한 자기자본 비중을 유지하고 있습니다.",
            "fair": "일반적 수준. 업종별로 차이가 큽니다.",
            "warning": "자산의 대부분이 부채로 구성되어 있어 재무 취약성이 높습니다.",
            "danger": "자본잠식 또는 그에 준하는 상태일 수 있습니다.",
        },
    },
    "영업이익률": {
        "thresholds": [(20.0, "excellent"), (10.0, "good"), (5.0, "fair"), (1.0, "warning")],
        "default": "danger",
        "higher_is_better": True,
        "unit": "%",
        "labels": {
            "excellent": "매우 우수",
            "good": "양호",
            "fair": "보통",
            "warning": "수익성 부진",
            "danger": "영업적자",
        },
        "explanations": {
            "excellent": "매출 대비 영업이익이 매우 높음. 강력한 사업 경쟁력 또는 고마진 산업의 특징입니다.",
            "good": "본업 수익성이 양호합니다. 일반적 제조업 평균을 상회합니다.",
            "fair": "유통·소비재·자동차 업종에서 일반적인 수준입니다.",
            "warning": "본업 수익성이 약합니다. 가격 경쟁력 또는 비용 구조 점검이 필요합니다.",
            "danger": "영업 손실 또는 그에 가까운 상태입니다.",
        },
    },
    "순이익률": {
        "thresholds": [(15.0, "excellent"), (7.0, "good"), (3.0, "fair"), (0.0, "warning")],
        "default": "danger",
        "higher_is_better": True,
        "unit": "%",
        "labels": {
            "excellent": "매우 우수",
            "good": "양호",
            "fair": "보통",
            "warning": "수익성 미흡",
            "danger": "순손실",
        },
        "explanations": {
            "excellent": "이자비용·세금까지 차감한 최종 수익성이 매우 우수합니다.",
            "good": "최종 수익성이 양호합니다.",
            "fair": "최종 수익성이 평이한 수준입니다.",
            "warning": "영업외 비용이 크거나 본업 수익성이 약한 상태입니다.",
            "danger": "당기순손실 상태입니다.",
        },
    },
    "ROA": {
        "thresholds": [(10.0, "excellent"), (5.0, "good"), (2.0, "fair"), (0.0, "warning")],
        "default": "danger",
        "higher_is_better": True,
        "unit": "%",
        "labels": {
            "excellent": "매우 우수",
            "good": "양호",
            "fair": "보통",
            "warning": "자산 효율 미흡",
            "danger": "자산 손실",
        },
        "explanations": {
            "excellent": "보유 자산을 매우 효율적으로 활용하여 수익을 창출하고 있습니다.",
            "good": "자산 활용이 양호한 수준입니다.",
            "fair": "자산 효율이 평이합니다.",
            "warning": "자산 대비 수익이 미흡합니다. 자본 효율이 낮습니다.",
            "danger": "자산이 손실을 발생시키고 있습니다.",
        },
    },
    "ROE": {
        "thresholds": [(15.0, "excellent"), (10.0, "good"), (5.0, "fair"), (0.0, "warning")],
        "default": "danger",
        "higher_is_better": True,
        "unit": "%",
        "labels": {
            "excellent": "매우 우수",
            "good": "양호",
            "fair": "보통",
            "warning": "자본 효율 미흡",
            "danger": "자본 손실",
        },
        "explanations": {
            "excellent": "주주가 투자한 자본 대비 매우 높은 수익률을 창출하고 있습니다. 워런 버핏이 강조하는 우수 기업의 기준입니다.",
            "good": "자기자본 대비 수익률이 양호합니다.",
            "fair": "자본 효율이 평이합니다.",
            "warning": "자기자본 대비 수익이 미흡합니다.",
            "danger": "자기자본이 손실을 보고 있는 상태입니다.",
        },
    },
}


# ==========================================
# 평가 함수
# ==========================================

@dataclass
class RatioInterpretation:
    name: str           # 비율 이름
    value: Optional[float]   # 값
    display: str        # 표시용 문자열
    grade: str          # 등급 (excellent/good/fair/warning/danger)
    label: str          # 등급 한글
    explanation: str    # 해석 텍스트
    icon: str           # 시각화 아이콘 (✅/👍/🟡/⚠️/🔴)


GRADE_ICONS = {
    "excellent": "✅",
    "good": "👍",
    "fair": "🟡",
    "warning": "⚠️",
    "danger": "🔴",
}


def evaluate_ratio(name: str, value: Optional[float],
                    display: Optional[str] = None,
                    use_percent: bool = None) -> RatioInterpretation:
    """
    단일 비율 평가
    
    Args:
        name: 비율 이름 (한글, RATIO_THRESHOLDS 키와 일치해야 함)
        value: 비율 값 (예: 0.0586 OR 5.86 — 어떤 단위인지 use_percent로 명시)
        display: 표시용 문자열 (없으면 value로 자동 생성)
        use_percent: True면 value가 이미 % 단위 (5.86 → 5.86%)
                     False면 value가 비율(0.0586 → 5.86%)
                     None이면 룰의 unit을 보고 자동 판단
    Returns:
        RatioInterpretation 객체
    """
    if name not in RATIO_THRESHOLDS:
        return RatioInterpretation(
            name=name, value=value, display=display or "N/A",
            grade="unknown", label="평가 불가", explanation="해석 룰 없음",
            icon="❓",
        )
    
    rule = RATIO_THRESHOLDS[name]
    
    if value is None:
        return RatioInterpretation(
            name=name, value=None, display="N/A",
            grade="unknown", label="데이터 없음", explanation="값이 없어 평가할 수 없습니다.",
            icon="❓",
        )
    
    # 단위 정규화
    if use_percent is None:
        unit = rule.get("unit", "")
        if "%" in unit and value < 1.0 and value > -1.0:
            value_pct = value * 100
        else:
            value_pct = value
    else:
        value_pct = value * 100 if use_percent is False else value
    
    # 등급 판정
    grade = rule["default"]
    higher_is_better = rule["higher_is_better"]
    thresholds = rule["thresholds"]  # [(threshold, grade), ...]
    
    for threshold, g in thresholds:
        if higher_is_better:
            if value_pct >= threshold:
                grade = g
                break
        else:
            if value_pct <= threshold:
                grade = g
                break
    
    label = rule["labels"].get(grade, grade)
    explanation = rule["explanations"].get(grade, "")
    icon = GRADE_ICONS.get(grade, "❓")
    
    return RatioInterpretation(
        name=name,
        value=value,
        display=display or f"{value_pct:.2f}{rule.get('unit', '')}",
        grade=grade,
        label=label,
        explanation=explanation,
        icon=icon,
    )


def interpret_ratios(ratios_data: dict) -> dict[str, RatioInterpretation]:
    """
    analytics.calculate_ratios의 결과를 받아 모든 비율을 해석
    
    Args:
        ratios_data: analytics.calculate_ratios() 반환값
            {
                "corp_name": str,
                "year": int,
                "ratios": {
                    "유동비율": {"value": 2.33, "display": "2.33배", ...},
                    ...
                }
            }
    Returns:
        {비율명: RatioInterpretation}
    """
    result = {}
    raw = ratios_data.get("ratios", {})
    
    for name, rdict in raw.items():
        if not rdict:
            continue
        value = rdict.get("value")
        display = rdict.get("display")
        mult = rdict.get("display_multiplier", 1)
        use_percent = False if mult == 100 else (None if mult == 1 else None)
        
        interp = evaluate_ratio(name, value, display, use_percent=use_percent)
        result[name] = interp
    
    return result


# ==========================================
# 종합 평가
# ==========================================

def generate_summary(interpretations: dict[str, RatioInterpretation],
                     yoy_data: Optional[dict] = None) -> str:
    """
    모든 비율 해석을 종합해 한글 요약 생성
    
    Args:
        interpretations: interpret_ratios() 결과
        yoy_data: 전년 대비 데이터 (선택, 트렌드 코멘트 추가용)
    Returns:
        종합 평가 문자열
    """
    if not interpretations:
        return "분석할 데이터가 없습니다."
    
    # 등급별 카운트
    grade_count = {"excellent": 0, "good": 0, "fair": 0, "warning": 0, "danger": 0, "unknown": 0}
    for interp in interpretations.values():
        grade_count[interp.grade] = grade_count.get(interp.grade, 0) + 1
    
    total = sum(grade_count[g] for g in ["excellent", "good", "fair", "warning", "danger"])
    
    if total == 0:
        return "비율 데이터가 충분하지 않습니다."
    
    # 카테고리별 비율
    profitability_keys = ["영업이익률", "순이익률", "ROA", "ROE"]
    stability_keys = ["유동비율", "부채비율", "자기자본비율"]
    
    profit_grades = [interpretations[k].grade for k in profitability_keys if k in interpretations]
    stab_grades = [interpretations[k].grade for k in stability_keys if k in interpretations]
    
    # 종합 등급 판정
    def majority_grade(grades):
        if not grades:
            return None
        counts = {}
        for g in grades:
            counts[g] = counts.get(g, 0) + 1
        return max(counts.items(), key=lambda x: x[1])[0]
    
    profit_overall = majority_grade(profit_grades)
    stab_overall = majority_grade(stab_grades)
    
    # 요약 생성
    lines = []
    
    if profit_overall:
        profit_label_map = {
            "excellent": "매우 우수",
            "good": "양호",
            "fair": "평이",
            "warning": "부진",
            "danger": "위험",
        }
        lines.append(f"💰 **수익성**: {profit_label_map.get(profit_overall, profit_overall)}")
    
    if stab_overall:
        stab_label_map = {
            "excellent": "매우 안정",
            "good": "양호",
            "fair": "보통",
            "warning": "취약",
            "danger": "위험",
        }
        lines.append(f"🏦 **재무 안정성**: {stab_label_map.get(stab_overall, stab_overall)}")
    
    # 핵심 코멘트
    comments = []
    
    if "ROE" in interpretations and "영업이익률" in interpretations:
        roe_grade = interpretations["ROE"].grade
        opm_grade = interpretations["영업이익률"].grade
        if roe_grade == "excellent" and "부채비율" in interpretations:
            db_grade = interpretations["부채비율"].grade
            if db_grade in ["warning", "danger"]:
                comments.append("⚠️ 높은 ROE는 부채 의존이 큰 결과일 수 있습니다.")
    
    if "영업이익률" in interpretations and "순이익률" in interpretations:
        op = interpretations["영업이익률"]
        net = interpretations["순이익률"]
        if op.value is not None and net.value is not None:
            try:
                op_pct = op.value * 100 if op.value < 1.0 else op.value
                net_pct = net.value * 100 if net.value < 1.0 else net.value
                if op_pct - net_pct > 5:
                    comments.append("📊 영업이익률에 비해 순이익률이 낮습니다. 금융비용 또는 영업외 손실이 큽니다.")
                elif net_pct - op_pct > 3:
                    comments.append("📊 순이익률이 영업이익률보다 높습니다. 일회성 영업외 이익(자산매각 등)이 있었을 수 있습니다.")
            except (TypeError, AttributeError):
                pass
    
    if yoy_data:
        yoy = yoy_data.get("yoy", {}) if isinstance(yoy_data, dict) else {}
        if "매출액" in yoy and "영업이익" in yoy:
            sales_pct = yoy["매출액"].get("change_pct")
            op_pct = yoy["영업이익"].get("change_pct")
            if sales_pct is not None and op_pct is not None:
                if sales_pct > 0 and op_pct < 0:
                    comments.append("매출은 증가했으나 영업이익은 감소했습니다. *마진 압박* 신호입니다.")
                elif sales_pct < 0 and op_pct > 0:
                    comments.append("매출 감소에도 영업이익은 증가. 비용 효율화가 이루어지고 있습니다.")
                elif sales_pct > 5 and op_pct > sales_pct:
                    comments.append("매출과 영업이익이 모두 빠르게 성장 중. 매우 긍정적 신호입니다.")
    
    # 최종 조합
    if lines:
        body = "\n".join(lines)
    else:
        body = "비율 평가 데이터 부족"
    
    if comments:
        body += "\n\n" + "\n".join(comments)
    
    return body


def format_interpretations(interpretations: dict[str, RatioInterpretation]) -> list[dict]:
    """UI에서 사용하기 쉬운 형식으로 변환"""
    return [
        {
            "name": interp.name,
            "value": interp.value,
            "display": interp.display,
            "grade": interp.grade,
            "label": interp.label,
            "explanation": interp.explanation,
            "icon": interp.icon,
        }
        for interp in interpretations.values()
    ]


# ==========================================
# 테스트
# ==========================================

if __name__ == "__main__":
    # 삼성전자 실제 데이터로 테스트
    test_data = {
        "corp_name": "삼성전자",
        "year": 2025,
        "ratios": {
            "유동비율": {"value": 2.33, "display": "2.33배", "display_multiplier": 1},
            "부채비율": {"value": 0.30, "display": "0.30배", "display_multiplier": 1},
            "자기자본비율": {"value": 0.7696, "display": "76.96%", "display_multiplier": 100},
            "영업이익률": {"value": 0.0981, "display": "9.81%", "display_multiplier": 100},
            "순이익률": {"value": 0.1066, "display": "10.66%", "display_multiplier": 100},
            "ROA": {"value": 0.0451, "display": "4.51%", "display_multiplier": 100},
            "ROE": {"value": 0.0586, "display": "5.86%", "display_multiplier": 100},
        }
    }
    
    yoy_test = {
        "yoy": {
            "매출액": {"change_pct": 6.5},
            "영업이익": {"change_pct": -10.3},
        }
    }
    
    print("=" * 70)
    print("삼성전자 2025 재무 비율 해석")
    print("=" * 70)
    
    interps = interpret_ratios(test_data)
    for name, interp in interps.items():
        print(f"\n{interp.icon} {interp.name}: {interp.display} - {interp.label}")
        print(f"   {interp.explanation}")
    
    print("\n" + "=" * 70)
    print("종합 평가")
    print("=" * 70)
    print(generate_summary(interps, yoy_test))
    
    # SK하이닉스 (높은 ROE) 시뮬레이션
    print("\n\n" + "=" * 70)
    print("SK하이닉스 시뮬레이션 (ROE 22.96%, 영업이익률 43.59%)")
    print("=" * 70)
    sk_data = {
        "ratios": {
            "유동비율": {"value": 1.86, "display": "1.86배", "display_multiplier": 1},
            "부채비율": {"value": 0.46, "display": "0.46배", "display_multiplier": 1},
            "자기자본비율": {"value": 0.6852, "display": "68.52%", "display_multiplier": 100},
            "영업이익률": {"value": 0.4359, "display": "43.59%", "display_multiplier": 100},
            "순이익률": {"value": 0.4307, "display": "43.07%", "display_multiplier": 100},
            "ROA": {"value": 0.1573, "display": "15.73%", "display_multiplier": 100},
            "ROE": {"value": 0.2296, "display": "22.96%", "display_multiplier": 100},
        }
    }
    interps_sk = interpret_ratios(sk_data)
    for name, interp in interps_sk.items():
        print(f"  {interp.icon} {name}: {interp.display} ({interp.label})")
    print("\n" + generate_summary(interps_sk))
