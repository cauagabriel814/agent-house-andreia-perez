"""
retorno_9h.py - Job de retorno de contato no proximo dia util as 9h.

Disparado quando um lead entra em contato fora do horario comercial.
O greeting_node agenda este job para o proximo dia util as 9h (fuso Cuiaba).

Se o lead responder antes das 9h (ex: mandou mais mensagens a noite),
o scheduler cancela o job automaticamente via cancel_pending_by_lead.
"""

from src.agent.prompts.greeting import GREETING_RETORNO_9H
from src.agent.tools.uazapi import send_whatsapp_message
from src.db.database import async_session
from src.services.lead_service import LeadService
from src.utils.logger import logger


async def execute_retorno_9h(lead_id: str, payload: dict | None = None):
    """
    Job: Retorno de contato no proximo dia util as 9h.

    Envia mensagem de retorno personalizada com o nome do lead.
    Se o lead ja tiver respondido, o scheduler ja teria cancelado este job.
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)

        if not lead:
            logger.warning(
                "RETORNO_9H | Lead nao encontrado | lead_id=%s", lead_id
            )
            return

        nome = payload.get("nome") or lead.name or "voce"
        msg = GREETING_RETORNO_9H.format(nome=nome)

        logger.info(
            "RETORNO_9H | Enviando retorno 9h | phone=%s | lead_id=%s | nome=%r",
            lead.phone,
            lead_id,
            nome,
        )
        await send_whatsapp_message(lead.phone, msg)
