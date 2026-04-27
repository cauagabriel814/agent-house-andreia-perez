import uuid  # noqa
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text

from src.api.middleware.auth import validate_webhook_token
from src.db.database import async_session
from src.db.models.blocked_number import BlockedNumber
from src.queue.producer import publish_message
from src.utils.logger import logger

router = APIRouter()

# Tipos de mensagem UAZAPI que mapeamos para nossos tipos internos
_UAZAPI_TYPE_MAP = {
    "conversation": "text",
    "extendedtext": "text",
    # Áudio: "audio" = arquivo de áudio, "ptt" = mensagem de voz gravada no WhatsApp
    "audio": "audio",
    "ptt": "audio",
    "voice": "audio",
    "audiomessage": "audio",
    "pttmessage": "audio",
    "voicemessage": "audio",
    # Imagem e vídeo
    "image": "image",
    "imagemessage": "image",
    "video": "image",
    "videomessage": "image",
    # Documentos
    "document": "document",
    "documentmessage": "document",
    # Outros
    "sticker": "sticker",
    "location": "location",
    "contact": "contact",
    "reaction": "reaction",
}


def _extract_phone(chatid: str) -> str:
    """Extrai numero de telefone limpo do chatid do WhatsApp."""
    return chatid.replace("@s.whatsapp.net", "").replace("@g.us", "")


def _map_uazapi_message(msg: dict) -> tuple[str, str | None, str | None, str | None, str | None, str | None]:
    """
    Mapeia o objeto 'message' da UAZAPI para o formato interno.

    Formato UAZAPI:
      - messageType: "Conversation", "ExtendedText", "Audio", "PTT", "Image", "Document", ...
      - text / content: conteudo textual
      - mediaType: mimetype da midia (se houver)
      - base64: conteudo da midia codificado em base64 (se disponivel)
      - url / mediaUrl: URL da midia (se disponivel)
      - messageId / id: ID da mensagem para download via API

    Retorna: (tipo_interno, conteudo, media_url, media_mimetype, media_base64, uazapi_message_id)
    """
    if not msg:
        return "text", None, None, None, None, None

    raw_type = (msg.get("messageType") or "").lower()
    msg_type = _UAZAPI_TYPE_MAP.get(raw_type, "text")

    # Conteudo textual (garante que seja string; UAZAPI pode enviar dict para campos de midia)
    _raw_content = msg.get("text") or msg.get("content") or msg.get("caption")
    content = _raw_content if isinstance(_raw_content, str) else None

    # Mimetype
    media_mimetype = msg.get("mediaType") or msg.get("mimetype") or None

    # URL da midia (alguns setups UAZAPI enviam URL direta; chave pode ser maiuscula)
    media_url = (
        msg.get("url") or msg.get("URL")
        or msg.get("mediaUrl") or msg.get("MediaUrl")
        or msg.get("fileUrl") or msg.get("FileUrl")
        or None
    )

    # Base64 inline (depende da configuracao da instancia UAZAPI)
    media_base64 = msg.get("base64") or msg.get("mediaData") or msg.get("data") or None

    # ID da mensagem para download via API UAZAPI como fallback
    uazapi_message_id = (
        msg.get("messageId")
        or msg.get("id")
        or msg.get("key", {}).get("id")
        or None
    )

    # Log de diagnostico para mensagens de midia (facilita debug de novos payloads)
    if msg_type in ("audio", "image", "document"):
        logger.info(
            "WEBHOOK | Midia recebida | type=%s | keys=%s | has_base64=%s | has_url=%s | msg_id=%s",
            msg_type,
            list(msg.keys()),
            bool(media_base64),
            bool(media_url),
            uazapi_message_id,
        )

    return msg_type, content, media_url, media_mimetype, media_base64, uazapi_message_id


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

    # Mensagens enviadas pelo nosso numero (fromMe)
    if msg.get("fromMe", False):
        # Verifica se foi o agente ou um humano que enviou
        from_me_msg_id = (
            msg.get("messageId")
            or msg.get("id")
            or msg.get("key", {}).get("id")
            or None
        )

        if from_me_msg_id:
            async with async_session() as session:
                row = await session.execute(
                    text("SELECT 1 FROM agent_sent_msg_ids WHERE msg_id = :mid"),
                    {"mid": from_me_msg_id},
                )
                is_agent_message = row.scalar_one_or_none() is not None

            if not is_agent_message:
                # ID desconhecido: humano enviou manualmente → intervencao humana
                lead_chatid = msg.get("chatid") or msg.get("sender_pn", "")
                if not lead_chatid:
                    lead_chatid = msg.get("key", {}).get("remoteJid", "")
                lead_phone = _extract_phone(lead_chatid)

                if lead_phone and "@g.us" not in lead_chatid:
                    async with async_session() as session:
                        existing = await session.execute(
                            select(BlockedNumber).where(BlockedNumber.phone == lead_phone)
                        )
                        if not existing.scalar_one_or_none():
                            session.add(BlockedNumber(
                                phone=lead_phone,
                                reason="intervencao_humana",
                            ))
                            await session.commit()
                            logger.info(
                                "WEBHOOK | Intervencao humana detectada — numero bloqueado | phone=%s",
                                lead_phone,
                            )

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
    msg_type, content, media_url, media_mimetype, media_base64, uazapi_message_id = _map_uazapi_message(msg)

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
        "chat_id": chatid,  # necessario para download de midia via API UAZAPI
        "push_name": push_name,
        "type": msg_type,
        "content": content,
        "media_url": media_url,
        "media_mimetype": media_mimetype,
        "media_base64": media_base64,
        "uazapi_message_id": uazapi_message_id,
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
