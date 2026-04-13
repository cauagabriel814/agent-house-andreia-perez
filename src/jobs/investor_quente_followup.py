"""
investor_quente_followup.py - Job de follow-up para leads QUENTE sem resposta.

Agendado pelo fluxo de investidor quando INVESTOR_QUENTE_OPCOES e enviado
e o lead nao responde em 10 minutos.

Fluxo:
  1. Envia INVESTOR_QUENTE_FOLLOWUP (1 vez apenas)
  2. Agenda timeout_5min para o proximo check (timeout generico assume a partir dai)

Payload esperado: {"phone": str, "nome": str}
"""

from datetime import timedelta

from src.agent.prompts.investor import INVESTOR_QUENTE_FOLLOWUP
from src.agent.tools.uazapi import send_whatsapp_message
from src.db.database import async_session
from src.services.job_service import JobService
from src.services.lead_service import LeadService
from src.utils.logger import logger


async def execute_investor_quente_followup(lead_id: str, payload: dict | None = None):
    """
    Job: Follow-up para lead investidor QUENTE que nao respondeu em 10min.

    Envia a mensagem de follow-up UMA UNICA VEZ e agenda timeout_5min
    para que o sistema generico de timeout assuma a partir dai.
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        job_svc = JobService(session)

        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning(
                "INVESTOR_QUENTE_FOLLOWUP | Lead nao encontrado | lead_id=%s", lead_id
            )
            return

        nome = payload.get("nome") or lead.name or "voce"
        msg = INVESTOR_QUENTE_FOLLOWUP.format(nome=nome)

        logger.info(
            "INVESTOR_QUENTE_FOLLOWUP | Enviando follow-up quente | phone=%s | lead_id=%s",
            lead.phone,
            lead_id,
        )
        await send_whatsapp_message(lead.phone, msg)

        # Agendar timeout_5min: a partir daqui o timeout generico assume
        await job_svc.schedule_after(
            lead_id,
            "timeout_5min",
            timedelta(minutes=5),
            payload={"phone": lead.phone},
        )
        logger.info(
            "INVESTOR_QUENTE_FOLLOWUP | timeout_5min agendado apos follow-up | lead_id=%s",
            lead_id,
        )
