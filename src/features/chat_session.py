"""
chat_session.py — 챗봇 세션 메모리

기능:
  1. 엔티티 메모리: last_corp, last_year, last_period_scope 등 추적
  2. 대화 이력: 최근 5개 Q&A 보관
  3. 후속 질문 해결: "전년 대비는?", "그럼 영업이익은?" 같은 생략 보충
  4. 자동 만료: 30분 inactivity 후 세션 삭제
"""

from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field
from typing import Optional


# ==========================================
# 후속 질문 단서 키워드
# ==========================================

# "전년 대비는?", "이전 대비는?" — 같은 회사·계정에서 시점 비교
COMPARE_KW = ["전년", "전기", "이전", "전 분기", "직전", "지난해", "작년"]

# "그럼 영업이익은?", "그러면 매출은?" — 같은 회사·시점에서 다른 계정
SWITCH_ACCOUNT_KW = ["그럼", "그러면", "그리고", "또한", "다음으로"]

# "최근 매출은?", "지금은?" — 가장 최신 데이터
LATEST_KW = ["최근", "지금", "현재", "요즘"]

# 대명사 (회사명 대체)
PRONOUN_KW = ["이 회사", "그 회사", "이 기업", "그 기업", "여기", "거기"]


# ==========================================
# 세션 데이터 클래스
# ==========================================

@dataclass
class ConversationTurn:
    query: str
    intent: str
    corp_name: Optional[str] = None
    fiscal_year: Optional[int] = None
    period_scope: Optional[str] = None
    account_kr: Optional[str] = None
    answer_snippet: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ChatSession:
    session_id: str
    history: list[ConversationTurn] = field(default_factory=list)
    last_corp: Optional[str] = None
    last_year: Optional[int] = None
    last_period_scope: Optional[str] = None
    last_account: Optional[str] = None
    last_statement: Optional[str] = None
    last_intent: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    MAX_HISTORY = 5
    
    def resolve_query(self, qi, query: str):
        """
        후속 질문
        """
        # 메모리가 비어있으면 그대로 반환
        if not self.last_corp:
            return qi
        
        is_first_turn = not self.history
        if is_first_turn:
            return qi
        
        # 1. 회사명 보충
        # 명시적으로 안 잡혔으면 last_corp 사용
        if not qi.corp_name:
            qi.corp_name = self.last_corp
            qi._memory_used = True  # type: ignore
        
        # 2. 대명사 케이스
        if any(p in query for p in PRONOUN_KW):
            if self.last_corp:
                qi.corp_name = self.last_corp
                qi._memory_used = True  # type: ignore
        
        # 3. 전년 대비
        if any(kw in query for kw in COMPARE_KW):
            if self.last_year and not qi.fiscal_year:
                # 전년이면 last_year - 1
                qi.fiscal_year = self.last_year - 1 if "전년" in query or "작년" in query or "지난해" in query else self.last_year
                qi._memory_used = True  # type: ignore
            # period_scope 유지
            if self.last_period_scope and not qi.period_scope:
                qi.period_scope = self.last_period_scope
            # account/statement 유지
            if self.last_account and not qi.account_kr:
                qi.account_kr = self.last_account
            if self.last_statement and not qi.statement:
                qi.statement = self.last_statement
        
        # 4. 시점 유지, 계정만 변경
        elif any(kw in query for kw in SWITCH_ACCOUNT_KW):
            if not qi.fiscal_year and self.last_year:
                qi.fiscal_year = self.last_year
                qi._memory_used = True  # type: ignore
            if not qi.period_scope and self.last_period_scope:
                qi.period_scope = self.last_period_scope
            if not qi.statement and self.last_statement:
                qi.statement = self.last_statement
        
        # 5. period_scope 일반 보충
        elif not qi.fiscal_year and not qi.period_scope:
            # 마지막 시점 가정
            if self.last_year:
                qi.fiscal_year = self.last_year
                qi._memory_used = True
            if self.last_period_scope:
                qi.period_scope = self.last_period_scope
        
        return qi
    
    def add_turn(self, query: str, qi, response_snippet: str = "") -> None:
        # 대화 이력 추가
        turn = ConversationTurn(
            query=query,
            intent=qi.intent,
            corp_name=qi.corp_name,
            fiscal_year=qi.fiscal_year,
            period_scope=qi.period_scope,
            account_kr=qi.account_kr,
            answer_snippet=response_snippet[:100],
        )
        self.history.append(turn)
        if len(self.history) > self.MAX_HISTORY:
            self.history.pop(0)
        
        if qi.corp_name:
            self.last_corp = qi.corp_name
        if qi.fiscal_year:
            self.last_year = qi.fiscal_year
        if qi.period_scope:
            self.last_period_scope = qi.period_scope
        if qi.account_kr:
            self.last_account = qi.account_kr
        if qi.statement:
            self.last_statement = qi.statement
        if qi.intent:
            self.last_intent = qi.intent
        
        self.updated_at = time.time()
    
    def get_context_summary(self) -> dict:
        """디버깅/UI용 현재 메모리 상태."""
        return {
            "session_id": self.session_id,
            "turn_count": len(self.history),
            "last_corp": self.last_corp,
            "last_year": self.last_year,
            "last_period_scope": self.last_period_scope,
            "last_account": self.last_account,
            "last_intent": self.last_intent,
            "history_brief": [
                {
                    "q": t.query[:40],
                    "intent": t.intent,
                    "corp": t.corp_name,
                }
                for t in self.history
            ],
        }
    
    def reset(self) -> None:
        """세션 초기화"""
        self.history.clear()
        self.last_corp = None
        self.last_year = None
        self.last_period_scope = None
        self.last_account = None
        self.last_statement = None
        self.last_intent = None
        self.updated_at = time.time()


# ==========================================
# 세션 관리자
# ==========================================

class SessionManager:
    
    SESSION_TTL_SEC = 30 * 60  # 30분
    
    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()
    
    def get_or_create(self, session_id: str) -> ChatSession:
        """세션 조회. 없으면 새로 생성."""
        with self._lock:
            self._cleanup_expired()
            if session_id not in self._sessions:
                self._sessions[session_id] = ChatSession(session_id=session_id)
            return self._sessions[session_id]
    
    def get(self, session_id: str) -> Optional[ChatSession]:
        """세션 조회"""
        with self._lock:
            self._cleanup_expired()
            return self._sessions.get(session_id)
    
    def reset(self, session_id: str) -> bool:
        """세션 초기화"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.reset()
                return True
            return False
    
    def delete(self, session_id: str) -> bool:
        """세션 완전 삭제"""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None
    
    def _cleanup_expired(self) -> None:
        """만료된 세션 정리"""
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.updated_at > self.SESSION_TTL_SEC
        ]
        for sid in expired:
            del self._sessions[sid]
    
    def stats(self) -> dict:
        """통계"""
        with self._lock:
            self._cleanup_expired()
            return {
                "active_sessions": len(self._sessions),
                "session_ids": list(self._sessions.keys()),
            }


# ==========================================
# 전역 싱글턴
# ==========================================

_global_manager: Optional[SessionManager] = None


def get_global_manager() -> SessionManager:
    """전역 SessionManager (싱글턴)."""
    global _global_manager
    if _global_manager is None:
        _global_manager = SessionManager()
    return _global_manager


# ==========================================
# 테스트
# ==========================================

if __name__ == "__main__":
    """직접 실행: 동작 확인"""
    
    # 가짜 QueryInfo (router 의존 없이 테스트)
    class FakeQI:
        def __init__(self, corp=None, year=None, scope=None, account=None,
                     stmt=None, intent="fact_lookup"):
            self.corp_name = corp
            self.fiscal_year = year
            self.period_scope = scope
            self.account_kr = account
            self.statement = stmt
            self.intent = intent
    
    print("=" * 60)
    print("  ChatSession 시나리오 테스트")
    print("=" * 60)
    
    mgr = SessionManager()
    session = mgr.get_or_create("test-001")
    
    # Turn 1: "삼성전자 2025년 매출은?"
    print("\n[Turn 1] 사용자: 삼성전자 2025년 매출은?")
    qi1 = FakeQI(corp="삼성전자", year=2025, account="매출액", stmt="포괄손익계산서")
    qi1_resolved = session.resolve_query(qi1, "삼성전자 2025년 매출은?")
    print(f"   resolved: corp={qi1_resolved.corp_name}, year={qi1_resolved.fiscal_year}")
    session.add_turn("삼성전자 2025년 매출은?", qi1, "333.6조원")
    print(f"   메모리: {session.get_context_summary()}")
    
    # Turn 2: "전년 대비는?" (회사·계정 생략)
    print("\n[Turn 2] 사용자: 전년 대비는?")
    qi2 = FakeQI()  # 모든 필드 비어있음
    qi2_resolved = session.resolve_query(qi2, "전년 대비는?")
    print(f"   resolved: corp={qi2_resolved.corp_name}, year={qi2_resolved.fiscal_year}, "
          f"account={qi2_resolved.account_kr}")
    print(f"   ✅ corp={qi2_resolved.corp_name}, year={qi2_resolved.fiscal_year} "
          f"(메모리에서 복원, year은 -1 = 2024)")
    session.add_turn("전년 대비는?", qi2_resolved, "전년 대비 +6.5%")
    
    # Turn 3: "그럼 영업이익은?" (회사·시점 유지, 계정만 바꿈)
    print("\n[Turn 3] 사용자: 그럼 영업이익은?")
    qi3 = FakeQI(account="영업이익")  # 회사·시점 없음
    qi3_resolved = session.resolve_query(qi3, "그럼 영업이익은?")
    print(f"   resolved: corp={qi3_resolved.corp_name}, year={qi3_resolved.fiscal_year}, "
          f"account={qi3_resolved.account_kr}")
    session.add_turn("그럼 영업이익은?", qi3_resolved, "43.6조원")
    
    # Turn 4: "이 회사 사업 부문은?" (대명사)
    print("\n[Turn 4] 사용자: 이 회사 사업 부문은?")
    qi4 = FakeQI(intent="narrative")
    qi4_resolved = session.resolve_query(qi4, "이 회사 사업 부문은?")
    print(f"   resolved: corp={qi4_resolved.corp_name}")
    session.add_turn("이 회사 사업 부문은?", qi4_resolved, "DX, DS, ...")
    
    print("\n" + "=" * 60)
    print("  최종 메모리 상태")
    print("=" * 60)
    import json
    print(json.dumps(session.get_context_summary(), ensure_ascii=False, indent=2))
    
    # 리셋 테스트
    print("\n[리셋 테스트]")
    session.reset()
    print(f"리셋 후: {session.get_context_summary()}")
