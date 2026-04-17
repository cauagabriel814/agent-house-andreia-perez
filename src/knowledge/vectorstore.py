"""
Busca vetorial na knowledge base usando PostgreSQL + pgvector.

search_knowledge() é síncrona — chame via asyncio.to_thread no contexto async.
"""
import psycopg2
from pgvector.psycopg2 import register_vector
from openai import OpenAI

from src.config.settings import settings

_EMBEDDING_MODEL = "text-embedding-3-small"


def _get_conn():
    """Abre conexão psycopg2 com pgvector registrado."""
    conn = psycopg2.connect(settings.database_url_sync)
    register_vector(conn)
    return conn


def search_knowledge(query: str, k: int = 3) -> list[str]:
    """Retorna os k chunks mais relevantes para a query usando similaridade por cosseno."""
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(model=_EMBEDDING_MODEL, input=query)
    query_embedding = response.data[0].embedding

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content
                FROM knowledge_chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, k),
            )
            rows = cur.fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()
