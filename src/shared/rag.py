"""
RAG knowledge base using JSONLoader + jq_schema (from Repo 2 pattern).
Loads faq/data.json, embeds with OpenAI, stores in ChromaDB.
"""
import os
import json
import chromadb
from chromadb.utils import embedding_functions

FAQ_PATH = os.getenv("FAQ_PATH", "faq/data.json")
CHROMA_PATH = os.getenv("CHROMA_PATH", "data/chroma_db")


def get_rag_collection():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    openai_ef = embedding_functions.OpenAIEmbeddingFunction(
        api_key=os.getenv("OPENAI_API_KEY"),
        model_name="text-embedding-3-small"
    )
    return client.get_or_create_collection(
        name="clinic_faq",
        embedding_function=openai_ef
    )


def index_faq_documents():
    """
    Load faq/data.json using jq_schema pattern (Repo 2).
    Each FAQ entry becomes one document: question + answer combined.
    """
    with open(FAQ_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    collection = get_rag_collection()
    documents, ids = [], []

    for i, item in enumerate(data):
        # jq_schema pattern: combine question + answer into one searchable chunk
        doc = f"Q: {item['question']}\nA: {item['answer']}"
        documents.append(doc)
        ids.append(f"faq_{i}")

    collection.upsert(documents=documents, ids=ids)
    print(f"Indexed {len(documents)} FAQ entries into ChromaDB.")


def query_faq(question: str, n_results: int = 3) -> str:
    """Search the knowledge base and return relevant FAQ text."""
    collection = get_rag_collection()
    results = collection.query(query_texts=[question], n_results=n_results)
    docs = results.get("documents", [[]])[0]
    return "\n\n".join(docs) if docs else ""


if __name__ == "__main__":
    index_faq_documents()
