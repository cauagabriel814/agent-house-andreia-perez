"""
Ingestão da knowledge base no PostgreSQL (pgvector).

- ingest_text()             : ingere texto puro, dividindo em chunks e gerando embeddings
- ensure_knowledge_loaded() : verifica se a tabela está vazia e ingere automaticamente
"""
import asyncio

import psycopg2
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from pgvector.psycopg2 import register_vector

from src.config.settings import settings
from src.utils.logger import logger

_EMBEDDING_MODEL = "text-embedding-3-small"
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50


def _get_conn():
    conn = psycopg2.connect(settings.database_url_sync)
    register_vector(conn)
    return conn


def ingest_text(text: str, source: str = "manual", clear: bool = True) -> int:
    """
    Divide o texto em chunks, gera embeddings e insere na tabela knowledge_chunks.

    Args:
        text:   Conteúdo a ser indexado.
        source: Identificador da fonte (gravado nos metadados).
        clear:  Se True, apaga todos os chunks existentes antes de inserir.

    Returns:
        Número de chunks inseridos.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
    )
    chunks = splitter.split_text(text)
    if not chunks:
        return 0

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(model=_EMBEDDING_MODEL, input=chunks)
    embeddings = [item.embedding for item in response.data]

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            if clear:
                cur.execute("TRUNCATE knowledge_chunks")
            cur.executemany(
                "INSERT INTO knowledge_chunks (content, embedding, source) VALUES (%s, %s::vector, %s)",
                [(chunk, emb, source) for chunk, emb in zip(chunks, embeddings)],
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return len(chunks)


async def ensure_knowledge_loaded() -> None:
    """
    Verifica se há chunks na knowledge base.
    Se a tabela estiver vazia, executa o ingest automático com o KNOWLEDGE_TEXT padrão.
    Chamado no startup do worker.
    """
    from src.db.database import async_session
    import sqlalchemy as sa

    async with async_session() as session:
        result = await session.execute(sa.text("SELECT COUNT(*) FROM knowledge_chunks"))
        count = result.scalar() or 0

    if count > 0:
        logger.info("KNOWLEDGE | Base carregada | chunks=%d", count)
        return

    logger.info("KNOWLEDGE | Tabela vazia — iniciando ingestão automática...")
    from src.knowledge.knowledge_base import KNOWLEDGE_TEXT

    n = await asyncio.to_thread(ingest_text, KNOWLEDGE_TEXT, "knowledge_base", True)
    logger.info("KNOWLEDGE | Ingestão concluída | chunks=%d", n)
