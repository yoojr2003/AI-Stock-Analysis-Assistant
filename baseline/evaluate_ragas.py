import locale
import os
import requests
import pandas as pd
import json
import time
from datasets import Dataset
from eval_data import eval_dataset

# 시스템 환경 변수 강제 설정 (한글 깨짐 방지)
os.environ["PYTHONIOENCODING"] = "utf-8"
def getpreferredencoding(do_setlocale = True):
    return "UTF-8"
locale.getpreferredencoding = getpreferredencoding

from google.colab import drive
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_chroma import Chroma
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision
from ragas.run_config import RunConfig


CLOVA_API_KEY = ""
os.environ["OPENAI_API_KEY"] = ""

try:
    drive.mount('/content/drive')
except Exception as e:
    pass

JSON_FILE_PATH = "/content/dart_reports/parsed_reports_table_aware.json"
DRIVE_DB_PATH = "./chroma_db_table_to_text"

# ==========================================
# 검색기(Retriever) 로드
# ==========================================
print("\n하이브리드 DB 및 검색기를 로드합니다")

# Vector DB 로드 (의미 검색)
embed_model = OpenAIEmbeddings(model="text-embedding-3-small")
vector_db = Chroma(persist_directory=DRIVE_DB_PATH, embedding_function=embed_model)
vector_retriever = vector_db.as_retriever(search_kwargs={"k": 3})

# BM25 로드 (키워드 검색)
with open(JSON_FILE_PATH, "r", encoding="utf-8") as f:
    all_data = json.load(f)
docs_for_bm25 = [Document(page_content=f"[문서 출처: {report['filename']}]\n{report['text']}") for report in all_data]
bm25_retriever = BM25Retriever.from_documents(docs_for_bm25)
bm25_retriever.k = 3

# 앙상블 결합
ensemble_retriever = EnsembleRetriever(
    retrievers=[bm25_retriever, vector_retriever],
    weights=[0.4, 0.6]
)
print("검색기 로드 완료")

# ==========================================
# 답변 생성 함수 (400 에러 방지)
# ==========================================
def generate_rag_response(query, retriever):
    results = retriever.invoke(query)

    # 400 Bad Request 방지
    results = results[:3]

    contexts = [doc.page_content for doc in results]
    context_str = "\n".join(contexts)

    url = "https://clovastudio.stream.ntruss.com/testapp/v1/chat-completions/HCX-003"
    headers = {
        'Authorization': f'Bearer {CLOVA_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    system_prompt = "당신은 주식 분석 비서입니다. [공시 자료]를 분석하여 [사용자 질문]에 답하세요. 표(|) 형태의 데이터가 있다면 행과 열을 꼼꼼히 분석하여 숫자를 정확히 답변하세요."
    user_prompt = f"[공시 자료]\n{context_str}\n\n[사용자 질문]\n{query}"

    payload = {
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "topP": 0.8, "temperature": 0.1, "maxTokens": 500
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        answer = response.json()['result']['message']['content']
        return answer, contexts
    except Exception as e:
        error_msg = f"API 오류: {str(e)}"
        if hasattr(response, 'text'):
            error_msg += f" | {response.text}"
        return error_msg, contexts

# ==========================================
# 답변 생성 및 다이어트 (Timeout 방지)
# ==========================================
print("\n데이터셋 답변 생성 시작")

ragas_data_advanced = {"question": [], "answer": [], "contexts": [], "ground_truth": []}

for i, item in enumerate(eval_dataset):
    print(f"[{i+1}/{len(eval_dataset)}] '{item['question'][:15]}' 처리")

    ans_adv, ctx_adv = generate_rag_response(item['question'], ensemble_retriever)

    short_ctx = [c[:600] for c in ctx_adv]

    ragas_data_advanced["question"].append(item['question'])
    ragas_data_advanced["answer"].append(ans_adv)
    ragas_data_advanced["contexts"].append(short_ctx)
    ragas_data_advanced["ground_truth"].append(item['ground_truth'])

    time.sleep(1)

# ==========================================
# RAGAS 채점 함수 (1개씩)
# ==========================================
def evaluate(data_dict, metrics, llm, embeddings, run_config):
    dataset = Dataset.from_dict(data_dict)
    results_list = []

    for i in range(len(dataset)):
        item_batch = dataset.select([i])
        print(f"{i+1}/{len(dataset)}번 항목 진행 중...")

        try:
            res = evaluate(
                item_batch, metrics=metrics, llm=llm, embeddings=embeddings,
                run_config=run_config, show_progress=False
            )
            results_list.append(res.to_pandas())
            time.sleep(3) # OpenAI 과부하 방지 휴식

        except Exception as e:
            print(f"   {i+1}번 오류 발생(스킵): {e}")
            time.sleep(10)

    return pd.concat(results_list, ignore_index=True)

evaluator_llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0)
evaluator_embeddings = OpenAIEmbeddings()
eval_metrics = [faithfulness, answer_relevancy, context_precision]
custom_run_config = RunConfig(timeout=120, max_retries=3, max_workers=1)

print("\nRAGAS 채점 시작")
df_res_advanced = evaluate(ragas_data_advanced, eval_metrics, evaluator_llm, evaluator_embeddings, custom_run_config)

# ==========================================
#  결과 출력
# ==========================================
if not df_res_advanced.empty:
    print("\n[RAG 평가 평균 점수]")
    print(df_res_advanced[['faithfulness', 'answer_relevancy', 'context_precision']].mean())

    SAVE_PATH = "/content/drive/MyDrive/AI_Stock_Assistant/ragas_table_to_text.csv"
    df_res_advanced.to_csv(SAVE_PATH, index=False, encoding='utf-8-sig')
    print(f"\n저장 완료: {SAVE_PATH}")
else:
    print("결과가 없습니다.")