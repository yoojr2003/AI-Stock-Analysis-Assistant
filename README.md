# AI 주식 분석 및 정보 어시스턴트 (Table-Aware RAG)

![Python](https://img.shields.io/badge/Python-3.10-blue)
![LangChain](https://img.shields.io/badge/LangChain-Framework-green)
![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_DB-orange)

본 프로젝트는 DART(전자공시시스템)의 비정형/반정형 공시 자료를 기반으로, 개인 투자자에게 정확한 정보를 자연어 대화 형태로 제공하는 AI 주식 분석 비서입니다.

# 프로젝트 배경 및 목적
기존의 대형언어모델(LLM)과 RAG(검색 증강 생성) 시스템은 텍스트 청킹(Chunking) 과정에서 재무제표와 같은 2차원 표(Table) 구조를 파괴하여, 숫자를 잘못 추출하는 심각한 환각(Hallucination) 오류를 발생시킵니다. 
본 프로젝트는 이러한 한계를 극복하기 위해 하이브리드 검색(Hybrid Search)과 Table-to-Text 데이터 증강 기법을 결합한  RAG 파이프라인을 제안합니다.

# 핵심 기술 및 파이프라인

1. 표 구조 보존 파싱 (Table-Aware Parsing)
   - `BeautifulSoup`과 `Pandas`를 활용하여 복잡한 HTML 재무제표를 마크다운(`|---|`) 형태로 정밀하게 변환합니다.
2. Table-to-Text 데이터 증강 (Data Augmentation)
   - 문서가 DB에 적재되기 전, 표가 감지되면 LLM을 호출하여 표의 주요 수치를 자연어 줄글로 요약하고 원본에 결합(`[AI 표 요약]`)하여 문맥 단절을 방지합니다.
3. 하이브리드 앙상블 검색 (Ensemble Retriever)
   - 의미 기반의 밀집 검색(`Vector Search`, ChromaDB)과 키워드 기반의 희소 검색(`BM25`)을 1:1 가중치로 결합하여 금융 고유명사와 수치 검색의 정밀도를 높였습니다.
4. CoT(Chain-of-Thought) 기반 수치 추출
   - 최종 답변 생성 시 `행(Row) -> 열(Column) -> 교차 수치 추출`의 과정을 강제하여 환각을 억제합니다.

# 디렉토리 구조 (Directory Structure)

```text
AI-Stock-Analysis-Assistant/
├── data/                  # 원본 및 파싱된 DART JSON 데이터 보관
├── db/                    # Vector DB (ChromaDB) 보관 장소
├── docs/                  # 프로젝트 제안서 및 보고서
├── src/                   # 소스 코드
│   ├── extract_baseline.py           # 기본 텍스트 파싱
│   ├── extract_table_aware.py        # 표 구조 보존 마크다운 파싱
│   ├── build_db_baseline.py          # 기본 벡터 DB 구축
│   ├── build_db_table_aware.py       # 표 인지형 DB 구축
│   ├── build_db_table_to_text.py     # LLM 요약(Table-to-Text) 적용 DB 구축
│   ├── build_db_hybrid.py            # 하이브리드 검색기 세팅
│   ├── retriever_hybrid.py           # 검색 및 AI 답변 생성 모듈 (Serving)
│   ├── eval_data.py                  # 평가용 질의응답 데이터셋 (Ground Truth)
│   └── evaluate_ragas.py             # RAGAS 프레임워크 기반 성능 자동 채점
├── requirements.txt
└── README.md

이 프로젝트는 구글 코랩 환경에서 테스트되었습니다
