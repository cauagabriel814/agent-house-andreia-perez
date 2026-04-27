from contextvars import ContextVar

from sqlalchemy import text

from src.agent.guardrails import check_output
from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
from src.db.database import async_session
from src.services.uazapi import UazapiService
from src.utils.logger import logger

# Quando não-None, mensagens são capturadas aqui em vez de enviadas ao WhatsApp (modo teste).
test_capture: ContextVar[list[str] | None] = ContextVar("test_capture", default=None)


def _extract_uazapi_msg_id(response: dict) -> str | None:
    """Extrai o messageId do response da UAZAPI apos envio (tenta multiplos campos)."""
    return (
        response.get("id")
        or response.get("messageId")
        or (response.get("message") or {}).get("key", {}).get("id")
        or (response.get("key") or {}).get("id")
        or None
    )


async def _store_agent_msg_id(msg_id: str) -> None:
    """Persiste o ID da mensagem enviada pelo agente para deteccao de intervencao humana."""
    try:
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO agent_sent_msg_ids (msg_id) VALUES (:msg_id) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"msg_id": msg_id},
            )
            await session.commit()
    except Exception as exc:
        logger.warning("UAZAPI | Falha ao salvar msg_id | msg_id=%s | erro=%s", msg_id, exc)


async def send_whatsapp_message(phone: str, message: str) -> dict:
    """Tool: Envia mensagem via WhatsApp (UAZAPI) com guardrail de saída."""
    guardrail = await check_output(message)
    if not guardrail.allowed:
        logger.warning(
            "GUARDRAIL_OUTPUT | Mensagem bloqueada antes do envio | phone=%s | categoria=%s | preview=%s",
            phone,
            guardrail.category,
            message[:200].replace("\n", " "),
        )
        captured = test_capture.get()
        if captured is not None:
            captured.append(f"[BLOQUEADO] {TECHNICAL_ERROR_MESSAGE}")
            return {"status": "test_captured"}
        service = UazapiService()
        result = await service.send_text_message(phone, TECHNICAL_ERROR_MESSAGE)
        msg_id = _extract_uazapi_msg_id(result)
        if msg_id:
            await _store_agent_msg_id(msg_id)
        return result

    captured = test_capture.get()
    if captured is not None:
        captured.append(message)
        logger.info("TEST_MODE | Mensagem capturada | phone=%s | preview=%s", phone, message[:60])
        return {"status": "test_captured"}

    service = UazapiService()
    result = await service.send_text_message(phone, message)
    msg_id = _extract_uazapi_msg_id(result)
    if msg_id:
        await _store_agent_msg_id(msg_id)
    return result
