from src.agent.prompts.follow_up import REMINDER_24H_VISIT, REMINDER_24H_VISIT_WITH_DETAILS
from src.agent.tools.uazapi import send_whatsapp_message
from src.db.database import async_session
from src.services.lead_service import LeadService
from src.utils.logger import logger


async def execute_reminder_24h(lead_id: str, payload: dict | None = None):
    """
    Job: Lembrete de visita agendada 24h antes.

    Enviado para o lead quando ele agendou uma visita a um imovel.
    Se o payload contiver horario e endereco, inclui os detalhes na mensagem.

    Payload esperado: {
        "name": str,
        "visit_time": str (opcional),   ex: "14h00"
        "property_address": str (opcional), ex: "Rua das Flores, 123 - Jardim Italia"
    }
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("REMINDER_24H | Lead nao encontrado | lead_id=%s", lead_id)
            return

        name = payload.get("name") or lead.name or "voce"
        visit_time = payload.get("visit_time")
        property_address = payload.get("property_address")

        if visit_time and property_address:
            msg = REMINDER_24H_VISIT_WITH_DETAILS.format(
                name=name,
                visit_time=visit_time,
                property_address=property_address,
            )
        else:
            msg = REMINDER_24H_VISIT.format(name=name)

        logger.info(
            "REMINDER_24H | Enviando lembrete visita | phone=%s | lead_id=%s",
            lead.phone,
            lead_id,
        )
        await send_whatsapp_message(lead.phone, msg)
