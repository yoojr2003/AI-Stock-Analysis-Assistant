import os
import json
import requests
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain_chroma import Chroma

CLOVA_API_KEY = ""
os.environ["OPENAI_API_KEY"] = ""

JSON_FILE_PATH = "/content/dart_reports/parsed_reports_table_aware.json" # BM25 인덱스용 원본 데이터
DB_PATH = "./chroma_db_table_to_text"                                    # Vector 검색용 ChromaDB 경로

def get_ensemble_retriever():
    """
    의미 기반 검색(Vector)과 키워드 기반 검색(BM25)을 결합한 하이브리드 검색기 생성
    """
    # Vector DB
    embed_model = OpenAIEmbeddings(model="text-embedding-3-small")
    vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embed_model)
    vector_retriever = vector_db.as_retriever(search_kwargs={"k": 3})

    # BM25 초기화
    with open(JSON_FILE_PATH, "r", encoding="utf-8") as f:
        all_data = json.load(f)
    
    documents = [Document(page_content=report["text"], metadata={"source": report["filename"]}) for report in all_data]
    bm25_retriever = BM25Retriever.from_documents(documents)
    bm25_retriever.k = 3

    # 3. Ensemble 결합 (가중치 1:1)
    print("앙상블 검색기 완료!")
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.5, 0.5]
    )
    return ensemble_retriever

def generate_answer(query, context):
    """
    CoT(Chain-of-Thought) 프롬프트 적용 및 HyperCLOVA X를 통한 답변 생성
    """
    url = "https://clovastudio.stream.ntruss.com/testapp/v1/chat-completions/HCX-003"
    headers = {
        'Authorization': f'Bearer {CLOVA_API_KEY}',
        'Content-Type': 'application/json'
    }

    system_prompt = """당신은 정확한 수치를 추출하는 주식 분석 비서입니다.
제공된 공시 자료(마크다운 표 및 요약본)를 바탕으로 사용자의 질문에 답하세요.
환각(오답)을 방지하기 위해 반드시 아래 단계를 거쳐 생각하고 답변하세요:
1. 시점(열) 확인
2. 항목(행) 확인
3. 숫자 추출
4. 단위 적용 (예: 백만원)

만약 문서에 해당 정보가 존재하지 않거나 확신할 수 없다면, 임의의 숫자를 지어내지 말고 "해당 정보를 찾을 수 없습니다."라고 안전하게 답변하세요."""

    user_prompt = f"[검색된 공시 자료]\n{context}\n\n[사용자 질문]\n{query}"

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "topP": 0.8,
        "temperature": 0.1,  # 정확성을 위해 낮게 설정
        "maxTokens": 500
    }

    try:
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        return res.json()['result']['message']['content']
    except Exception as e:
        return f"API 호출 오류 발생: {str(e)}"

if __name__ == "__main__":
    retriever = get_ensemble_retriever()

    test_query = "삼성전자의 2025년 3분기말(당분기말) 연결재무상태표 기준 유동자산 총계는 얼마인가요?"
    print(f"\n질의: '{test_query}'")

    print("관련 공시 문서를 탐색 중입니다.")
    docs = retriever.invoke(test_query)
    
    context_str = "\n\n".join([f"[출처: {doc.metadata.get('source', '알 수 없음')}]\n{doc.page_content[:1500]}" for doc in docs])

    print("HyperCLOVA X가 표 데이터를 분석하여 답변을 생성하고 있습니다.\n")
    answer = generate_answer(test_query, context_str)

    print("==================================================")
    print("[AI 주식 비서의 최종 답변]")
    print("==================================================")
    print(answer)