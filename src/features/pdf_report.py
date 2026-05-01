"""
pdf_report.py — 기업 분석 PDF 보고서 자동 생성

구조:
  표지 → 1. 핵심 지표 → 2. 재무 비율 + 해석 → 3. 시계열 차트
       → 4. 업종 비교 → 5. 최근 뉴스 → 6. 출처 + 면책
"""

from __future__ import annotations
import io
import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ==========================================
# 한글 폰트 설정
# ==========================================

# Colab 기본 경로
NANUM_PATHS = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/Library/Fonts/AppleGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
]

NANUM_BOLD_PATHS = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
]


def _find_font(paths: list[str]) -> Optional[str]:
    """가능한 폰트 경로 중 존재하는 것 반환"""
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def _register_korean_font() -> tuple[str, str]:
    """
    reportlab에 한글 폰트 등록
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    
    regular_path = _find_font(NANUM_PATHS)
    bold_path = _find_font(NANUM_BOLD_PATHS) or regular_path
    
    if not regular_path:
        raise RuntimeError(
            "한글 폰트가 없습니다. Colab에서:\n"
            "  !apt-get install -y fonts-nanum\n"
            "  !fc-cache -fv"
        )
    
    pdfmetrics.registerFont(TTFont("NanumGothic", regular_path))
    pdfmetrics.registerFont(TTFont("NanumGothicBold", bold_path))
    return "NanumGothic", "NanumGothicBold"


# ==========================================
# 차트 생성
# ==========================================

def _make_timeseries_chart(series: list[dict], title: str, ylabel: str = "조원") -> bytes:
    """
    시계열 데이터를 matplotlib 막대 차트로 그리고 PNG bytes 반환
    """
    import matplotlib
    matplotlib.use("Agg")  # GUI 없이
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    
    # 한글 폰트
    regular_path = _find_font(NANUM_PATHS)
    if regular_path:
        font_manager.fontManager.addfont(regular_path)
        plt.rcParams["font.family"] = "NanumGothic"
    plt.rcParams["axes.unicode_minus"] = False
    
    if not series:
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.text(0.5, 0.5, "데이터 없음", ha="center", va="center", fontsize=14, color="gray")
        ax.axis("off")
    else:
        labels = [s.get("label", "") for s in series]
        values = []
        for s in series:
            v = s.get("value_won", 0) or 0
            values.append(v / 1_000_000_000_000)
        
        fig, ax = plt.subplots(figsize=(7, 3.2))
        bars = ax.bar(labels, values, color="#3b82f6", alpha=0.85)
        
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                    f"{val:.1f}", ha="center", va="bottom", fontsize=9)
        
        ax.set_title(title, fontsize=12, pad=10)
        ax.set_ylabel(ylabel)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", linestyle="--", alpha=0.3)
        plt.xticks(rotation=20, ha="right", fontsize=9)
        plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ==========================================
# 메인
# ==========================================

def generate_company_report(
    corp_name: str,
    year: int,
    facts_db: str,
    api_base: str = "http://localhost:8000",
    include_news: bool = True,
    include_sector: bool = True,
) -> bytes:
    """
    기업 분석 PDF 보고서 생성.
    
    Args:
        corp_name: 기업명
        year: 회계연도
        facts_db: facts.db 경로
        api_base: FastAPI 서버 (시계열, 업종비교 등 API 호출용)
        include_news: 최근 뉴스 섹션 포함 여부
        include_sector: 업종 비교 섹션 포함 여부
    """
    # reportlab import (lazy)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, Image as RLImage, KeepTogether,
    )
    
    REGULAR, BOLD = _register_korean_font()
    
    COLOR_PRIMARY = HexColor("#1e40af")
    COLOR_ACCENT = HexColor("#3b82f6")
    COLOR_SUCCESS = HexColor("#16a34a")
    COLOR_WARNING = HexColor("#dc2626")
    COLOR_GRAY = HexColor("#6b7280")
    COLOR_LIGHT = HexColor("#f3f4f6")
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        name="TitleK", parent=styles["Title"],
        fontName=BOLD, fontSize=24, textColor=COLOR_PRIMARY,
        alignment=TA_CENTER, spaceAfter=20,
    )
    h1_style = ParagraphStyle(
        name="H1K", parent=styles["Heading1"],
        fontName=BOLD, fontSize=16, textColor=COLOR_PRIMARY,
        spaceBefore=15, spaceAfter=10,
        borderWidth=0, borderPadding=0,
    )
    h2_style = ParagraphStyle(
        name="H2K", parent=styles["Heading2"],
        fontName=BOLD, fontSize=13, textColor=COLOR_ACCENT,
        spaceBefore=10, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        name="BodyK", parent=styles["Normal"],
        fontName=REGULAR, fontSize=10, leading=14,
    )
    small_style = ParagraphStyle(
        name="SmallK", parent=styles["Normal"],
        fontName=REGULAR, fontSize=8, leading=11, textColor=COLOR_GRAY,
    )
    caption_style = ParagraphStyle(
        name="CaptionK", parent=styles["Normal"],
        fontName=REGULAR, fontSize=9, leading=12,
        alignment=TA_CENTER, textColor=COLOR_GRAY,
    )
    
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title=f"{corp_name} 기업 분석 보고서",
        author="DART AI Q&A 시스템",
    )
    
    story = []
    
    # ==========================================
    # 표지
    # ==========================================
    story.append(Spacer(1, 4*cm))
    story.append(Paragraph("기업 분석 보고서", title_style))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        f'<font size="20" color="#3b82f6"><b>{corp_name}</b></font>',
        ParagraphStyle(name="cv", parent=title_style, fontName=BOLD)
    ))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(f"회계연도 {year}년", caption_style))
    story.append(Spacer(1, 5*cm))
    
    story.append(Paragraph(
        f"<b>생성 일시</b>: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M')}",
        body_style
    ))
    story.append(Paragraph(
        "<b>데이터 출처</b>: DART 공시 시스템 XBRL · 네이버 뉴스",
        body_style
    ))
    story.append(Paragraph(
        "<b>생성 도구</b>: AI 주식 분석 비서 (학부 졸업 작품)",
        body_style
    ))
    story.append(PageBreak())
    
    # ==========================================
    # 1. 핵심 지표 (KPI)
    # ==========================================
    story.append(Paragraph(f"1. 핵심 지표 ({year}년)", h1_style))
    
    profile = _safe_api_get(f"{api_base}/profile/{corp_name}", {"year": year})
    yoy_resp = _safe_api_get(f"{api_base}/compare/years/{corp_name}", {"year": year})
    yoy_map = {}
    if yoy_resp and yoy_resp.get("comparisons"):
        for c in yoy_resp["comparisons"]:
            yoy_map[c.get("account", "")] = {
                "change_pct": c.get("change_pct"),
                "change_display": c.get("change_display", ""),
            }
    
    if profile and profile.get("metrics"):
        metrics = profile["metrics"]
        
        kpi_keys = ["매출액", "영업이익", "당기순이익", "자산총계",
                    "부채총계", "자본총계", "유동자산", "현금및현금성자산"]
        
        rows = [["지표", "값", "전년 대비"]]
        for key in kpi_keys:
            m = metrics.get(key)
            if m:
                value = m.get("display", "N/A")
                yoy_data = yoy_map.get(key, {})
                yoy_pct = yoy_data.get("change_pct")
                if yoy_pct is not None:
                    arrow = "▲" if yoy_pct > 0 else ("▼" if yoy_pct < 0 else "—")
                    yoy_str = f"{arrow} {abs(yoy_pct):.1f}%"
                else:
                    yoy_str = "—"
                rows.append([key, value, yoy_str])
            else:
                rows.append([key, "N/A", "—"])
        
        kpi_table = Table(rows, colWidths=[5*cm, 6*cm, 5*cm])
        kpi_table.setStyle(TableStyle([
            # 헤더
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
            ("FONTNAME", (0, 0), (-1, 0), BOLD),
            ("FONTSIZE", (0, 0), (-1, 0), 11),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            # 본문
            ("FONTNAME", (0, 1), (-1, -1), REGULAR),
            ("FONTSIZE", (0, 1), (-1, -1), 10),
            ("ALIGN", (0, 1), (0, -1), "LEFT"),    # 지표명
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),   # 값
            ("ALIGN", (2, 1), (2, -1), "CENTER"),  # 증감
            ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), COLOR_LIGHT]),
            ("LINEBELOW", (0, 0), (-1, 0), 1, COLOR_PRIMARY),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
            ("TOPPADDING", (0, 1), (-1, -1), 6),
        ]))
        story.append(kpi_table)
    else:
        story.append(Paragraph("핵심 지표 데이터를 불러오지 못했습니다.", body_style))
    
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        "※ 모든 수치는 DART XBRL 공시에서 직접 추출. LLM 호출 없이 정형 데이터로 조회.",
        small_style
    ))
    
    # ==========================================
    # 2. 재무 비율 + 자동 해석
    # ==========================================
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("2. 재무 비율 + 자동 해석", h1_style))
    
    interp = _safe_api_get(f"{api_base}/interpret-ratios/{corp_name}", {"year": year})
    if interp and interp.get("ratios"):
        interpretations = interp.get("interpretations", [])
        
        if interpretations:
            ratio_rows = [["비율", "값", "등급", "해석"]]
            for item in interpretations:
                name = item.get("name", "")
                display = item.get("display", "")
                icon = item.get("icon", "")
                label = item.get("label", "")
                explanation = item.get("explanation", "")
                
                grade_str = f"{icon} {label}" if icon and label else (icon or label or "—")
                
                explanation_para = Paragraph(explanation, body_style)
                
                ratio_rows.append([name, display, grade_str, explanation_para])
            
            ratio_table = Table(ratio_rows, colWidths=[3*cm, 2.5*cm, 3.5*cm, 7*cm])
            ratio_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), COLOR_ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
                ("FONTNAME", (0, 0), (-1, 0), BOLD),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 1), (-1, -1), REGULAR),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("ALIGN", (0, 1), (0, -1), "LEFT"),
                ("ALIGN", (2, 1), (2, -1), "CENTER"),
                ("ALIGN", (3, 1), (3, -1), "LEFT"),
                ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), COLOR_LIGHT]),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(ratio_table)
            
            # 등급 통계 요약
            grades = [item.get("grade", "") for item in interpretations]
            from collections import Counter
            grade_count = Counter(grades)
            
            grade_summary_parts = []
            grade_emoji = {
                "excellent": "✅ 우수",
                "good": "👍 양호",
                "average": "ℹ️ 보통",
                "warning": "⚠️ 주의",
                "danger": "❌ 위험",
            }
            for g, n in grade_count.most_common():
                emoji = grade_emoji.get(g, g)
                grade_summary_parts.append(f"{emoji}: {n}개")
            
            if grade_summary_parts:
                story.append(Spacer(1, 0.3*cm))
                story.append(Paragraph(
                    f"<b>등급 분포</b>: {' · '.join(grade_summary_parts)}",
                    body_style
                ))
        else:
            story.append(Paragraph("재무 비율 해석 데이터가 없습니다.", body_style))
    else:
        story.append(Paragraph("재무 비율 데이터를 불러오지 못했습니다.", body_style))
    
    story.append(PageBreak())
    
    # ==========================================
    # 3. 시계열 추이
    # ==========================================
    story.append(Paragraph("3. 매출 / 영업이익 추이", h1_style))
    
    for stmt, account, title in [
        ("포괄손익계산서", "매출액", "매출 추이"),
        ("포괄손익계산서", "영업이익", "영업이익 추이"),
    ]:
        ts = _safe_api_get(
            f"{api_base}/timeseries/{corp_name}",
            {"statement": stmt, "account": account},
        )
        if ts and ts.get("series"):
            try:
                chart_png = _make_timeseries_chart(
                    ts["series"], title=title, ylabel="조원"
                )
                story.append(RLImage(io.BytesIO(chart_png), width=15*cm, height=6.5*cm))
                story.append(Spacer(1, 0.3*cm))
            except Exception as e:
                logger.warning(f"차트 렌더 실패: {e}")
                story.append(Paragraph(f"{title}: 차트 생성 실패", small_style))
        else:
            story.append(Paragraph(f"{title}: 데이터 없음", small_style))
    
    # ==========================================
    # 4. 업종 비교
    # ==========================================
    if include_sector:
        story.append(PageBreak())
        story.append(Paragraph("4. 업종 비교", h1_style))
        
        # 회사가 속한 업종 추정
        sector_map = {
            "삼성전자": "반도체", "SK하이닉스": "반도체",
            "현대차": "자동차", "기아": "자동차",
            "LG에너지솔루션": "배터리", "POSCO홀딩스": "철강",
            "LG화학": "화학", "삼성바이오로직스": "바이오",
            "셀트리온": "바이오", "NAVER": "IT",
        }
        sector = sector_map.get(corp_name)
        
        if sector:
            cmp_data = _safe_api_get(
                f"{api_base}/sector-compare/{sector}",
                {"year": year},
            )
            if cmp_data and cmp_data.get("rankings"):
                rankings_list = cmp_data["rankings"]
                companies_n = cmp_data.get("companies", [])
                
                story.append(Paragraph(
                    f"<b>업종</b>: {sector} | <b>비교 대상</b>: {len(rankings_list)}개 기업",
                    body_style
                ))
                story.append(Spacer(1, 0.3*cm))
                
                # 각 기업의 비율 비교 표
                cmp_rows = [["기업", "ROE", "ROA", "영업이익률", "순이익률"]]
                
                for c in rankings_list:
                    name = c.get("corp_name", "")
                    ratios_c = c.get("ratios", {})
                    
                    def _ratio_display(key):
                        r = ratios_c.get(key)
                        if isinstance(r, dict):
                            return r.get("display", "—")
                        elif isinstance(r, (int, float)):
                            return f"{r*100:.1f}%" if abs(r) < 5 else f"{r:.1f}%"
                        return "—"
                    
                    if name == corp_name:
                        name_para = Paragraph(
                            f'<font name="{REGULAR}"><b>{name} (본 기업)</b></font>',
                            body_style
                        )
                    else:
                        name_para = Paragraph(
                            f'<font name="{REGULAR}">{name}</font>',
                            body_style
                        )
                    
                    cmp_rows.append([
                        name_para,
                        _ratio_display("ROE"),
                        _ratio_display("ROA"),
                        _ratio_display("영업이익률"),
                        _ratio_display("순이익률"),
                    ])
                
                cmp_table = Table(cmp_rows, colWidths=[5*cm, 2.7*cm, 2.7*cm, 3*cm, 2.7*cm])
                cmp_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
                    ("FONTNAME", (0, 0), (-1, 0), BOLD),
                    ("FONTNAME", (0, 1), (-1, -1), REGULAR),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), COLOR_LIGHT]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                ]))
                story.append(cmp_table)
                
                # 본 기업의 부문별 순위
                self_data = next(
                    (r for r in rankings_list if r.get("corp_name") == corp_name),
                    None
                )
                if self_data and self_data.get("rank"):
                    story.append(Spacer(1, 0.4*cm))
                    story.append(Paragraph(
                        f"<b>{corp_name}의 부문별 순위</b>",
                        h2_style
                    ))
                    rank_data = self_data["rank"]
                    rk_rows = [["부문", "순위"]]
                    for category, rank_str in rank_data.items():
                        rk_rows.append([category, rank_str])
                    
                    if len(rk_rows) > 1:
                        rk_table = Table(rk_rows, colWidths=[5*cm, 5*cm])
                        rk_table.setStyle(TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), COLOR_LIGHT),
                            ("FONTNAME", (0, 0), (-1, 0), BOLD),
                            ("FONTNAME", (0, 1), (-1, -1), REGULAR),
                            ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                            ("ALIGN", (0, 0), (0, -1), "LEFT"),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ]))
                        story.append(rk_table)
            else:
                story.append(Paragraph("업종 비교 데이터를 불러오지 못했습니다.", body_style))
        else:
            story.append(Paragraph(f"{corp_name}의 업종 정보가 없습니다.", body_style))
    
    # ==========================================
    # 5. 최근 뉴스
    # ==========================================
    if include_news:
        story.append(PageBreak())
        story.append(Paragraph("5. 최근 주요 뉴스", h1_style))
        
        news_data = _safe_api_get(f"{api_base}/news/{corp_name}", {"n": 5, "sort": "date"})
        if news_data and news_data.get("items"):
            news_items = news_data["items"]
            for i, n in enumerate(news_items[:5], 1):
                title_n = n.get("title", "")
                summary_n = n.get("summary", "")[:200]
                date = n.get("pub_date_relative", "")
                source = n.get("source", "")
                url = n.get("url", "")
                
                # 뉴스 카드
                story.append(Paragraph(
                    f'<b>{i}. {title_n}</b>',
                    ParagraphStyle(name="news_t", parent=body_style, fontName=BOLD,
                                   textColor=COLOR_PRIMARY, fontSize=10)
                ))
                story.append(Paragraph(
                    f'<font color="#6b7280">📅 {date} · 📰 {source}</font>',
                    small_style
                ))
                if summary_n:
                    story.append(Paragraph(summary_n, body_style))
                if url:
                    story.append(Paragraph(
                        f'<font color="#3b82f6"><a href="{url}">{url[:80]}...</a></font>',
                        small_style
                    ))
                story.append(Spacer(1, 0.4*cm))
        else:
            story.append(Paragraph("최근 뉴스를 불러오지 못했습니다.", body_style))
    
    # ==========================================
    # 6. 출처 + 면책
    # ==========================================
    story.append(PageBreak())
    story.append(Paragraph("6. 데이터 출처 및 면책", h1_style))
    
    story.append(Paragraph(
        "<b>공시 데이터</b>: 금융감독원 DART 시스템의 XBRL 본문 (2023.3분기 ~ 2025.사업보고서)",
        body_style
    ))
    story.append(Paragraph(
        "<b>뉴스</b>: 네이버 뉴스 검색 API",
        body_style
    ))
    story.append(Paragraph(
        "<b>분석 도구</b>: AI 주식 분석 비서 (XBRL 팩트 DB + RAG + HyperCLOVA X)",
        body_style
    ))
    story.append(Spacer(1, 0.4*cm))
    
    story.append(Paragraph("<b>면책 사항</b>", h2_style))
    disclaimer = (
        "본 보고서는 학부 졸업작품으로 개발된 AI 기반 분석 도구가 자동 생성한 것입니다. "
        "DART 공시 자료를 기반으로 하지만, 통합 과정에서 데이터 누락·오류 가능성이 있습니다. "
        "본 보고서는 정보 제공 목적이며, <b>투자 자문 또는 투자 권유가 아닙니다</b>. "
        "실제 투자 결정은 반드시 공식 공시 자료를 직접 확인하고 전문가의 자문을 받으시기 바랍니다."
    )
    story.append(Paragraph(disclaimer, body_style))
    
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        f"보고서 생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        small_style
    ))
    
    # 빌드
    doc.build(story)
    buf.seek(0)
    return buf.read()


# ==========================================
# 헬퍼
# ==========================================

def _safe_api_get(url: str, params: dict = None) -> Optional[dict]:
    """API 호출. 실패 시 None."""
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning(f"API 호출 실패 {url}: {e}")
    return None


# ==========================================
# 테스트
# ==========================================

if __name__ == "__main__":
    """직접 실행: 샘플 PDF 생성"""
    import sys
    
    corp = sys.argv[1] if len(sys.argv) > 1 else "삼성전자"
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
    out = sys.argv[3] if len(sys.argv) > 3 else f"/tmp/{corp}_{year}_report.pdf"
    
    print(f"PDF 생성 중: {corp} {year}년...")
    pdf_bytes = generate_company_report(
        corp_name=corp,
        year=year,
        facts_db="/content/db/facts.db",
        api_base=os.environ.get("API_URL", "http://localhost:8000"),
    )
    
    with open(out, "wb") as f:
        f.write(pdf_bytes)
    
    print(f" 생성 완료: {out} ({len(pdf_bytes)/1024:.1f} KB)")
