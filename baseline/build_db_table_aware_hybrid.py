import os
import shutil
import json
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

FILE_PATH = "/content/dart_reports/parsed_reports_table_aware.json"
LOCAL_DB_PATH = "./chroma_db_advanced"

os.environ["OPENAI_API_KEY"] = ""

with open(FILE_PATH, "r", encoding="utf-8") as f:
    all_data = json.load(f)

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1200,
    chunk_overlap=200
)

# 데이터 전처리 및 메타데이터 주입
print(f"총 {len(all_data)}개 기업 공시 자료 전처리")
documents = []

for report in all_data:
    source_name = report["filename"]

    chunks = text_splitter.split_text(report["text"])
    for i, chunk in enumerate(chunks):
        # 검색 효율을 위해 본문에 메타데이터 정보를 강제로 삽입
        enhanced_content = f"[문서 출처: {source_name}]\n{chunk}"

        doc = Document(
            page_content=enhanced_content,
            metadata={"source": source_name, "chunk_id": i}
        )
        documents.append(doc)

print(f"총 {len(documents)}개 청크 생성 완료")

# 임베딩 모델 및 벡터 DB 구축 (OpenAI 모델 사용)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

if os.path.exists(LOCAL_DB_PATH):
    shutil.rmtree(LOCAL_DB_PATH)

vector_db = Chroma.from_documents(
    documents=documents,
    embedding=embeddings,
    persist_directory=LOCAL_DB_PATH
)

# 의미 검색(Vector) + 키워드 검색(BM25) 결합
bm25_retriever = BM25Retriever.from_documents(documents)
bm25_retriever.k = 3

vector_retriever = vector_db.as_retriever(search_kwargs={"k": 3})

ensemble_retriever = EnsembleRetriever(
    retrievers=[bm25_retriever, vector_retriever],
    weights=[0.4, 0.6]
)

print(f"\nDB 구축 성공")