from src.agent.prompts.reengagement import NURTURE_30D, NURTURE_60D, NURTURE_90D
from src.agent.tools.uazapi import send_whatsapp_message
from src.db.database import async_session
from src.services.lead_service import LeadService
from src.utils.logger import logger


async def execute_nurture_30d(lead_id: str, payload: dict | None = None):
    """Job: Nutricao 30 dias - check-in personalizado."""
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("NURTURE_30D | Lead nao encontrado | lead_id=%s", lead_id)
            return

        name = payload.get("name") or lead.name or "voce"
        region = payload.get("region") or "Cuiaba"
        msg = NURTURE_30D.format(name=name, region=region)

        logger.info("NURTURE_30D | Enviando nutricao | phone=%s | lead_id=%s", lead.phone, lead_id)
        await send_whatsapp_message(lead.phone, msg)


async def execute_nurture_60d(lead_id: str, payload: dict | None = None):
    """Job: Nutricao 60 dias - novas oportunidades."""
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("NURTURE_60D | Lead nao encontrado | lead_id=%s", lead_id)
            return

        name = payload.get("name") or lead.name or "voce"
        region = payload.get("region") or "Cuiaba"
        msg = NURTURE_60D.format(name=name, region=region)

        logger.info("NURTURE_60D | Enviando nutricao | phone=%s | lead_id=%s", lead.phone, lead_id)
        await send_whatsapp_message(lead.phone, msg)


async def execute_nurture_90d(lead_id: str, payload: dict | None = None):
    """Job: Nutricao 90 dias - re-qualificacao."""
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("NURTURE_90D | Lead nao encontrado | lead_id=%s", lead_id)
            return

        name = payload.get("name") or lead.name or "voce"
        region = payload.get("region") or "Cuiaba"
        msg = NURTURE_90D.format(name=name, region=region)

        logger.info("NURTURE_90D | Enviando nutricao | phone=%s | lead_id=%s", lead.phone, lead_id)
        await send_whatsapp_message(lead.phone, msg)
