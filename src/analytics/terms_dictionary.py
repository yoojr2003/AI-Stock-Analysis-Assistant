"""
terms_dictionary.py — 금융/회계 용어 사전 (50개)

7개 카테고리:
  1. 수익성 (8): PER, PBR, EPS, ROE, ROA, 영업이익률, 순이익률, EBITDA
  2. 안정성 (5): 부채비율, 유동비율, 자기자본비율, 이자보상비율, 당좌비율
  3. 성장성 (4): 매출성장률, 영업이익성장률, EPS성장률, 자산성장률
  4. 활동성 (4): 자산회전율, 재고자산회전율, 매출채권회전율, 자기자본회전율
  5. 재무제표 (10): 자산총계, 부채총계, 자본총계, 매출액, 영업이익, 당기순이익,
                  유동자산, 유동부채, 매출원가, 현금및현금성자산
  6. 시장 (8): 시가총액, 거래량, 배당수익률, 배당성향, 주가, 주당배당금,
              유통주식수, 주가수익비율
  7. 공시/제도 (6): DART, XBRL, 사업보고서, 반기보고서, 분기보고서, 연결재무제표
  8. 회계 (5): 발생주의, 감가상각, 자본화, 영업현금흐름, 잉여현금흐름
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class TermDefinition:
    """용어 정의."""
    term: str                       # 용어 (한글/영문)
    name_full: str                  # 전체 명칭
    category: str                   # 카테고리
    definition: str                 # 기본 정의
    formula: Optional[str] = None   # 계산식
    interpretation: str = ""        # 해석 가이드
    related: list[str] = None       # 관련 용어
    example: Optional[str] = None   # 예시


# ==========================================
# 50개 용어 데이터
# ==========================================

TERMS_DB: list[TermDefinition] = [
    # ========================================
    # 1. 수익성 지표 (8개)
    # ========================================
    TermDefinition(
        term="PER",
        name_full="PER (Price-to-Earnings Ratio, 주가수익비율)",
        category="수익성",
        definition="주가가 주당순이익(EPS)의 몇 배에 거래되는지 나타내는 지표입니다. "
                   "주식의 가격이 회사 이익에 비해 비싼지/싼지를 평가하는 가장 기본적인 지표입니다.",
        formula="주가 ÷ 주당순이익(EPS)",
        interpretation="낮을수록 저평가로 해석되지만, 업종 평균 및 성장성과 함께 봐야 합니다. "
                       "성장주는 PER이 높아도 정상이고, 가치주는 PER이 낮은 편입니다. "
                       "PER < 10: 저평가 가능성, 10~20: 적정 수준, > 25: 고평가 또는 고성장 기대.",
        related=["EPS", "PBR", "ROE"],
        example="삼성전자 주가 70,000원, EPS 5,000원이면 PER = 14배",
    ),
    TermDefinition(
        term="PBR",
        name_full="PBR (Price-to-Book Ratio, 주가순자산비율)",
        category="수익성",
        definition="주가가 주당순자산(BPS)의 몇 배인지 나타냅니다. "
                   "회사가 청산할 때 주주가 받을 수 있는 자산 대비 현재 주가 수준을 측정합니다.",
        formula="주가 ÷ 주당순자산(BPS)",
        interpretation="1배 미만이면 청산가치보다 싸게 거래된다는 의미로 저평가 신호입니다. "
                       "다만 부동산·자원 기업은 PBR이 낮은 게 흔하고, IT·서비스 기업은 무형자산 때문에 PBR이 높을 수 있습니다.",
        related=["PER", "BPS", "ROE"],
    ),
    TermDefinition(
        term="EPS",
        name_full="EPS (Earnings Per Share, 주당순이익)",
        category="수익성",
        definition="당기순이익을 발행주식수로 나눈 값으로, 주식 1주가 1년간 벌어들인 이익을 나타냅니다.",
        formula="당기순이익 ÷ 발행주식수",
        interpretation="높을수록 좋고, 매년 꾸준히 증가하는 기업이 우수합니다. "
                       "EPS 성장률은 주가 상승과 가장 직접적 상관관계를 가진 지표입니다.",
        related=["PER", "당기순이익", "EPS성장률"],
    ),
    TermDefinition(
        term="ROE",
        name_full="ROE (Return on Equity, 자기자본이익률)",
        category="수익성",
        definition="자기자본 대비 당기순이익의 비율로, 주주가 투자한 돈으로 기업이 얼마나 이익을 냈는지 측정합니다. "
                   "워런 버핏이 가장 중요시하는 지표 중 하나입니다.",
        formula="당기순이익 ÷ 자기자본 × 100",
        interpretation="일반적으로 15% 이상이면 우수, 10~15% 양호, 10% 미만은 저조한 수준입니다. "
                       "단, 부채를 많이 써서 ROE가 인위적으로 높아질 수 있으니 부채비율과 함께 봐야 합니다.",
        related=["ROA", "당기순이익", "자기자본비율"],
        example="삼성전자 ROE 5.86% → 자본 100원당 5.86원의 순이익",
    ),
    TermDefinition(
        term="ROA",
        name_full="ROA (Return on Assets, 총자산이익률)",
        category="수익성",
        definition="총자산 대비 당기순이익의 비율로, 기업이 가진 자산 전체로 얼마나 효율적으로 이익을 만들어내는지 측정합니다.",
        formula="당기순이익 ÷ 총자산 × 100",
        interpretation="ROA 5% 이상이면 양호, 10% 이상이면 매우 우수합니다. "
                       "ROE와 함께 보면 자본 구조까지 분석할 수 있습니다 (ROE >> ROA면 부채 많음).",
        related=["ROE", "자산총계", "당기순이익"],
    ),
    TermDefinition(
        term="영업이익률",
        name_full="영업이익률 (Operating Margin)",
        category="수익성",
        definition="매출액 대비 영업이익의 비율로, 본업에서 얼마나 효율적으로 돈을 버는지 보여주는 핵심 수익성 지표입니다.",
        formula="영업이익 ÷ 매출액 × 100",
        interpretation="업종에 따라 다릅니다. 반도체 30%+, 유통 5% 내외가 평균. "
                       "전년 대비 영업이익률 변화가 매출 변화보다 중요합니다 (마진 압박 신호).",
        related=["순이익률", "매출액", "영업이익"],
        example="SK하이닉스 영업이익률 43.59% (반도체 호황기)",
    ),
    TermDefinition(
        term="순이익률",
        name_full="순이익률 (Net Profit Margin)",
        category="수익성",
        definition="매출액 대비 당기순이익의 비율로, 영업뿐 아니라 금융손익·세금까지 포함한 최종 수익성을 측정합니다.",
        formula="당기순이익 ÷ 매출액 × 100",
        interpretation="영업이익률과 큰 차이가 나면 영업외손익이나 일회성 비용/이익이 큰 영향을 주는 것입니다. "
                       "장기 추세와 비교가 중요.",
        related=["영업이익률", "당기순이익"],
    ),
    TermDefinition(
        term="EBITDA",
        name_full="EBITDA (Earnings Before Interest, Taxes, Depreciation and Amortization)",
        category="수익성",
        definition="이자·세금·감가상각비 차감 전 이익. 기업의 영업현금 창출력을 평가하는 지표로, 자본구조와 회계방식 차이를 배제하고 기업 간 비교에 유용합니다.",
        formula="영업이익 + 감가상각비 + 무형자산상각비",
        interpretation="설비투자가 많은 산업(통신, 항공, 반도체)에서 주요 지표. EV/EBITDA 비율은 PER 대안으로 자주 쓰입니다.",
        related=["영업이익", "감가상각", "EV/EBITDA"],
    ),
    
    # ========================================
    # 2. 안정성 지표 (5개)
    # ========================================
    TermDefinition(
        term="부채비율",
        name_full="부채비율 (Debt-to-Equity Ratio)",
        category="안정성",
        definition="자기자본 대비 부채의 비율로, 기업이 빚으로 운영되는 정도를 측정합니다.",
        formula="부채총계 ÷ 자기자본 × 100",
        interpretation="100% 이하면 매우 안정, 200% 이하 양호, 400% 초과는 위험 신호. "
                       "단 금융업·항공업은 부채비율이 높은 게 정상이라 업종별 비교 필요.",
        related=["자기자본비율", "유동비율"],
        example="삼성전자 부채비율 30% (매우 안정적)",
    ),
    TermDefinition(
        term="유동비율",
        name_full="유동비율 (Current Ratio)",
        category="안정성",
        definition="유동부채 대비 유동자산의 비율로, 1년 안에 갚아야 할 빚을 1년 안에 현금화 가능한 자산으로 갚을 수 있는지를 측정합니다.",
        formula="유동자산 ÷ 유동부채",
        interpretation="2.0배 이상 매우 양호, 1.5~2.0 양호, 1.0 미만은 단기 지급 능력 부족 위험. "
                       "단기 유동성 위기 가능성 판단에 가장 직접적인 지표.",
        related=["당좌비율", "유동자산", "유동부채"],
        example="삼성전자 유동비율 2.33배 (매우 안정)",
    ),
    TermDefinition(
        term="자기자본비율",
        name_full="자기자본비율 (Equity Ratio)",
        category="안정성",
        definition="총자산 중 자기자본이 차지하는 비율로, 기업이 부채에 의존하지 않고 자체 자본으로 운영되는 정도를 보여줍니다.",
        formula="자기자본 ÷ 총자산 × 100",
        interpretation="50% 이상이면 매우 안정, 30~50% 양호, 20% 미만은 재무 취약. "
                       "100% - 부채비율(자산 대비)과 같은 의미.",
        related=["부채비율", "자산총계", "자본총계"],
    ),
    TermDefinition(
        term="이자보상비율",
        name_full="이자보상비율 (Interest Coverage Ratio)",
        category="안정성",
        definition="영업이익이 이자비용의 몇 배인지 나타내는 지표로, 영업으로 번 돈으로 이자를 갚을 수 있는 능력을 측정합니다.",
        formula="영업이익 ÷ 이자비용",
        interpretation="1.0 미만이면 영업이익으로 이자도 못 갚는 좀비 기업. "
                       "5배 이상이 안전, 3배 이상 양호, 1.5배 미만 주의.",
        related=["영업이익", "부채비율"],
    ),
    TermDefinition(
        term="당좌비율",
        name_full="당좌비율 (Quick Ratio)",
        category="안정성",
        definition="유동비율에서 재고자산을 뺀 더 보수적인 단기 지급 능력 지표입니다.",
        formula="(유동자산 - 재고자산) ÷ 유동부채",
        interpretation="재고자산은 즉시 현금화가 어려울 수 있으므로 더 엄격한 기준입니다. "
                       "1.0 이상이면 매우 안정.",
        related=["유동비율", "재고자산"],
    ),
    
    # ========================================
    # 3. 성장성 지표 (4개)
    # ========================================
    TermDefinition(
        term="매출성장률",
        name_full="매출성장률 (Revenue Growth Rate)",
        category="성장성",
        definition="전년 동기 대비 매출액 증가율로, 기업이 외형적으로 얼마나 빠르게 성장하는지 측정합니다.",
        formula="(당기 매출 - 전기 매출) ÷ 전기 매출 × 100",
        interpretation="시장 평균(GDP 성장률 + α) 이상이면 양호. "
                       "산업 평균 대비 비교가 중요. 성장률 둔화가 주가 하락 신호로 작용하기도 합니다.",
        related=["매출액", "영업이익성장률"],
    ),
    TermDefinition(
        term="영업이익성장률",
        name_full="영업이익성장률 (Operating Income Growth Rate)",
        category="성장성",
        definition="전년 동기 대비 영업이익 증가율로, 본업 수익성의 성장을 측정합니다.",
        formula="(당기 영업이익 - 전기 영업이익) ÷ 전기 영업이익 × 100",
        interpretation="매출성장률보다 영업이익성장률이 높으면 마진 개선 중. "
                       "반대면 외형은 키우지만 수익성은 악화 중이라는 신호.",
        related=["매출성장률", "영업이익률"],
    ),
    TermDefinition(
        term="EPS성장률",
        name_full="EPS성장률 (EPS Growth Rate)",
        category="성장성",
        definition="주당순이익(EPS)의 전년 대비 증가율로, 주주 입장에서 가장 직접적인 가치 성장 지표입니다.",
        formula="(당기 EPS - 전기 EPS) ÷ 전기 EPS × 100",
        interpretation="장기 EPS 성장률은 장기 주가 상승률과 거의 일치합니다. "
                       "PEG (PER ÷ EPS성장률)는 PER의 적정성을 평가하는 도구.",
        related=["EPS", "PER", "PEG"],
    ),
    TermDefinition(
        term="자산성장률",
        name_full="자산성장률 (Asset Growth Rate)",
        category="성장성",
        definition="전년 대비 총자산 증가율. 기업이 사업 규모를 얼마나 키우고 있는지 보여줍니다.",
        formula="(당기 자산 - 전기 자산) ÷ 전기 자산 × 100",
        interpretation="자산이 빠르게 늘어도 매출/이익이 따라오지 않으면 자본 효율 악화. ROA 하락 동반 시 주의.",
        related=["자산총계", "ROA"],
    ),
    
    # ========================================
    # 4. 활동성 지표 (4개)
    # ========================================
    TermDefinition(
        term="자산회전율",
        name_full="자산회전율 (Asset Turnover)",
        category="활동성",
        definition="총자산을 매출로 몇 번 회전시켰는지를 나타내는 자본 효율성 지표입니다.",
        formula="매출액 ÷ 평균 총자산",
        interpretation="1.0 이상이면 효율적. 유통·소비재는 높고, 통신·인프라는 낮은 게 일반적. "
                       "ROA = 순이익률 × 자산회전율로 분해 가능.",
        related=["자산총계", "ROA"],
    ),
    TermDefinition(
        term="재고자산회전율",
        name_full="재고자산회전율 (Inventory Turnover)",
        category="활동성",
        definition="재고자산이 1년에 몇 번 팔려나가는지 측정. 재고 관리 효율성과 판매 속도를 보여줍니다.",
        formula="매출원가 ÷ 평균 재고자산",
        interpretation="높을수록 재고 회전 빠름 = 판매 양호. 너무 낮으면 악성 재고 우려, "
                       "너무 높으면 결품·기회비용 발생 가능.",
        related=["재고자산", "매출원가"],
    ),
    TermDefinition(
        term="매출채권회전율",
        name_full="매출채권회전율 (Receivables Turnover)",
        category="활동성",
        definition="외상 매출이 얼마나 빨리 현금으로 회수되는지 측정. 회수 능력과 신용 관리 수준을 보여줍니다.",
        formula="매출액 ÷ 평균 매출채권",
        interpretation="낮으면 부실채권 증가 위험. "
                       "365 ÷ 회전율 = 매출채권 회수일수 (DSO).",
        related=["매출채권"],
    ),
    TermDefinition(
        term="자기자본회전율",
        name_full="자기자본회전율 (Equity Turnover)",
        category="활동성",
        definition="자기자본을 매출로 몇 번 회전시켰는지 측정. 자본의 효율적 활용도를 보여줍니다.",
        formula="매출액 ÷ 평균 자기자본",
        interpretation="ROE = 순이익률 × 자기자본회전율로 분해 가능. 듀폰 분석의 핵심 요소.",
        related=["자본총계", "ROE"],
    ),
    
    # ========================================
    # 5. 재무제표 항목 (10개)
    # ========================================
    TermDefinition(
        term="자산총계",
        name_full="자산총계 (Total Assets)",
        category="재무제표",
        definition="기업이 보유한 모든 경제적 자원의 합계. 유동자산 + 비유동자산.",
        interpretation="기업 규모를 나타내지만, 자산이 많다고 무조건 좋은 게 아님. "
                       "ROA, 자산회전율 같은 효율성 지표와 함께 봐야 함.",
        related=["유동자산", "부채총계", "자본총계"],
    ),
    TermDefinition(
        term="부채총계",
        name_full="부채총계 (Total Liabilities)",
        category="재무제표",
        definition="기업이 갚아야 할 모든 빚의 합계. 유동부채 + 비유동부채.",
        interpretation="절대값보다 자본 대비 비율(부채비율)이 중요. "
                       "급증 시 차입 확대 또는 사업 확장의 신호.",
        related=["유동부채", "자본총계", "부채비율"],
    ),
    TermDefinition(
        term="자본총계",
        name_full="자본총계 (Total Equity)",
        category="재무제표",
        definition="자산에서 부채를 뺀 순자산. 주주에게 귀속되는 회사의 가치.",
        formula="자산총계 - 부채총계",
        interpretation="자본총계가 꾸준히 증가하면 사업이 성장 중. "
                       "자본잠식(자본 < 자본금)은 위험 신호.",
        related=["자산총계", "부채총계", "자기자본비율"],
    ),
    TermDefinition(
        term="매출액",
        name_full="매출액 (Revenue, Sales)",
        category="재무제표",
        definition="기업이 본업 활동으로 벌어들인 총 수입. 영업수익이라고도 함.",
        interpretation="회사의 외형 규모. "
                       "매출 증가가 영업이익 증가로 이어지지 않으면 마진 압박 신호.",
        related=["영업이익", "매출원가", "매출성장률"],
    ),
    TermDefinition(
        term="영업이익",
        name_full="영업이익 (Operating Income)",
        category="재무제표",
        definition="매출에서 매출원가, 판관비를 뺀 본업의 이익. 이자수익·금융손익·세금 차감 전.",
        formula="매출액 - 매출원가 - 판매비와관리비",
        interpretation="기업 경쟁력의 핵심 지표. "
                       "영업이익률(영업이익 ÷ 매출액)로 비교하는 게 일반적.",
        related=["영업이익률", "매출액", "당기순이익"],
    ),
    TermDefinition(
        term="당기순이익",
        name_full="당기순이익 (Net Income)",
        category="재무제표",
        definition="모든 비용·세금을 뺀 최종 이익. 주주에게 귀속되는 진짜 이익.",
        formula="영업이익 + 영업외손익 - 법인세",
        interpretation="배당과 주주환원의 재원. "
                       "EPS 계산의 기초. 일회성 이익/손실에 크게 좌우될 수 있어 추세를 보는 게 중요.",
        related=["영업이익", "EPS", "ROE"],
    ),
    TermDefinition(
        term="유동자산",
        name_full="유동자산 (Current Assets)",
        category="재무제표",
        definition="1년 이내에 현금화 가능한 자산. 현금, 매출채권, 재고자산, 단기금융상품 등이 포함됩니다.",
        interpretation="유동부채 대비 충분한지(유동비율)가 단기 안정성의 핵심. "
                       "현금이 많으면 안정적이지만 너무 많으면 자본 효율성 측면에서 비판받을 수도 있음.",
        related=["유동부채", "유동비율", "현금및현금성자산"],
    ),
    TermDefinition(
        term="유동부채",
        name_full="유동부채 (Current Liabilities)",
        category="재무제표",
        definition="1년 이내에 갚아야 할 부채. 매입채무, 단기차입금, 미지급금 등.",
        interpretation="유동자산으로 감당 가능한지가 단기 지급 능력 판단의 기초.",
        related=["유동자산", "유동비율", "부채총계"],
    ),
    TermDefinition(
        term="매출원가",
        name_full="매출원가 (Cost of Goods Sold, COGS)",
        category="재무제표",
        definition="제품·서비스를 만드는 데 직접 들어간 비용. 원재료, 직접노무비, 제조경비 등.",
        interpretation="매출액 - 매출원가 = 매출총이익. "
                       "매출원가율 변화는 원가 구조 변화 또는 가격 협상력 신호.",
        related=["매출액", "매출총이익"],
    ),
    TermDefinition(
        term="현금및현금성자산",
        name_full="현금및현금성자산 (Cash and Cash Equivalents)",
        category="재무제표",
        definition="현금과 즉시 현금으로 전환 가능한 자산(보통 3개월 이내). 가장 유동성 높은 자산.",
        interpretation="현금이 많으면 위기 대응력·M&A 여력 우수. "
                       "다만 너무 많으면 자본 비효율 비판도 (ex: 애플 현금 보유량 논쟁).",
        related=["유동자산", "유동비율"],
    ),
    
    # ========================================
    # 6. 시장 지표 (8개)
    # ========================================
    TermDefinition(
        term="시가총액",
        name_full="시가총액 (Market Capitalization)",
        category="시장",
        definition="주가 × 발행주식수. 주식시장에서 평가되는 기업의 총 가치.",
        interpretation="시가총액은 회사 규모를 가늠하는 표준 척도. "
                       "대형주(10조 이상), 중형주(1~10조), 소형주(1조 미만) 분류에 사용.",
        related=["주가", "유통주식수"],
    ),
    TermDefinition(
        term="거래량",
        name_full="거래량 (Trading Volume)",
        category="시장",
        definition="특정 기간 동안 거래된 주식 수. 시장 관심도와 유동성의 척도.",
        interpretation="거래량 급증은 중요한 변곡점 신호. "
                       "가격 상승 + 거래량 증가 = 강세, 가격 상승 + 거래량 감소 = 신뢰도 약함.",
    ),
    TermDefinition(
        term="배당수익률",
        name_full="배당수익률 (Dividend Yield)",
        category="시장",
        definition="주가 대비 1주당 연간 배당금의 비율. 배당주 매력도의 핵심 지표.",
        formula="주당 배당금 ÷ 주가 × 100",
        interpretation="3% 이상이면 매력적인 배당주. 단, 주가 폭락으로 배당수익률이 높아진 경우는 주의 (배당함정).",
        related=["배당성향", "주당배당금"],
    ),
    TermDefinition(
        term="배당성향",
        name_full="배당성향 (Dividend Payout Ratio)",
        category="시장",
        definition="당기순이익 중 배당으로 지급된 비율. 회사가 이익을 주주에게 얼마나 환원하는지 보여줍니다.",
        formula="배당금 총액 ÷ 당기순이익 × 100",
        interpretation="20~50%가 일반적. 너무 낮으면 인색, 너무 높으면 재투자 부족 우려. "
                       "성장기업은 낮고, 성숙기업은 높은 편.",
        related=["배당수익률", "당기순이익"],
    ),
    TermDefinition(
        term="주가",
        name_full="주가 (Stock Price)",
        category="시장",
        definition="주식 1주의 시장 가격. 수요와 공급에 의해 실시간 결정됩니다.",
        interpretation="주가 자체보다 PER, PBR 같은 상대 비율이 의미 있음. "
                       "1만원 주식이 10만원 주식보다 싼 게 아님.",
    ),
    TermDefinition(
        term="주당배당금",
        name_full="주당배당금 (DPS, Dividend Per Share)",
        category="시장",
        definition="주식 1주당 받는 연간 배당금.",
        formula="배당금 총액 ÷ 발행주식수",
        interpretation="장기 DPS 성장은 배당주의 핵심 지표 (배당귀족주는 25년 이상 DPS 증가 기업).",
        related=["배당수익률", "배당성향"],
    ),
    TermDefinition(
        term="유통주식수",
        name_full="유통주식수 (Outstanding Shares)",
        category="시장",
        definition="시장에서 거래되는 발행주식 수.",
        interpretation="자사주 매입·소각으로 유통주식수가 줄면 EPS·주가가 상승하는 효과.",
        related=["시가총액", "EPS"],
    ),
    TermDefinition(
        term="주가수익비율",
        name_full="주가수익비율 (Price-to-Earnings Ratio)",
        category="시장",
        definition="PER의 한국어 명칭. 주가가 EPS의 몇 배인지 나타내는 가장 기본적 지표.",
        formula="주가 ÷ EPS",
        related=["PER"],
    ),
    
    # ========================================
    # 7. 공시/제도 (6개)
    # ========================================
    TermDefinition(
        term="DART",
        name_full="DART (Data Analysis, Retrieval and Transfer System, 전자공시시스템)",
        category="공시/제도",
        definition="금융감독원이 운영하는 상장기업 공시 통합 시스템. 사업보고서·반기보고서·주요사항보고서 등이 모두 게시됩니다.",
        interpretation="투자자라면 종목 매수 전 반드시 확인해야 할 1차 정보원. dart.fss.or.kr",
        related=["사업보고서", "XBRL"],
    ),
    TermDefinition(
        term="XBRL",
        name_full="XBRL (eXtensible Business Reporting Language)",
        category="공시/제도",
        definition="재무 데이터를 표준화된 태그로 표현하는 XML 기반 언어. "
                   "각 숫자에 '회계연도', '계정명', '단위' 등의 메타데이터가 부착되어 기계가 정확히 해석할 수 있습니다.",
        interpretation="DART 공시는 대부분 XBRL 태그를 포함. "
                       "AI 시스템이 표를 이미지로 인식하지 않고 구조화된 데이터로 직접 추출 가능 (본 시스템의 핵심 기술).",
        related=["DART", "사업보고서"],
    ),
    TermDefinition(
        term="사업보고서",
        name_full="사업보고서 (Annual Report)",
        category="공시/제도",
        definition="연간 결산 후 90일 이내(통상 3월 말) 제출하는 가장 포괄적인 공시 문서. "
                   "회사 개요, 사업 내용, 재무제표, 주요계약, 임원 정보 등이 모두 담깁니다.",
        interpretation="투자 판단을 위한 가장 중요한 1차 자료. "
                       "보통 100-300페이지에 달함.",
        related=["반기보고서", "분기보고서", "DART"],
    ),
    TermDefinition(
        term="반기보고서",
        name_full="반기보고서 (Semi-Annual Report)",
        category="공시/제도",
        definition="상반기(1~6월) 종료 후 45일 이내(8월 14일) 제출하는 공시 문서.",
        interpretation="사업보고서보다 간소하지만 중간 점검에 필수. 외부감사인의 검토 의견 포함.",
        related=["사업보고서", "분기보고서"],
    ),
    TermDefinition(
        term="분기보고서",
        name_full="분기보고서 (Quarterly Report)",
        category="공시/제도",
        definition="1·3분기 종료 후 45일 이내(5월 15일, 11월 14일) 제출하는 공시 문서.",
        interpretation="가장 최신 실적을 알 수 있는 공시. 다만 외부감사인의 감사를 받지 않아 정확도는 사업보고서·반기보고서보다 낮을 수 있음.",
        related=["사업보고서", "반기보고서"],
    ),
    TermDefinition(
        term="연결재무제표",
        name_full="연결재무제표 (Consolidated Financial Statements)",
        category="공시/제도",
        definition="모회사와 종속회사를 하나의 경제적 실체로 보고 합산해 작성한 재무제표.",
        interpretation="대기업·지주사 분석은 연결 기준이 필수. "
                       "별도재무제표(모회사만)와 함께 보면 그룹사 구조 파악 가능.",
        related=["사업보고서"],
    ),
    
    # ========================================
    # 8. 회계 개념 (5개)
    # ========================================
    TermDefinition(
        term="발생주의",
        name_full="발생주의 (Accrual Basis Accounting)",
        category="회계",
        definition="현금이 오갈 때가 아니라 거래가 '발생'한 시점에 수익·비용을 인식하는 회계 원칙입니다.",
        interpretation="현금주의보다 정확한 경제적 실체 반영. 매출채권·미지급금 등이 발생주의의 결과.",
        related=["영업현금흐름"],
    ),
    TermDefinition(
        term="감가상각",
        name_full="감가상각 (Depreciation)",
        category="회계",
        definition="유형자산(건물·기계 등)의 가치 감소를 사용 기간에 걸쳐 비용으로 배분하는 회계 처리.",
        interpretation="현금 유출이 없는 비용. 그래서 EBITDA(감가상각비 차감 전 이익)로 영업현금흐름을 추정.",
        related=["EBITDA", "영업현금흐름"],
    ),
    TermDefinition(
        term="자본화",
        name_full="자본화 (Capitalization)",
        category="회계",
        definition="비용을 즉시 인식하지 않고 자산으로 처리한 후 여러 기간에 걸쳐 상각하는 회계 처리.",
        interpretation="R&D 자본화는 기업이 미래 수익이 기대된다고 판단할 때 적용. "
                       "자본화 정책에 따라 단기 이익이 크게 달라짐.",
        related=["감가상각"],
    ),
    TermDefinition(
        term="영업현금흐름",
        name_full="영업현금흐름 (Operating Cash Flow, OCF)",
        category="회계",
        definition="본업 활동으로 실제 들어오고 나간 현금의 차액. 발생주의 회계의 한계를 보완하는 지표.",
        interpretation="당기순이익 > 영업현금흐름이 지속되면 회계상 이익만 있고 실제 현금은 안 들어오는 상황 (분식회계 의심 신호).",
        related=["당기순이익", "잉여현금흐름"],
    ),
    TermDefinition(
        term="잉여현금흐름",
        name_full="잉여현금흐름 (Free Cash Flow, FCF)",
        category="회계",
        definition="영업현금흐름에서 자본적 지출(CAPEX)을 차감한 현금. 진짜로 주주에게 돌려줄 수 있는 돈.",
        formula="영업현금흐름 - 자본적 지출",
        interpretation="배당·자사주 매입의 진정한 재원. 워런 버핏이 강조하는 'Owner Earnings' 개념과 유사.",
        related=["영업현금흐름", "배당성향"],
    ),
]


# ==========================================
# 인덱스 구축
# ==========================================

def _build_index() -> dict[str, TermDefinition]:
    """용어명 → 정의 매핑"""
    idx = {}
    for term in TERMS_DB:
        idx[term.term.upper()] = term  # 정확한 명칭
        idx[term.term] = term  # 원본 그대로
        # name_full에서 영문/한글 분리해 추가 키로
        # "PER (Price-to-Earnings Ratio, 주가수익비율)" → "PER", "Price-to-Earnings Ratio", "주가수익비율"
        if "(" in term.name_full and ")" in term.name_full:
            full = term.name_full
            inside = full[full.index("(")+1:full.rindex(")")]
            for token in inside.split(","):
                token = token.strip()
                if token and token != term.term:
                    idx[token] = term
                    idx[token.upper()] = term
    return idx


_TERM_INDEX = _build_index()


# ==========================================
# 공개 API
# ==========================================

def lookup_term(query: str) -> Optional[dict]:
    """
    정확한 용어 매칭. 대소문자 구분 없음
    
    Args:
        query: 조회할 용어 (예: "PER", "ROE", "유동비율")
    Returns:
        용어 정의 dict 또는 None
    """
    if not query:
        return None
    
    query_clean = query.strip()
    
    for key in [query_clean, query_clean.upper(), query_clean.lower()]:
        if key in _TERM_INDEX:
            term = _TERM_INDEX[key]
            return _term_to_dict(term)
    
    return None


def search_terms(keyword: str, limit: int = 5) -> list[dict]:
    """
    부분 키워드 검색. term/name_full/definition에 포함된 모든 용어 반환
    
    Args:
        keyword: 검색 키워드 (예: "이익률", "재무")
    Returns:
        매칭된 용어 정의 리스트
    """
    if not keyword:
        return []
    
    keyword_lower = keyword.strip().lower()
    matches = []
    seen = set()
    
    for term in TERMS_DB:
        if term.term in seen:
            continue
        priority = None
        if keyword_lower in term.term.lower():
            priority = 0
        elif keyword_lower in term.name_full.lower():
            priority = 1
        elif keyword_lower in term.definition.lower():
            priority = 2
        elif keyword_lower in term.category.lower():
            priority = 3
        
        if priority is not None:
            matches.append((priority, term))
            seen.add(term.term)
    
    matches.sort(key=lambda x: x[0])
    return [_term_to_dict(t) for _, t in matches[:limit]]


def get_terms_by_category(category: str) -> list[dict]:
    """카테고리별 용어 리스트"""
    return [
        _term_to_dict(t) for t in TERMS_DB
        if t.category == category
    ]


def get_all_categories() -> list[str]:
    """모든 카테고리 목록"""
    seen = []
    for t in TERMS_DB:
        if t.category not in seen:
            seen.append(t.category)
    return seen


def get_total_count() -> int:
    """전체 용어 수"""
    return len(TERMS_DB)


def _term_to_dict(term: TermDefinition) -> dict:
    """dataclass → dict (None 필드 포함)"""
    d = asdict(term)
    if d.get("related") is None:
        d["related"] = []
    return d


def format_term_answer(term_dict: dict) -> str:
    """
    용어 정의를 사용자 친화적 답변 형식으로 변환
    Q&A 응답에 사용
    """
    if not term_dict:
        return ""
    
    lines = []
    lines.append(f"📚 **{term_dict['name_full']}**")
    lines.append(f"")
    lines.append(f"**정의**")
    lines.append(term_dict['definition'])
    
    if term_dict.get('formula'):
        lines.append(f"")
        lines.append(f"**계산식**")
        lines.append(f"`{term_dict['formula']}`")
    
    if term_dict.get('interpretation'):
        lines.append(f"")
        lines.append(f"💡 **해석 가이드**")
        lines.append(term_dict['interpretation'])
    
    if term_dict.get('example'):
        lines.append(f"")
        lines.append(f"📊 **예시**")
        lines.append(term_dict['example'])
    
    if term_dict.get('related'):
        lines.append(f"")
        lines.append(f"🔗 관련 용어: {', '.join(term_dict['related'])}")
    
    lines.append(f"")
    lines.append(f"_카테고리: {term_dict['category']}_")
    
    return "\n".join(lines)


# ==========================================
# 테스트
# ==========================================

if __name__ == "__main__":
    print(f"총 용어 수: {get_total_count()}")
    print(f"카테고리: {get_all_categories()}")
    
    # 정확 매칭
    for q in ["PER", "per", "ROE", "유동비율", "DART", "주가수익비율"]:
        result = lookup_term(q)
        if result:
            print(f"\n'{q}' → ✅ {result['name_full']}")
        else:
            print(f"\n'{q}' → ❌ 미발견")
    
    # 부분 검색
    print("\n=== '이익률' 검색 ===")
    for r in search_terms("이익률"):
        print(f"  - {r['term']}: {r['name_full']}")
    
    print("\n=== '재무' 검색 ===")
    for r in search_terms("재무"):
        print(f"  - {r['term']}: {r['name_full']}")
    
    # 답변 포맷
    print("\n" + "=" * 60)
    print("PER 답변 포맷 예시")
    print("=" * 60)
    print(format_term_answer(lookup_term("PER")))
