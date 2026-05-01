from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
import os
import shutil
import json

# Table-Aware 데이터 파일 불러오기
FILE_PATH = "/content/dart_reports/parsed_reports_table_aware.json"

with open(FILE_PATH, "r", encoding="utf-8") as f:
    all_data = json.load(f)

# 텍스트 분할기 설정 (마크다운 표가 잘리지 않도록 크기 1500)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1500,
    chunk_overlap=200,
    separators=["\n\n\n", "\n\n", "\n", ".", " ", ""]
)

print(f"총 {len(all_data)}개 기업 공시 자료 텍스트 분할 시작")
documents = []
for report in all_data:
    chunks = text_splitter.split_text(report["text"])
    for i, chunk in enumerate(chunks):
        doc = Document(
            page_content=chunk,
            metadata={"source": report["filename"], "chunk_id": i}
        )
        documents.append(doc)

print(f"총 {len(documents)}개의 청크 조각 생성\n")

# 임베딩 모델 로드
print("임베딩 모델 로드")
embeddings = HuggingFaceEmbeddings(
    model_name="jhgan/ko-sroberta-multitask",
    model_kwargs={'device': 'cuda'},
    encode_kwargs={'normalize_embeddings': True}
)

# 로컬 환경에 Table-Aware DB 구축
LOCAL_DB_PATH = "./chroma_db_table_aware"

# 기존 로컬 폴더 초기화
if os.path.exists(LOCAL_DB_PATH):
    shutil.rmtree(LOCAL_DB_PATH)

print("표 구조가 보존된 벡터 데이터베이스 구축 시작")

vector_db = Chroma.from_documents(
    documents=documents,
    embedding=embeddings,
    persist_directory=LOCAL_DB_PATH
)

print(f"\n데이터베이스 구축 성공 (총 {vector_db._collection.count()}개 데이터 저장)")