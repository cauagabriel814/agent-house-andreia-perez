import uuid

from sqlalchemy import delete, select

from src.agent.guardrails import INPUT_BLOCKED_MESSAGE, check_input
from src.agent.runner import run_agent
from src.agent.tools.uazapi import send_whatsapp_message
from src.db.database import async_session
from src.db.models.blocked_number import BlockedNumber
from src.db.models.conversation import Conversation
from src.db.models.lead import Lead
from src.db.models.message import Message
from src.db.models.notification import Notification
from src.db.models.scheduled_job import ScheduledJob
from src.db.models.score import LeadScore
from src.db.models.tag import LeadTag
from src.media.processor import process_media
from src.utils.logger import logger

# Tipos de midia que precisam de processamento antes de ir para o agente
_MEDIA_TYPES = {"audio", "image", "document", "spreadsheet", "sticker", "location", "contact"}


async def _reset_lead(phone: str):
    """Remove todos os dados de um lead do banco (conversas, tags, scores, jobs, etc)."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.phone == phone))
        lead = result.scalar_one_or_none()
        if not lead:
            return False

        lead_id = lead.id
        await session.execute(delete(Notification).where(Notification.lead_id == lead_id))
        await session.execute(delete(ScheduledJob).where(ScheduledJob.lead_id == lead_id))
        await session.execute(delete(LeadScore).where(LeadScore.lead_id == lead_id))
        await session.execute(delete(LeadTag).where(LeadTag.lead_id == lead_id))
        await session.execute(delete(Message).where(Message.lead_id == lead_id))
        await session.execute(delete(Conversation).where(Conversation.lead_id == lead_id))
        await session.delete(lead)
        await session.commit()
        logger.info("RESET | Lead removido completamente | phone=%s | lead_id=%s", phone, lead_id)
        return True


async def handle_incoming_message(payload: dict):
    """
    Processa uma mensagem da fila incoming_messages.

    Fluxo:
        1. Extrai campos do payload normalizado (Feature 4)
        2. Se for midia: delega ao media processor (Feature 5)
        3. Passa o conteudo processado para o agente LangGraph (Feature 6)
    """
    phone = payload.get("phone")
    msg_type = payload.get("type")
    message_id = payload.get("message_id")
    content = payload.get("content")
    media_url = payload.get("media_url")
    mimetype = payload.get("media_mimetype")
    media_base64 = payload.get("media_base64")
    uazapi_message_id = payload.get("uazapi_message_id")
    chat_id = payload.get("chat_id", "")
    raw_payload = payload.get("raw_payload", {})
    utm_source = payload.get("utm_source")

    # Verifica blocklist antes de qualquer processamento
    if phone:
        async with async_session() as session:
            result = await session.execute(
                select(BlockedNumber).where(BlockedNumber.phone == phone)
            )
            if result.scalar_one_or_none():
                logger.info("DISPATCHER | Numero bloqueado ignorado | phone=%s", phone)
                return

    # Garante que content seja sempre str ou None (UAZAPI pode enviar dict para midia)
    if isinstance(content, dict):
        content = None

    # Comando #reset: limpa todos os dados do lead e responde
    if isinstance(content, str) and content.strip().lower() == "#reset":
        logger.info("DISPATCHER | Comando #reset | phone=%s", phone)
        removed = await _reset_lead(phone)
        if removed:
            await send_whatsapp_message(phone, "Contexto resetado. Envie uma mensagem para comecar do zero.")
        else:
            await send_whatsapp_message(phone, "Nenhum dado encontrado para resetar.")
        return

    logger.info(
        "DISPATCHER | Mensagem recebida | phone=%s | type=%s | id=%s",
        phone,
        msg_type,
        message_id,
    )

    processed_content = content

    if msg_type in _MEDIA_TYPES:
        # Para location e contact, os dados estruturados vem dentro do raw_payload
        structured_content = None
        if msg_type in ("location", "contact"):
            structured_content = raw_payload.get(msg_type) or raw_payload

        processed_content = await process_media(
            media_type=msg_type,
            media_url=media_url,
            mimetype=mimetype,
            content=structured_content,
            media_base64=media_base64,
            uazapi_message_id=uazapi_message_id,
            chat_id=chat_id,
        )

        logger.info(
            "DISPATCHER | Midia processada | type=%s | preview=%s",
            msg_type,
            (processed_content or "")[:80].replace("\n", " "),
        )
    else:
        logger.info(
            "DISPATCHER | Mensagem de texto | preview=%s",
            str(content)[:80] if content else "(vazio)",
        )

    # Passa mensagem processada para o agente LangGraph
    if not phone:
        logger.warning("DISPATCHER | Mensagem sem telefone ignorada | id=%s", message_id)
        return

    # Guardrail de entrada: verifica se a mensagem é adequada para processamento
    guardrail = await check_input(processed_content or "")
    if not guardrail.allowed:
        logger.info(
            "GUARDRAIL_INPUT | Mensagem bloqueada | phone=%s | categoria=%s | preview=%s",
            phone,
            guardrail.category,
            (processed_content or "")[:80].replace("\n", " "),
        )
        await send_whatsapp_message(phone, INPUT_BLOCKED_MESSAGE)
        return

    logger.info("DISPATCHER | Enviando para agente | phone=%s | type=%s", phone, msg_type)
    await run_agent(
        phone=phone,
        message=processed_content or "",
        message_type=msg_type or "text",
        utm_source=utm_source,
    )
