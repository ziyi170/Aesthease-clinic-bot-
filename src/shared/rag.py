import os
import json
import chromadb
from chromadb.utils import embedding_functions

FAQ_PATH = os.getenv("FAQ_PATH", "faq/data.json")
CHROMA_PATH = os.getenv("CHROMA_PATH", "data/chroma_db")


def get_rag_collection():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    # 使用本地 sentence-transformers，完全免费，不需要任何 API key
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    return client.get_or_create_collection(
        name="clinic_faq",
        embedding_function=ef
    )


def index_faq_documents():
    with open(FAQ_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    collection = get_rag_collection()
    documents, ids = [], []

    for i, item in enumerate(data):
        doc = f"Q: {item['question']}\nA: {item['answer']}"
        documents.append(doc)
        ids.append(f"faq_{i}")

    collection.upsert(documents=documents, ids=ids)
    print(f"Indexed {len(documents)} FAQ entries into ChromaDB.")


def query_faq(question: str, n_results: int = 3) -> str:
    collection = get_rag_collection()
    results = collection.query(query_texts=[question], n_results=n_results)
    docs = results.get("documents", [[]])[0]
    return "\n\n".join(docs) if docs else ""


if __name__ == "__main__":
    index_faq_documents()
