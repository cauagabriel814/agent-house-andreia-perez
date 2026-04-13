import uuid
from datetime import timedelta

from src.agent.prompts.reengagement import REENGAGEMENT_7D
from src.agent.tools.uazapi import send_whatsapp_message
from src.db.database import async_session
from src.services.job_service import JobService
from src.services.lead_service import LeadService
from src.services.tag_service import TagService
from src.utils.logger import logger


async def execute_reengagement_7d(lead_id: str | uuid.UUID, payload: dict | None = None):
    """
    Job: Follow-up 7 dias apos timeout.

    Se o lead nao respondeu, envia nova mensagem, adiciona tag 'lead_inativo'
    e agenda a sequencia de nutricao de longo prazo (30/60/90 dias).
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        job_svc = JobService(session)
        tag_svc = TagService(session)

        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning(
                "REENGAGEMENT_7D | Lead nao encontrado | lead_id=%s", lead_id
            )
            return

        name = payload.get("name") or lead.name or "voce"
        region = payload.get("region") or "Cuiaba"
        msg = REENGAGEMENT_7D.format(name=name, region=region)

        logger.info(
            "REENGAGEMENT_7D | Enviando follow-up | phone=%s | lead_id=%s",
            lead.phone,
            lead_id,
        )
        await send_whatsapp_message(lead.phone, msg)

        # Marcar lead como inativo
        await tag_svc.set_tag(lead_id, "lead_inativo", "true")
        logger.info("REENGAGEMENT_7D | Tag lead_inativo adicionada | lead_id=%s", lead_id)

        # Agendar sequencia de nutricao de longo prazo
        nurture_payload = {"name": name, "region": region}

        await job_svc.schedule_after(lead_id, "nurture_30d", timedelta(days=30), nurture_payload)
        await job_svc.schedule_after(lead_id, "nurture_60d", timedelta(days=60), nurture_payload)
        await job_svc.schedule_after(lead_id, "nurture_90d", timedelta(days=90), nurture_payload)

        logger.info(
            "REENGAGEMENT_7D | Sequencia nurture 30/60/90d agendada | lead_id=%s", lead_id
        )
