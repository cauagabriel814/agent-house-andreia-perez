import asyncio
import json
from typing import Awaitable, Callable

import aio_pika

from src.queue.connection import get_rabbitmq_connection
from src.utils.logger import logger

_consumer_task: asyncio.Task | None = None


async def consume_messages(
    queue_name: str,
    callback: Callable[[dict], Awaitable[None]],
):
    """Consome mensagens de uma fila do RabbitMQ."""
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    queue = await channel.declare_queue(queue_name, durable=True)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                payload = json.loads(message.body.decode())
                logger.info(
                    "CONSUMER | Mensagem consumida | fila=%s | phone=%s",
                    queue_name,
                    payload.get("phone", "?"),
                )
                await callback(payload)


async def start_consumer(
    queue_name: str,
    callback: Callable[[dict], Awaitable[None]],
) -> asyncio.Task:
    """
    Inicia o consumer como background task com reconexao automatica.
    Em caso de erro, aguarda 5 segundos e tenta reconectar.
    """
    global _consumer_task

    async def _run():
        while True:
            try:
                logger.info("CONSUMER | Iniciando consumer | fila=%s", queue_name)
                await consume_messages(queue_name, callback)
            except asyncio.CancelledError:
                logger.info("CONSUMER | Consumer encerrado | fila=%s", queue_name)
                break
            except Exception as exc:
                logger.error(
                    "CONSUMER | Erro no consumer | fila=%s | erro=%s | Reconectando em 5s...",
                    queue_name,
                    exc,
                )
                await asyncio.sleep(5)

    _consumer_task = asyncio.create_task(_run())
    return _consumer_task


async def stop_consumer():
    """Para o consumer de forma segura."""
    global _consumer_task
    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
        _consumer_task = None
        logger.info("CONSUMER | Consumer parado com sucesso")


def is_consumer_running() -> bool:
    """Retorna True se o consumer esta ativo."""
    return _consumer_task is not None and not _consumer_task.done()
