"""
Busca vetorial na knowledge base usando PostgreSQL.

Embeddings armazenados como DOUBLE PRECISION[] — similaridade de cosseno calculada em Python.
search_knowledge() é síncrona — chame via asyncio.to_thread no contexto async.
"""
import math

import psycopg2
from openai import OpenAI

from src.config.settings import settings

_EMBEDDING_MODEL = "text-embedding-3-small"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def search_knowledge(query: str, k: int = 3) -> list[str]:
    """Retorna os k chunks mais relevantes para a query usando similaridade de cosseno."""
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(model=_EMBEDDING_MODEL, input=query)
    query_embedding = response.data[0].embedding

    conn = psycopg2.connect(settings.database_url_sync)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content, embedding FROM knowledge_chunks")
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    scored = [
        (_cosine_similarity(query_embedding, row[1]), row[0])
        for row in rows
        if row[1]
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [content for _, content in scored[:k]]
