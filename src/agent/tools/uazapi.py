from contextvars import ContextVar

from src.agent.guardrails import check_output
from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
from src.services.uazapi import UazapiService
from src.utils.logger import logger

# Quando não-None, mensagens são capturadas aqui em vez de enviadas ao WhatsApp (modo teste).
test_capture: ContextVar[list[str] | None] = ContextVar("test_capture", default=None)


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
        return await service.send_text_message(phone, TECHNICAL_ERROR_MESSAGE)

    captured = test_capture.get()
    if captured is not None:
        captured.append(message)
        logger.info("TEST_MODE | Mensagem capturada | phone=%s | preview=%s", phone, message[:60])
        return {"status": "test_captured"}

    service = UazapiService()
    return await service.send_text_message(phone, message)
