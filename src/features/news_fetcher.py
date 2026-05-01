"""
news_fetcher.py — 네이버 뉴스 검색 API 래퍼

기능:
  1. 기업명으로 최근 뉴스 검색
  2. 5분 메모리 캐싱
  3. HTML 태그 제거, 시간 정규화
  4. 안전한 fallback
"""

from __future__ import annotations
import os
import re
import time
import html
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse

import requests


logger = logging.getLogger(__name__)

# ==========================================
# 캐시 
# ==========================================

_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SEC = 300  # 5분


def _cache_get(key: str) -> Optional[list[dict]]:
    """캐시에서 가져오기"""
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, data = entry
    if time.time() - ts > _CACHE_TTL_SEC:
        del _CACHE[key]
        return None
    return data


def _cache_set(key: str, data: list[dict]) -> None:
    """캐시에 저장"""
    _CACHE[key] = (time.time(), data)


def clear_cache() -> None:
    """캐시 전체 클리어"""
    _CACHE.clear()


# ==========================================
# HTML 정리
# ==========================================

_TAG_RE = re.compile(r'<[^>]+>')


def _clean_html(text: str) -> str:
    """HTML 태그 제거 + 엔티티 디코드 + 공백 정리"""
    if not text:
        return ""
    # 태그 제거
    text = _TAG_RE.sub('', text)
    # HTML 엔티티 (&amp; &quot; 등)
    text = html.unescape(text)
    # 연속 공백 → 단일 공백
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ==========================================
# 시간 정규화
# ==========================================

def _parse_pub_date(pub_date_str: str) -> Optional[datetime]:
    """
    네이버 API의 pubDate를 datetime으로
    형식: "Thu, 30 Apr 2026 14:30:00 +0900"
    """
    try:
        return datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z")
    except (ValueError, TypeError):
        return None


def _format_relative_time(dt: Optional[datetime]) -> str:
    """
    상대 시간 표현
    - "5분 전"
    - "3시간 전"
    - "2일 전"
    - "2026.04.20"
    """
    if not dt:
        return ""
    
    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    
    dt_kst = dt.astimezone(KST)
    diff = now - dt_kst
    
    seconds = diff.total_seconds()
    if seconds < 60:
        return "방금"
    if seconds < 3600:
        return f"{int(seconds // 60)}분 전"
    if seconds < 86400:
        return f"{int(seconds // 3600)}시간 전"
    if seconds < 604800:
        return f"{int(seconds // 86400)}일 전"
    return dt_kst.strftime("%Y.%m.%d")


# ==========================================
# 출처(언론사)
# ==========================================

# 도메인 → 언론사명
_KNOWN_SOURCES = {
    "yna.co.kr": "연합뉴스",
    "yonhapnews.co.kr": "연합뉴스",
    "chosun.com": "조선일보",
    "joins.com": "중앙일보",
    "donga.com": "동아일보",
    "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문",
    "mt.co.kr": "머니투데이",
    "hankyung.com": "한국경제",
    "edaily.co.kr": "이데일리",
    "fnnews.com": "파이낸셜뉴스",
    "newsis.com": "뉴시스",
    "sedaily.com": "서울경제",
    "biz.chosun.com": "조선비즈",
    "asiae.co.kr": "아시아경제",
    "mk.co.kr": "매일경제",
    "naver.com": "네이버",
    "ytn.co.kr": "YTN",
    "sbs.co.kr": "SBS",
    "kbs.co.kr": "KBS",
    "mbc.co.kr": "MBC",
    "etnews.com": "전자신문",
    "zdnet.co.kr": "지디넷",
    "thelec.kr": "디일렉",
    "dt.co.kr": "디지털타임스",
    "businesspost.co.kr": "비즈니스포스트",
}


def _extract_source(url: str) -> str:
    """URL에서 언론사명 추정."""
    if not url:
        return ""
    
    try:
        netloc = urlparse(url).netloc.lower()
        netloc = re.sub(r'^(www\.|m\.|news\.)', '', netloc)
        
        if netloc in _KNOWN_SOURCES:
            return _KNOWN_SOURCES[netloc]
        
        for domain, name in _KNOWN_SOURCES.items():
            if netloc.endswith(domain):
                return name
        
        return netloc.split('.')[0].upper()
    except Exception:
        return ""


# ==========================================
# 메인 함수
# ==========================================

def fetch_news(
    corp_name: str,
    n: int = 5,
    sort: str = "sim",
    use_cache: bool = True,
) -> list[dict]:
    """
    기업명으로 네이버 뉴스 검색.
    
    Args:
        corp_name: 검색 대상 기업명 (예: "삼성전자")
        n: 반환할 뉴스 개수 (1-10)
        sort: "sim" (관련도순) 또는 "date" (최신순)
        use_cache: 5분 캐시 사용 여부
    
    Returns:
        [
            {
                "title": "...",
                "summary": "...",
                "pub_date": "Thu, 30 Apr 2026 ...",
                "pub_date_relative": "3시간 전",
                "url": "https://...",
                "source": "한국경제",
            },
            ...
        ]
        실패 시 빈 리스트.
    """
    if not corp_name:
        return []
    
    cache_key = f"{corp_name}|{n}|{sort}"
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info(f"news cache hit: {corp_name}")
            return cached
    
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.warning("NAVER_CLIENT_ID/SECRET 미설정 - 뉴스 검색 불가")
        return []
    
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {
        "query": corp_name,
        "display": min(max(n, 1), 10),
        "sort": sort if sort in ("sim", "date") else "sim",
    }
    
    try:
        res = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers,
            params=params,
            timeout=10,
        )
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        logger.error(f"네이버 API 호출 실패 ({corp_name}): {e}")
        return []
    
    results = []
    for item in data.get("items", [])[:n]:
        title = _clean_html(item.get("title", ""))
        summary = _clean_html(item.get("description", ""))
        pub_date_str = item.get("pubDate", "")
        url = item.get("link") or item.get("originallink", "")
        
        pub_dt = _parse_pub_date(pub_date_str)
        relative = _format_relative_time(pub_dt) if pub_dt else ""
        
        source = _extract_source(url)
        
        results.append({
            "title": title,
            "summary": summary,
            "pub_date": pub_date_str,
            "pub_date_relative": relative,
            "pub_date_iso": pub_dt.isoformat() if pub_dt else None,
            "url": url,
            "source": source,
        })
    
    if use_cache:
        _cache_set(cache_key, results)
    
    return results


def format_news_for_llm(news_list: list[dict], max_items: int = 5) -> str:
    """
    뉴스 리스트를 LLM 프롬프트용 텍스트로 변환
    
    Returns:
        "[뉴스 1] (2026.04.30, 한국경제) 제목\n   요약 ...\n[뉴스 2] ..."
    """
    if not news_list:
        return "(최근 뉴스 없음)"
    
    lines = []
    for i, n in enumerate(news_list[:max_items], 1):
        date = n.get("pub_date_relative", "") or n.get("pub_date", "")[:16]
        source = n.get("source", "")
        title = n.get("title", "")
        summary = n.get("summary", "")
        
        header = f"[뉴스 {i}] ({date}, {source})"
        lines.append(header)
        lines.append(f"  제목: {title}")
        if summary:
            lines.append(f"  요약: {summary}")
        lines.append("")  # 빈 줄
    
    return "\n".join(lines).strip()
