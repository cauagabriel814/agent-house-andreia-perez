import uuid
from datetime import timedelta

from src.agent.prompts.reengagement import REENGAGEMENT_24H, REENGAGEMENT_24H_WITH_REGION
from src.agent.tools.uazapi import send_whatsapp_message
from src.db.database import async_session
from src.services.job_service import JobService
from src.services.lead_service import LeadService
from src.utils.logger import logger


async def execute_reengagement_24h(lead_id: str | uuid.UUID, payload: dict | None = None):
    """
    Job: Follow-up 24h apos timeout.

    Envia mensagem personalizada e agenda o proximo passo (reengagement_7d).
    Se o lead tiver respondido antes deste job executar, o job ja teria
    sido cancelado por cancel_pending_by_lead dentro de run_agent.
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        job_svc = JobService(session)

        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning(
                "REENGAGEMENT_24H | Lead nao encontrado | lead_id=%s", lead_id
            )
            return

        name = payload.get("name") or lead.name or "voce"
        region = payload.get("region") or None
        if region:
            msg = REENGAGEMENT_24H_WITH_REGION.format(name=name, region=region)
        else:
            msg = REENGAGEMENT_24H.format(name=name)

        logger.info(
            "REENGAGEMENT_24H | Enviando follow-up | phone=%s | lead_id=%s",
            lead.phone,
            lead_id,
        )
        await send_whatsapp_message(lead.phone, msg)

        # Agendar proximo follow-up em 7 dias
        await job_svc.schedule_after(
            lead_id,
            "reengagement_7d",
            timedelta(days=7),
            payload={"name": name, "region": region},
        )
        logger.info(
            "REENGAGEMENT_24H | Job reengagement_7d agendado | lead_id=%s", lead_id
        )
