import aio_pika

from src.config.settings import settings

_connection = None

QUEUE_NAMES = [
    "incoming_messages",
    "outgoing_messages",
    "scheduled_jobs",
    "notifications",
]


async def get_rabbitmq_connection() -> aio_pika.abc.AbstractRobustConnection:
    """Retorna conexao singleton com o RabbitMQ."""
    global _connection
    if _connection is None or _connection.is_closed:
        _connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    return _connection


async def setup_queues():
    """Declara todas as filas necessarias no RabbitMQ como durable."""
    connection = await get_rabbitmq_connection()
    async with connection.channel() as channel:
        for name in QUEUE_NAMES:
            await channel.declare_queue(name, durable=True)


async def close_rabbitmq_connection():
    """Fecha a conexao com o RabbitMQ."""
    global _connection
    if _connection and not _connection.is_closed:
        await _connection.close()
        _connection = None
