from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
import os
import shutil

all_data = parsed_reports

# 텍스트 분할기 설정
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100,
    separators=["\n\n", "\n", ".", " ", ""]
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

# 로컬 환경에 전체 DB 구축
LOCAL_DB_PATH = "./chroma_db_final"

# 기존 로컬 폴더 초기화
if os.path.exists(LOCAL_DB_PATH):
    shutil.rmtree(LOCAL_DB_PATH)

print("벡터 데이터베이스 구축 시작")

vector_db = Chroma.from_documents(
    documents=documents,
    embedding=embeddings,
    persist_directory=LOCAL_DB_PATH
)

print(f"\n 벡터 데이터베이스 구축 성공 (총 {vector_db._collection.count()}개 데이터 저장)")
