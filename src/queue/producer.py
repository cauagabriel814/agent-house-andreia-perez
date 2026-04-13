import json

import aio_pika

from src.queue.connection import get_rabbitmq_connection
from src.utils.logger import logger


async def publish_message(queue_name: str, message: dict):
    """Publica uma mensagem na fila do RabbitMQ."""
    connection = await get_rabbitmq_connection()
    async with connection.channel() as channel:
        await channel.declare_queue(queue_name, durable=True)
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(message).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=queue_name,
        )
    logger.info(
        "QUEUE | Publicado | fila=%s | phone=%s",
        queue_name,
        message.get("phone", "?"),
    )
