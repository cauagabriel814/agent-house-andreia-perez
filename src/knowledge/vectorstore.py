import os
from pathlib import Path

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from src.config.settings import settings

_CHROMA_DIR = str(Path(__file__).resolve().parents[2] / "data" / "chroma")
_COLLECTION = "faq_knowledge"

_embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    api_key=settings.openai_api_key,
)


def get_vectorstore() -> Chroma:
    """Retorna o vectorstore ChromaDB persistido em data/chroma/."""
    os.makedirs(_CHROMA_DIR, exist_ok=True)
    return Chroma(
        collection_name=_COLLECTION,
        embedding_function=_embeddings,
        persist_directory=_CHROMA_DIR,
    )


def search_knowledge(query: str, k: int = 3) -> list[str]:
    """Busca os k trechos mais relevantes da base de conhecimento."""
    vs = get_vectorstore()
    docs = vs.similarity_search(query, k=k)
    return [doc.page_content for doc in docs]
