"""
worker.py - Processo separado para consumir mensagens do RabbitMQ e executar o agente.

Rodar com:
    python worker.py

Responsabilidades:
    - Consome fila incoming_messages → executa o agente LangGraph
    - Roda o scheduler de cron jobs (timeouts, reengajamentos, nutrimento)

A API (uvicorn src.api.main:app) fica responsavel apenas por receber
webhooks e publicar mensagens na fila — sem processamento de agente.
"""

import asyncio
import os

# Logger PRIMEIRO — configura niveis antes de qualquer outro import
from src.utils.logger import logger  # noqa: E402

from src.config.settings import settings
from src.jobs.scheduler import start_scheduler, stop_scheduler
from src.knowledge.ingest import ensure_knowledge_loaded
from src.queue.connection import close_rabbitmq_connection, setup_queues
from src.queue.consumer import start_consumer, stop_consumer
from src.queue.dispatcher import handle_incoming_message


async def main() -> None:
    logger.info("WORKER | Iniciando...")

    # --- LangSmith: ativar tracing via variaveis de ambiente ---
    if settings.langchain_tracing_v2 and settings.langchain_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        logger.info(
            "WORKER | LangSmith tracing ativado | project=%s", settings.langchain_project
        )
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.info("WORKER | LangSmith tracing desativado (LANGCHAIN_API_KEY nao configurado)")

    await ensure_knowledge_loaded()

    await setup_queues()
    logger.info("WORKER | Filas RabbitMQ declaradas")

    await start_consumer("incoming_messages", handle_incoming_message)
    logger.info("WORKER | Consumer ativo — ouvindo fila incoming_messages")

    await start_scheduler(interval_seconds=60)
    logger.info("WORKER | Scheduler ativo (intervalo=60s)")

    logger.info("WORKER | Pronto. Aguardando mensagens...")

    try:
        await asyncio.Future()  # bloqueia para sempre ate Ctrl+C
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("WORKER | Sinal de encerramento recebido")
    finally:
        await stop_scheduler()
        await stop_consumer()
        await close_rabbitmq_connection()
        logger.info("WORKER | Encerrado.")


if __name__ == "__main__":
    asyncio.run(main())
