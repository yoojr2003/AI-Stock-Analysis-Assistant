"""
streamlit_app.py — DART 공시 분석 시스템 UI
"""

import os
import time
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="DART 공시 분석 시스템",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==========================================
# CSS
# ==========================================

st.markdown("""
<style>
    .main-header {
        padding: 0.5rem 0 1rem 0;
        border-bottom: 3px solid #1E3A5F;
        margin-bottom: 1.5rem;
    }
    .kpi-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #e8eef5 100%);
        padding: 1.2rem;
        border-radius: 8px;
        border-left: 4px solid #1E3A5F;
        height: 130px;
    }
    .kpi-label { color: #666; font-size: 0.85rem; font-weight: 500; margin-bottom: 0.4rem; }
    .kpi-value { color: #1E3A5F; font-size: 1.5rem; font-weight: 700; margin-bottom: 0.3rem; }
    .kpi-change-up { color: #d32f2f; font-size: 0.85rem; font-weight: 600; }
    .kpi-change-down { color: #1976d2; font-size: 0.85rem; font-weight: 600; }
    .kpi-change-neutral { color: #888; font-size: 0.85rem; }
    
    /* 의도 뱃지 - 5가지 색상 */
    .intent-badge {
        display: inline-block; padding: 0.25rem 0.7rem; border-radius: 12px;
        font-size: 0.75rem; font-weight: 600;
    }
    .intent-fact_lookup { background: #d4edda; color: #155724; }
    .intent-narrative { background: #cce7ff; color: #004085; }
    .intent-hybrid { background: #fff3cd; color: #856404; }
    .intent-definition { background: #e1d5f0; color: #4527a0; }
    .intent-general { background: #f5f5f5; color: #424242; }
    .intent-sector_compare { background: #ffe0b2; color: #e65100; }
    
    .source-box {
        background: #f9f9f9; padding: 0.6rem 0.9rem;
        border-radius: 4px; margin: 0.3rem 0;
        font-size: 0.85rem; border-left: 3px solid #ccc;
    }
    .perf-highlight {
        background: #fff8e1; padding: 0.8rem 1rem;
        border-left: 3px solid #f57c00; border-radius: 4px;
        margin: 0.5rem 0;
    }
    
    /* 비율 해석 카드 */
    .ratio-card {
        padding: 0.9rem 1rem; border-radius: 6px; margin: 0.4rem 0;
        background: #f8f9fa;
    }
    .ratio-card.excellent { border-left: 4px solid #2e7d32; }
    .ratio-card.good { border-left: 4px solid #66bb6a; }
    .ratio-card.fair { border-left: 4px solid #fdd835; }
    .ratio-card.warning { border-left: 4px solid #fb8c00; }
    .ratio-card.danger { border-left: 4px solid #d32f2f; }
    .ratio-card.unknown { border-left: 4px solid #bdbdbd; }
    
    /* 용어 사전 박스 */
    .term-card {
        background: #f3e5f5; padding: 1rem;
        border-left: 4px solid #7b1fa2;
        border-radius: 4px; margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# API 호출 helper
# ==========================================

@st.cache_data(ttl=300)
def api_get(path: str, params: dict = None):
    try:
        r = requests.get(f"{API_URL}{path}", params=params, timeout=30)
        if r.status_code == 200:
            return r.json(), None
        return None, f"{r.status_code}: {r.text[:200]}"
    except Exception as e:
        return None, str(e)


def api_post(path: str, json_body: dict, timeout: int = 120):
    try:
        r = requests.post(f"{API_URL}{path}", json=json_body, timeout=timeout)
        if r.status_code == 200:
            return r.json(), None
        return None, f"{r.status_code}: {r.text[:200]}"
    except Exception as e:
        return None, str(e)


# ==========================================
# 헤더
# ==========================================

st.markdown('<div class="main-header">', unsafe_allow_html=True)
col1, col2 = st.columns([4, 1])
with col1:
    st.title("📊 DART 공시 분석 시스템")
    st.caption("XBRL 팩트 DB + 섹션 RAG + 용어 사전 + 업종 비교를 결합한 종합 기업 분석 AI")
with col2:
    health_data, err = api_get("/health")
    if err:
        st.error("🔴 서버 연결 실패")
        st.caption(f"API: {API_URL}")
    elif health_data and health_data.get("status") == "ok":
        st.success("🟢 서버 정상")
        st.caption(f"용어 {health_data.get('terms_count', 0)}개")
st.markdown('</div>', unsafe_allow_html=True)


# ==========================================
# 사이드바
# ==========================================

with st.sidebar:
    st.header("🏢 분석 대상 선택")
    
    companies_data, _ = api_get("/companies")
    companies = companies_data["companies"] if companies_data else [
        "삼성전자", "SK하이닉스", "현대자동차", "기아",
        "LG에너지솔루션", "LG화학", "NAVER",
        "삼성바이오로직스", "POSCO홀딩스", "셀트리온",
    ]
    
    selected_corp = st.selectbox("분석할 기업", companies, index=0)
    selected_year = st.selectbox("회계연도", [2025, 2024], index=0)
    
    st.divider()
    
    # ⭐ 용어 사전 검색 (NEW)
    st.header("📚 용어 사전")
    term_query = st.text_input(
        "금융 용어 검색",
        placeholder="예: PER, ROE, 유동비율",
        help="50개 금융/회계 용어 정의 즉시 조회",
    )
    
    if term_query:
        define_data, define_err = api_get(f"/define/{term_query}")
        if define_err and "404" not in define_err:
            st.error(f"❌ {define_err[:80]}")
        elif define_data and define_data.get("matched"):
            term = define_data["exact"]
            st.markdown(f"""
            <div class="term-card">
                <b>{term['name_full']}</b><br>
                <small style="color: #666;">{term['category']}</small><br><br>
                {term['definition']}
            </div>
            """, unsafe_allow_html=True)
            
            if term.get("formula"):
                st.code(term["formula"], language="")
            
            if term.get("interpretation"):
                with st.expander("💡 해석 가이드"):
                    st.write(term["interpretation"])
            
            if term.get("related"):
                st.caption(f"🔗 관련: {', '.join(term['related'])}")
        elif define_data and not define_data.get("matched"):
            suggestions = define_data.get("suggestions", [])
            if suggestions:
                st.info(f"비슷한 용어: {', '.join(s['term'] for s in suggestions)}")
            else:
                st.warning(f"'{term_query}' 용어를 찾을 수 없습니다")
    
    st.divider()
    
    st.markdown("""
    <div class="perf-highlight">
    <b>📊 시스템 성능</b><br>
    Fact 정확도: <b>96.2%</b> (25/26)<br>
    Baseline 대비: <b>12~25배</b><br>
    의도: 6가지 (fact/narrative/hybrid/<br>
    <b>definition/general/sector</b>)
    </div>
    """, unsafe_allow_html=True)
    
    with st.expander("ℹ️ 기술 스택"):
        st.markdown("""
        - **LLM**: HCX-003
        - **임베딩**: OpenAI text-embedding-3-small
        - **리랭커**: BGE-reranker-v2-m3
        - **팩트 DB**: SQLite (XBRL 파싱)
        - **벡터 DB**: Chroma + BM25
        - **분석 모듈**: 자동 해석/업종 비교
        - **용어 사전**: 50개 금융 용어
        """)


# ==========================================
# 탭 구조
# ==========================================

tab_dashboard, tab_compare, tab_qa, tab_system = st.tabs([
    "📊 대시보드", "🔄 비교 분석", "💬 Q&A", "ℹ️ 시스템 정보"
])


# ==========================================
# 탭 1 — 대시보드 (비율 해석 추가됨)
# ==========================================

with tab_dashboard:
    st.subheader(f"🏢 {selected_corp} 기업 프로파일 ({selected_year}년)")
    
    # PDF 다운로드 + 캡션
    title_col1, title_col2 = st.columns([4, 1])
    with title_col1:
        st.caption("XBRL 팩트 DB에서 직접 조회한 주요 지표 · LLM 호출 없음")
    with title_col2:
        # PDF 생성 버튼
        if st.button("📄 PDF 보고서", help="이 기업의 종합 분석 PDF 생성·다운로드",
                     key="dl_pdf_btn", use_container_width=True):
            with st.spinner("📑 PDF 생성 중... (10-30초)"):
                try:
                    import requests
                    pdf_url = f"{API_URL}/report/pdf/{selected_corp}"
                    r = requests.get(pdf_url, params={"year": selected_year}, timeout=60)
                    if r.status_code == 200:
                        st.session_state["last_pdf"] = {
                            "data": r.content,
                            "filename": f"{selected_corp}_{selected_year}_report.pdf",
                        }
                        st.success(f"✅ PDF 생성 완료 ({len(r.content)/1024:.1f} KB)")
                    else:
                        st.error(f"PDF 생성 실패: {r.status_code}")
                except Exception as e:
                    st.error(f"오류: {e}")
    
    # 생성된 PDF가 있으면 다운로드 버튼 표시
    if "last_pdf" in st.session_state:
        pdf_info = st.session_state["last_pdf"]
        st.download_button(
            label=f"💾 {pdf_info['filename']} 다운로드",
            data=pdf_info["data"],
            file_name=pdf_info["filename"],
            mime="application/pdf",
            use_container_width=False,
        )
    
    profile_data, err = api_get(f"/profile/{selected_corp}", {"year": selected_year})
    
    if err:
        st.error(f"프로파일 로드 실패: {err}")
    elif profile_data:
        metrics = profile_data.get("metrics", {})
        yoy = profile_data.get("yoy", {})
        
        # KPI 카드
        st.markdown("### 📈 핵심 지표")
        
        for row_labels in [["매출액", "영업이익", "자산총계", "자본총계"],
                          ["당기순이익", "부채총계", "유동자산", "현금및현금성자산"]]:
            cols = st.columns(4)
            for i, label in enumerate(row_labels):
                m = metrics.get(label)
                with cols[i]:
                    if m:
                        change_html = ""
                        if label in yoy:
                            y = yoy[label]
                            pct = y["change_pct"]
                            if pct > 0:
                                change_html = f'<span class="kpi-change-up">▲ {pct:+.1f}%</span>'
                            elif pct < 0:
                                change_html = f'<span class="kpi-change-down">▼ {pct:+.1f}%</span>'
                        st.markdown(f"""
                        <div class="kpi-card">
                            <div class="kpi-label">{label}</div>
                            <div class="kpi-value">{m['display']}</div>
                            <div>{change_html}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                        <div class="kpi-card">
                            <div class="kpi-label">{label}</div>
                            <div class="kpi-value" style="color: #999;">N/A</div>
                        </div>
                        """, unsafe_allow_html=True)
            st.markdown("")
    
    st.divider()
    
    # ==========================================
    # 📰 최근 뉴스 (네이버 뉴스 API)
    # ==========================================
    with st.expander(f"📰 {selected_corp} 최근 뉴스 (실시간)", expanded=False):
        news_data, news_err = api_get(f"/news/{selected_corp}", {"n": 5, "sort": "date"})
        if news_err:
            st.warning(f"뉴스 가져오기 실패: {news_err}")
        elif news_data and news_data.get("items"):
            for item in news_data["items"]:
                title = item.get("title", "")
                summary = item.get("summary", "")[:120]
                date = item.get("pub_date_relative", "")
                source = item.get("source", "")
                url = item.get("url", "")
                
                # streamlit native 컴포넌트
                with st.container(border=True):
                    if url:
                        st.markdown(f"**[{title}]({url})**")
                    else:
                        st.markdown(f"**{title}**")
                    st.caption(f"📅 {date} · 📰 {source}")
                    if summary:
                        st.markdown(f"_{summary}..._")
        else:
            st.info("최근 뉴스가 없습니다.")
    
    # 시계열 차트
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.markdown("### 📈 매출 추이")
        ts_data, _ = api_get(f"/timeseries/{selected_corp}",
                              {"statement": "포괄손익계산서", "account": "매출액"})
        if ts_data and ts_data.get("series"):
            df = pd.DataFrame(ts_data["series"])
            df["매출 (조원)"] = df["value_won"] / 1_000_000_000_000
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=df["label"], y=df["매출 (조원)"],
                text=df["display"], textposition="outside",
                marker_color="#1E3A5F",
            ))
            fig.update_layout(yaxis_title="매출액 (조원)", height=350,
                              margin=dict(l=20, r=20, t=20, b=40), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("시계열 데이터 없음")
    
    with col_chart2:
        st.markdown("### 📉 영업이익 추이")
        ts_op, _ = api_get(f"/timeseries/{selected_corp}",
                            {"statement": "포괄손익계산서", "account": "영업이익"})
        if ts_op and ts_op.get("series"):
            df = pd.DataFrame(ts_op["series"])
            df["영업이익 (조원)"] = df["value_won"] / 1_000_000_000_000
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df["label"], y=df["영업이익 (조원)"],
                mode="lines+markers+text",
                text=df["display"], textposition="top center",
                line=dict(color="#d32f2f", width=2),
                marker=dict(size=8),
            ))
            fig.update_layout(yaxis_title="영업이익 (조원)", height=350,
                              margin=dict(l=20, r=20, t=20, b=40), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("영업이익 시계열 없음")
    
    st.divider()
    
    # 재무 비율 + 자동 해석
    st.markdown("### 💰 재무 비율 + 자동 해석")
    st.caption("XBRL 팩트로 자동 계산 + 룰 기반 해석 (LLM 호출 없음)")
    
    interp_data, err = api_get(f"/interpret-ratios/{selected_corp}",
                                {"year": selected_year})
    
    if interp_data and interp_data.get("interpretations"):
        # 종합 평가 박스 (상단)
        summary = interp_data.get("summary", "")
        if summary:
            st.markdown(f"""
            <div style="background: #e3f2fd; padding: 1rem; border-radius: 6px; 
                        border-left: 4px solid #1976d2; margin-bottom: 1rem;">
            <b>📋 종합 평가</b><br><br>
            {summary.replace(chr(10), '<br>')}
            </div>
            """, unsafe_allow_html=True)
        
        # 각 비율 (2열)
        col_r1, col_r2 = st.columns(2)
        for i, interp in enumerate(interp_data["interpretations"]):
            target_col = col_r1 if i % 2 == 0 else col_r2
            with target_col:
                grade = interp.get("grade", "unknown")
                st.markdown(f"""
                <div class="ratio-card {grade}">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 600; color: #1E3A5F;">
                            {interp['icon']} {interp['name']}
                        </span>
                        <span style="font-size: 1.2rem; font-weight: 700; color: #1E3A5F;">
                            {interp['display']}
                        </span>
                    </div>
                    <div style="font-size: 0.85rem; color: #666; margin-top: 0.3rem;">
                        <b>{interp['label']}</b> — {interp['explanation']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.warning("재무 비율 해석 데이터를 불러올 수 없습니다.")


# ==========================================
# 탭 2 — 비교 분석
# ==========================================

with tab_compare:
    st.subheader("🔄 비교 분석")
    
    comp_mode = st.radio(
        "비교 방식",
        ["📅 전년 대비", "🏢 기업 간 비교", "🏭 업종 비교"],
        horizontal=True,
    )
    
    st.divider()
    
    if comp_mode == "📅 전년 대비":
        st.markdown(f"### {selected_corp}의 {selected_year}년 vs {selected_year-1}년")
        
        yoy_data, err = api_get(f"/compare/years/{selected_corp}", {"year": selected_year})
        
        if yoy_data and yoy_data.get("comparisons"):
            rows = []
            for c in yoy_data["comparisons"]:
                cur = c["current"]["display"] if c["current"] else "N/A"
                prev = c["previous"]["display"] if c["previous"] else "N/A"
                pct = c.get("change_pct")
                pct_display = f"{pct:+.2f}%" if pct is not None else "N/A"
                icon = "📈" if pct and pct > 0 else "📉" if pct and pct < 0 else "—"
                rows.append({
                    "": icon, "재무제표": c["statement"], "항목": c["account"],
                    f"{selected_year-1}년": prev, f"{selected_year}년": cur,
                    "증감률": pct_display,
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            st.markdown("#### 전년 대비 증감률")
            viz_df = pd.DataFrame([
                {"항목": c["account"], "증감률": c.get("change_pct", 0)}
                for c in yoy_data["comparisons"] if c.get("change_pct") is not None
            ])
            if not viz_df.empty:
                colors = ["#d32f2f" if v > 0 else "#1976d2" for v in viz_df["증감률"]]
                fig = go.Figure(go.Bar(
                    x=viz_df["항목"], y=viz_df["증감률"],
                    text=[f"{v:+.1f}%" for v in viz_df["증감률"]],
                    textposition="outside", marker_color=colors,
                ))
                fig.update_layout(yaxis_title="증감률 (%)", height=400, showlegend=False)
                fig.add_hline(y=0, line_dash="dash", line_color="gray")
                st.plotly_chart(fig, use_container_width=True)
    
    elif comp_mode == "🏢 기업 간 비교":
        st.markdown(f"### {selected_year}년 기업 간 비교")
        peers = st.multiselect(
            "비교할 기업 선택 (2개 이상)",
            companies, default=["삼성전자", "SK하이닉스"],
        )
        
        if len(peers) < 2:
            st.warning("2개 이상의 기업을 선택해주세요")
        else:
            corps_param = ",".join(peers)
            peer_data, err = api_get("/compare/companies",
                                     {"corps": corps_param, "year": selected_year})
            
            if peer_data and peer_data.get("metrics"):
                rows = []
                for m in peer_data["metrics"]:
                    row = {"재무제표": m["statement"], "항목": m["account"]}
                    for corp in peers:
                        v = m["values"].get(corp)
                        row[corp] = v["display"] if v else "N/A"
                    rows.append(row)
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                
                # 시각화
                viz_rows = []
                for m in peer_data["metrics"]:
                    for corp in peers:
                        v = m["values"].get(corp)
                        if v and v["value"] is not None:
                            viz_rows.append({
                                "항목": m["account"], "기업": corp,
                                "값 (조원)": v["value"] / 1_000_000_000_000,
                                "display": v["display"],
                            })
                if viz_rows:
                    viz_df = pd.DataFrame(viz_rows)
                    fig = px.bar(viz_df, x="항목", y="값 (조원)", color="기업",
                                  barmode="group", text="display", height=450)
                    fig.update_traces(textposition="outside")
                    st.plotly_chart(fig, use_container_width=True)
                
                # 재무비율 비교 (해석 포함)
                st.markdown("#### 재무 비율 + 등급 비교")
                ratio_rows = []
                for corp in peers:
                    interp_data, _ = api_get(f"/interpret-ratios/{corp}",
                                              {"year": selected_year})
                    if interp_data and interp_data.get("interpretations"):
                        row = {"기업": corp}
                        for interp in interp_data["interpretations"]:
                            row[interp["name"]] = f"{interp['icon']} {interp['display']}"
                        ratio_rows.append(row)
                if ratio_rows:
                    st.dataframe(pd.DataFrame(ratio_rows),
                                 use_container_width=True, hide_index=True)
    
    elif comp_mode == "🏭 업종 비교":
        st.markdown(f"### 🏭 업종 비교 ({selected_year}년)")
        
        # 업종 목록 로드
        sectors_data, _ = api_get("/sectors")
        if sectors_data and sectors_data.get("sectors"):
            sector_list = list(sectors_data["sectors"].keys())
            
            selected_sector = st.selectbox(
                "업종 선택",
                sector_list,
                index=0,
                help="해당 업종 내 기업들의 재무 비율을 비교합니다",
            )
            
            sector_info = sectors_data["sectors"].get(selected_sector, {})
            st.caption(f"포함 기업: {', '.join(sector_info.get('companies', []))}")
            
            sector_data, err = api_get(f"/sector-compare/{selected_sector}",
                                        {"year": selected_year})
            
            if sector_data and sector_data.get("rankings"):
                # 단일 기업 업종 안내
                if sector_data.get("note"):
                    st.info(sector_data["note"])
                
                # 부문별 우수 기업 (최상단)
                winners = sector_data.get("winner", {})
                if winners and any(winners.values()):
                    st.markdown("#### 🏆 부문별 1위")
                    cols = st.columns(4)
                    items = [
                        ("종합 수익성", "종합_수익성", "🥇"),
                        ("ROE", "ROE", "💰"),
                        ("영업이익률", "영업이익률", "📈"),
                        ("재무 안정성", "부채비율", "🏦"),
                    ]
                    for i, (label, key, icon) in enumerate(items):
                        with cols[i]:
                            winner = winners.get(key)
                            if winner:
                                st.metric(f"{icon} {label} 1위", winner)
                            else:
                                st.metric(f"{icon} {label} 1위", "—")
                
                # 비율 비교 표
                st.markdown("#### 기업별 재무 비율")
                rows = []
                for r in sector_data["rankings"]:
                    corp = r["corp_name"]
                    ratios = r["ratios"]
                    rows.append({
                        "기업": corp,
                        "영업이익률": ratios.get("영업이익률", {}).get("display", "N/A"),
                        "순이익률": ratios.get("순이익률", {}).get("display", "N/A"),
                        "ROE": ratios.get("ROE", {}).get("display", "N/A"),
                        "ROA": ratios.get("ROA", {}).get("display", "N/A"),
                        "부채비율": ratios.get("부채비율", {}).get("display", "N/A"),
                        "유동비율": ratios.get("유동비율", {}).get("display", "N/A"),
                    })
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                
                # 시각화 (ROE/영업이익률 막대)
                if len(sector_data["rankings"]) >= 2:
                    st.markdown("#### 수익성 비교 시각화")
                    viz_rows = []
                    for r in sector_data["rankings"]:
                        for metric_name in ["영업이익률", "순이익률", "ROE", "ROA"]:
                            v = r["ratios"].get(metric_name, {}).get("value")
                            if v is not None:
                                # value가 비율(0.05) 형태인지 % 형태인지 확인
                                # display_multiplier가 100이면 비율 형태 → ×100
                                pct = v * 100 if v < 1.0 else v
                                viz_rows.append({
                                    "기업": r["corp_name"],
                                    "지표": metric_name,
                                    "값(%)": pct,
                                })
                    if viz_rows:
                        viz_df = pd.DataFrame(viz_rows)
                        fig = px.bar(viz_df, x="지표", y="값(%)", color="기업",
                                      barmode="group", height=400,
                                      text_auto=".1f")
                        fig.update_traces(textposition="outside")
                        st.plotly_chart(fig, use_container_width=True)


# ==========================================
# 탭 3 — Q&A
# ==========================================

with tab_qa:
    st.subheader("💬 공시 자료 Q&A")
    st.caption(
        "7가지 질문 타입 지원: **수치 조회** / **서술 검색** / **하이브리드** / "
        "**📚 용어 정의** / **💬 일반 답변** / **🏭 업종 비교** / **📰 뉴스 동향**"
    )
    
    # ==========================================
    # 챗봇 세션 (대화 메모리)
    # ==========================================
    if "chat_session_id" not in st.session_state:
        import uuid
        st.session_state["chat_session_id"] = f"web-{str(uuid.uuid4())[:8]}"
    
    session_id = st.session_state["chat_session_id"]
    
    # 메모리 상태 + 리셋 버튼
    mem_col1, mem_col2 = st.columns([5, 1])
    with mem_col1:
        sess_data, _ = api_get(f"/session/{session_id}")
        if sess_data and sess_data.get("exists") and sess_data.get("turn_count", 0) > 0:
            last_corp = sess_data.get("last_corp", "")
            last_year = sess_data.get("last_year", "")
            turn_count = sess_data.get("turn_count", 0)
            year_str = f"{last_year}년" if last_year else ""
            corp_str = last_corp if last_corp else ""
            ctx = " · ".join(filter(None, [corp_str, year_str]))
            st.info(
                f"🧠 **대화 메모리**: {ctx} · {turn_count}턴 진행 중  \n"
                f"후속 질문 OK: \"전년 대비는?\", \"그럼 영업이익은?\", \"이 회사 사업 부문은?\""
            )
        else:
            st.caption(
                "💡 첫 질문에 회사명·시점을 명시하면, 이후 후속 질문을 짧게 할 수 있어요."
            )
    with mem_col2:
        if st.button("🔄 메모리 초기화", help="대화 메모리 비우기", use_container_width=True):
            api_post(f"/session/{session_id}/reset", {}, timeout=5)
            if "qa_response" in st.session_state:
                del st.session_state["qa_response"]
            st.rerun()
    
    # 추천 질문
    suggested_data, _ = api_get(f"/suggested/{selected_corp}")
    if suggested_data:
        st.markdown(f"#### 💡 {selected_corp} 추천 질문")
        suggestions = suggested_data.get("suggestions", [])
        cols = st.columns(min(len(suggestions), 3))
        for i, q in enumerate(suggestions[:3]):
            with cols[i]:
                if st.button(q, key=f"sug_{i}", use_container_width=True):
                    st.session_state["question_input"] = q
    
    st.markdown("#### 🆕 신규 기능 예시")
    cols = st.columns(4)
    new_examples = [
        ("📚 PER이 뭐야?", "PER이 뭐야?"),
        ("🏭 반도체 업종 비교", "반도체 업종 비교"),
        ("💬 주식 투자 시작 방법", "주식 투자 처음 시작할 때 어떻게 해야 해?"),
        ("📰 삼성전자 최근 동향", f"{selected_corp} 최근 어떻게 돌아가?"),
    ]
    for i, (label, q) in enumerate(new_examples):
        with cols[i]:
            if st.button(label, key=f"new_{i}", use_container_width=True):
                st.session_state["question_input"] = q
    
    st.divider()
    
    # 질문 입력
    if "question_input" not in st.session_state:
        st.session_state["question_input"] = ""
    
    question = st.text_area(
        "질문",
        value=st.session_state["question_input"],
        height=80,
        placeholder="자유롭게 질문하세요. 예: PER이 뭐야? / 반도체 업종 비교 / 삼성전자 매출",
    )
    
    col_ask, col_clear = st.columns([1, 5])
    with col_ask:
        ask_btn = st.button("🔍 질문하기", type="primary", use_container_width=True)
    with col_clear:
        if st.button("🗑️ 초기화"):
            st.session_state["question_input"] = ""
            if "qa_response" in st.session_state:
                del st.session_state["qa_response"]
            st.rerun()
    
    if ask_btn and question.strip():
        with st.spinner("답변 생성 중..."):
            resp, err = api_post("/ask", {
                "question": question,
                "session_id": session_id,
            }, timeout=120)
            if err:
                st.error(f"❌ {err}")
            elif resp:
                st.session_state["qa_response"] = resp
                st.session_state["question_input"] = question
    
    # 답변 표시
    if "qa_response" in st.session_state:
        resp = st.session_state["qa_response"]
        intent = resp.get("intent", "")
        confidence = resp.get("confidence", "")
        elapsed = resp.get("elapsed_seconds", 0)
        
        st.divider()
        
        # 메타 (intent별 색상)
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            intent_label_map = {
                "fact_lookup": "📊 수치 조회",
                "narrative": "📖 서술 검색",
                "hybrid": "🔀 하이브리드",
                "definition": "📚 용어 정의",
                "general": "💬 일반 답변",
                "sector_compare": "🏭 업종 비교",
                "news_context": "📰 뉴스 동향",
            }
            intent_label = intent_label_map.get(intent, intent)
            st.markdown(
                f'<span class="intent-badge intent-{intent}">{intent_label}</span>'
                f' &nbsp;Confidence: <b>{confidence}</b>',
                unsafe_allow_html=True,
            )
        with col2:
            st.metric("⏱️ 응답시간", f"{elapsed:.2f}초")
        with col3:
            st.metric("📚 참고자료", f"{len(resp.get('sources', []))}개")
        
        # 답변
        st.markdown("#### 💬 답변")
        answer = resp.get("answer", "")
        if "답변 생성 중 오류" in answer or "답변 생성에 실패" in answer:
            st.warning(answer)
        elif "찾을 수 없" in answer:
            st.info(answer)
        elif intent == "general":
            # general은 일반 컨테이너로 표시 (success 색상은 부적절)
            st.markdown(answer)
        elif intent == "definition":
            # definition은 보라 톤
            st.markdown(answer)
        elif intent == "news_context":
            # 뉴스 답변은 warning(주황)으로 (공시와 시각적 구분)
            st.warning(answer)
        else:
            st.success(answer)
        
        # 출처
        if resp.get("sources"):
            st.markdown("#### 📖 참고 자료")
            for i, s in enumerate(resp.get("sources", []), 1):
                src_type = s.get("type", "document")
                
                if src_type == "news":
                    # 뉴스 출처 (news_context 의도)
                    title = s.get("title", "(제목 없음)")
                    url = s.get("url", "")
                    src_meta = s.get("source_file", "")  # "네이버 | 2시간 전" 형태
                    
                    with st.container(border=True):
                        st.markdown(f"**📰 뉴스 {i}**")
                        if url:
                            st.markdown(f"[{title}]({url})")
                        else:
                            st.markdown(title)
                        if src_meta:
                            st.caption(f"📅 {src_meta}")
                else:
                    # 공시 자료 출처
                    corp = s.get("corp_name", "")
                    fy = s.get("fiscal_year", "")
                    section = s.get("section_path_str", "")
                    src_file = s.get("source_file", "")
                    
                    with st.container(border=True):
                        meta_parts = [f"**자료 {i}**"]
                        if corp:
                            meta_parts.append(corp)
                        if fy:
                            meta_parts.append(f"{fy}년")
                        st.markdown(" · ".join(meta_parts))
                        
                        if section:
                            st.caption(f"📂 {section}")
                        if src_file:
                            st.caption(f"📄 {src_file}")


# ==========================================
# 탭 4 — 시스템 정보
# ==========================================

with tab_system:
    st.subheader("ℹ️ 시스템 정보")
    
    # Baseline 비교 카드
    st.markdown("### 📊 평가 결과 (45개 질문 기준)")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        <div style="background: #e8f5e9; padding: 1.5rem; border-radius: 8px; text-align: center;">
            <div style="font-size: 0.85rem; color: #666;">우리 시스템</div>
            <div style="font-size: 2rem; font-weight: 700; color: #2e7d32; margin: 0.5rem 0;">96.2%</div>
            <div style="font-size: 0.85rem;">Fact 정확도 (25/26)</div>
            <div style="font-size: 0.75rem; color: #888; margin-top: 0.3rem;">평균 2.5초 (fact)</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div style="background: #fff3e0; padding: 1.5rem; border-radius: 8px; text-align: center;">
            <div style="font-size: 0.85rem; color: #666;">Baseline B</div>
            <div style="font-size: 2rem; font-weight: 700; color: #e65100; margin: 0.5rem 0;">3.8%</div>
            <div style="font-size: 0.85rem;">Table-aware RAG (1/26)</div>
            <div style="font-size: 0.75rem; color: #888; margin-top: 0.3rem;">BM25 + 리랭커 포함</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown("""
        <div style="background: #ffebee; padding: 1.5rem; border-radius: 8px; text-align: center;">
            <div style="font-size: 0.85rem; color: #666;">Baseline A</div>
            <div style="font-size: 2rem; font-weight: 700; color: #c62828; margin: 0.5rem 0;">7.7%</div>
            <div style="font-size: 0.85rem;">Naive RAG (2/26)</div>
            <div style="font-size: 0.75rem; color: #888; margin-top: 0.3rem;">Vector only</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="perf-highlight">
    <b>핵심 발견</b>: 우리 시스템은 baseline 대비 <b>12~25배 높은 fact 정확도</b>를 보이며,
    fact 응답 시간은 <b>2.5초로 baseline(3.7~6.7초)보다 빠릅니다</b>. 
    XBRL 팩트 DB가 수치 조회에 필수적임을 입증합니다.
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    st.markdown("### 기능")
    fcol1, fcol2 = st.columns(2)
    
    with fcol1:
        st.markdown("""
        #### 📚 1. 금융 용어 사전 (50개)
        - 8개 카테고리: 수익성/안정성/성장성/활동성/재무제표/시장/공시/회계
        - 0초 응답 (LLM 호출 없음)
        - 정확 매칭 + 부분 검색
        - 정의 + 계산식 + 해석 가이드 + 관련 용어
        
        #### 🏭 3. 업종 비교 (Peer Analysis)
        - 7개 업종: 반도체/자동차/이차전지/바이오/철강/IT/플랫폼
        - 부문별 1위 자동 선정
        - 종합 수익성 + 영업이익률 + ROE + 부채비율 등
        """)
    
    with fcol2:
        st.markdown("""
        #### 💡 2. 재무 비율 자동 해석
        - 7개 비율: 유동비율/부채비율/자기자본비율/영업이익률/순이익률/ROA/ROE
        - 5단계 등급: 매우 우수/양호/보통/주의/위험
        - YoY 트렌드 자동 코멘트 (마진 압박 감지 등)
        
        #### 💬 4. 일반 질문 답변 (General Intent)
        - DART 외 일반 투자 지식 답변
        - 명확한 면책 표시 ("일반 지식 기반")
        - 6가지 의도 라우팅
        """)
    
    st.divider()
    
    # 아키텍처
    st.markdown("### 🏗️ 시스템 아키텍처")
    st.markdown("""
    ```
    사용자 질문
        ↓
    [라우터] intent 분류 + 엔티티 추출
        ↓
    ├── fact_lookup      → XBRL 팩트 DB (~2초)
    ├── narrative        → Chroma + BM25 + Reranker → HCX (~10초)
    ├── hybrid           → fact + narrative 결합
    ├── definition (NEW) → 용어 사전 직접 조회 (~0초)
    ├── general (NEW)    → HCX 일반 답변 + 면책 (~5초)
    └── sector_compare   → 업종 내 기업 비율 비교 (~0.1초)
    ```
    """)
    
    st.divider()
    
    # 데이터셋 통계
    st.markdown("### 데이터셋 현황")
    cols = st.columns(5)
    cols[0].metric("기업 수", "10개")
    cols[1].metric("DART XML", "37개")
    cols[2].metric("XBRL 팩트", "28,148개")
    cols[3].metric("Narrative 섹션", "755개")
    cols[4].metric("용어 사전", "50개")
    
    st.divider()
    
    # 한계
    st.markdown("### ⚠️ 시스템 한계")
    st.markdown("""
    - **HCX rate limit**: narrative/general 의도는 외부 LLM API 한도에 의존
    - **주관적 판단 회피**: "전망이 좋은가?" 등은 의도적으로 답변 회피 (투자 자문 회피)
    - **데이터 범위**: 현재 10개 기업 × 2년 (2024-2025) × 3개 보고서 유형
    - **업종 분류**: 단순 매핑 (DART KSIC 코드 미활용)
    """)


# ==========================================
# 푸터
# ==========================================

st.divider()
st.caption(
    "© 2026 DART 공시 Q&A + 분석 Project · "
    "HCX-003 · OpenAI Embeddings · BGE Reranker · "
    "용어 사전 50개 · 업종 7개"
)
