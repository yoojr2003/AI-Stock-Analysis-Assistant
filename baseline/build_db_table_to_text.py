import os
import requests
import json
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_chroma import Chroma
import time


CLOVA_API_KEY = ""
os.environ["OPENAI_API_KEY"] = ""

JSON_FILE_PATH = "/content/dart_reports/parsed_reports_table_aware.json"
NEW_DB_PATH = "./chroma_db_table_to_text"

# ==========================================
# 표 -> 줄글 요약(Table-to-Text) 함수
# ==========================================
def summarize_table(table_text):
    url = "https://clovastudio.stream.ntruss.com/testapp/v1/chat-completions/HCX-003"
    headers = {
        'Authorization': f'Bearer {CLOVA_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    system_prompt = """당신은 데이터 전처리 전문가입니다.
주어진 마크다운 표를 분석하여, 검색 엔진이 잘 찾을 수 있도록 주요 수치(예: 매출액, 영업이익, 자산 총계 등)를 자연스러운 '줄글(Text)'로 요약해주세요.
예시: '2025년 3분기말 기준 유동자산은 100,000 백만원, 영업이익은 50,000 백만원입니다.'"""

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"다음 표를 줄글로 요약해줘:\n{table_text[:1000]}"} # 안전을 위해 1000자 제한
        ],
        "topP": 0.8, "temperature": 0.1, "maxTokens": 300
    }

    try:
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        return res.json()['result']['message']['content']
    except Exception as e:
        return "" # 에러 시 빈 문자열 반환

# ==========================================
# 데이터 증강 및 새로운 문서 객체 생성
# ==========================================
print("원본 JSON 데이터를 불러와 Table-to-Text 변환 시작")
with open(JSON_FILE_PATH, "r", encoding="utf-8") as f:
    all_data = json.load(f)

sample_data = all_data
augmented_documents = []

for idx, report in enumerate(sample_data):
    print(f"[{idx+1}/{len(sample_data)}] '{report['filename']}' 처리")

    # 문서를 대략적인 문단이나 표 단위로 쪼갬
    chunks = report['text'].split('\n\n')

    for i, chunk in enumerate(chunks):
        if len(chunk) < 50: continue 

        enhanced_content = f"[문서 출처: {report['filename']}]\n"

        #  마크다운 표 기호('|---')가 포함되어 있다면 LLM 요약
        if "|---" in chunk or "| :" in chunk or "|:" in chunk:
            print("LLM 요약(Table-to-Text) 생성")
            summary = summarize_table(chunk)
            if summary:
                # 원본 표 위에 LLM이 생성한 '친절한 줄글 요약'을 덧붙임 (데이터 증강)
                enhanced_content += f"[AI 표 요약] {summary}\n\n[원본 표]\n{chunk}"
            else:
                enhanced_content += chunk
            time.sleep(1) # API 과부하 방지
        else:
            enhanced_content += chunk # 표가 아니면 그냥 원본 텍스트 사용

        doc = Document(page_content=enhanced_content, metadata={"source": report['filename']})
        augmented_documents.append(doc)

print(f"\n✅ 총 {len(augmented_documents)}개의 문서(Chunk) 생성 완료")

# ==========================================
# 새로운 Table-to-Text DB 저장
# ==========================================
print("\n저장")
embed_model = OpenAIEmbeddings(model="text-embedding-3-small")
vector_db_t2t = Chroma.from_documents(
    documents=augmented_documents,
    embedding=embed_model,
    persist_directory=NEW_DB_PATH
)
print(f"Table-to-Text 기법이 적용 DB 생성 완료")