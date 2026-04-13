import uuid

from src.agent.prompts.follow_up import FOLLOW_UP_24H_LAUNCH, FOLLOW_UP_48H_RENTAL
from src.agent.tools.uazapi import send_whatsapp_message
from src.db.database import async_session
from src.services.lead_service import LeadService
from src.utils.logger import logger


async def execute_follow_up_48h(lead_id: str | uuid.UUID, payload: dict | None = None):
    """
    Job: Follow-up locacao 48h apos envio da proposta de parceria.

    Agendado pelo fluxo de Locacao (Feature 11) quando o proprietario
    recebe a proposta por email. Verifica interesse e abre espaco para duvidas.

    Payload esperado: {"name": str}
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("FOLLOW_UP_48H | Lead nao encontrado | lead_id=%s", lead_id)
            return

        name = payload.get("name") or lead.name or "voce"
        msg = FOLLOW_UP_48H_RENTAL.format(name=name)

        logger.info(
            "FOLLOW_UP_48H | Enviando follow-up locacao | phone=%s | lead_id=%s",
            lead.phone,
            lead_id,
        )
        await send_whatsapp_message(lead.phone, msg)


async def execute_follow_up_24h(lead_id: str | uuid.UUID, payload: dict | None = None):
    """
    Job: Follow-up lancamento morno 24h apos envio de material completo.

    Agendado pelo fluxo de Lancamento (Feature 14) para leads com
    score entre 60-84 pts que receberam material de apresentacao.

    Payload esperado: {"name": str, "property": str}
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("FOLLOW_UP_24H | Lead nao encontrado | lead_id=%s", lead_id)
            return

        name = payload.get("name") or lead.name or "voce"
        property_name = payload.get("property") or "empreendimento"
        msg = FOLLOW_UP_24H_LAUNCH.format(name=name, property=property_name)

        logger.info(
            "FOLLOW_UP_24H | Enviando follow-up lancamento | phone=%s | lead_id=%s",
            lead.phone,
            lead_id,
        )
        await send_whatsapp_message(lead.phone, msg)
