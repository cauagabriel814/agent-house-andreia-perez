import uuid  # noqa
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from src.api.middleware.auth import validate_webhook_token
from src.queue.producer import publish_message
from src.utils.logger import logger

router = APIRouter()

# Tipos de mensagem UAZAPI que mapeamos para nossos tipos internos
_UAZAPI_TYPE_MAP = {
    "conversation": "text",
    "extendedtext": "text",
    "audio": "audio",
    "image": "image",
    "video": "image",
    "document": "document",
    "sticker": "sticker",
    "location": "location",
    "contact": "contact",
    "reaction": "reaction",
}


def _extract_phone(chatid: str) -> str:
    """Extrai numero de telefone limpo do chatid do WhatsApp."""
    return chatid.replace("@s.whatsapp.net", "").replace("@g.us", "")


def _map_uazapi_message(msg: dict) -> tuple[str, str | None, str | None, str | None]:
    """
    Mapeia o objeto 'message' da UAZAPI para o formato interno.

    Formato UAZAPI:
      - messageType: "Conversation", "ExtendedText", "Audio", "Image", "Video", "Document", ...
      - text / content: conteudo textual
      - mediaType: mimetype da midia (se houver)

    Retorna: (tipo_interno, conteudo, media_url, media_mimetype)
    """
    if not msg:
        return "text", None, None, None

    raw_type = (msg.get("messageType") or "").lower()
    msg_type = _UAZAPI_TYPE_MAP.get(raw_type, "text")

    # Conteudo textual: UAZAPI usa 'text' como campo principal
    content = msg.get("text") or msg.get("content") or None

    # Media: UAZAPI coloca o mimetype em 'mediaType'
    media_mimetype = msg.get("mediaType") or None
    media_url = None  # UAZAPI nao envia URL direta no webhook, midia precisa ser baixada

    return msg_type, content, media_url, media_mimetype


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    _: None = Depends(validate_webhook_token),
):
    """
    Recebe eventos da UAZAPI (WhatsApp), mapeia e publica no RabbitMQ.

    Formato UAZAPI:
      - EventType: "messages" | "chats" | "status" | ...
      - message: { chatid, fromMe, senderName, text, messageType, messageTimestamp, ... }
      - token: instance_id
    """
    body = await request.body()
    if not body:
        return {"status": "ok", "event": "empty_body"}
    payload = await request.json()

    event_type = payload.get("EventType") or payload.get("event", "")
    logger.info("WEBHOOK | Recebido | event=%s", event_type)

    # Processar apenas eventos de mensagens
    if event_type not in ("messages", "messages.upsert"):
        return {"status": "ok", "event": event_type}

    # UAZAPI: dados da mensagem ficam em 'message' (flat)
    msg = payload.get("message") or payload.get("data", {})

    # Ignorar mensagens enviadas pelo proprio bot
    if msg.get("fromMe", False):
        return {"status": "ok", "ignored": "own_message"}

    # Extrair telefone: UAZAPI usa 'chatid' ou 'sender_pn'
    chatid = msg.get("chatid") or msg.get("sender_pn", "")
    # Fallback para formato antigo (key.remoteJid)
    if not chatid:
        chatid = msg.get("key", {}).get("remoteJid", "")

    phone = _extract_phone(chatid)
    if not phone:
        logger.warning("WEBHOOK | Mensagem sem telefone: %s", chatid)
        return {"status": "ok", "ignored": "no_phone"}

    # Ignorar grupos
    if "@g.us" in chatid:
        return {"status": "ok", "ignored": "group_message"}

    # Mapear tipo e conteudo
    msg_type, content, media_url, media_mimetype = _map_uazapi_message(msg)

    # Nome do remetente
    push_name = msg.get("senderName") or payload.get("chat", {}).get("name", "")

    # Timestamp: UAZAPI envia em milissegundos
    timestamp_raw = msg.get("messageTimestamp", 0)
    if isinstance(timestamp_raw, (int, float)) and timestamp_raw > 1e12:
        timestamp_raw = timestamp_raw / 1000  # ms -> s
    timestamp = datetime.fromtimestamp(int(timestamp_raw or 0), tz=timezone.utc).isoformat()

    # Montar payload normalizado para a fila
    normalized = {
        "message_id": str(uuid.uuid4()),
        "phone": phone,
        "push_name": push_name,
        "type": msg_type,
        "content": content,
        "media_url": media_url,
        "media_mimetype": media_mimetype,
        "raw_payload": payload,
        "timestamp": timestamp,
    }

    logger.info(
        "WEBHOOK | %s | phone=%s | type=%s | msg=%s",
        push_name or "?",
        phone,
        msg_type,
        str(content)[:60] if content else "(midia)",
    )

    # Publicar na fila incoming_messages
    await publish_message("incoming_messages", normalized)

    return {"status": "ok"}
