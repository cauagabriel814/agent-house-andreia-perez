from datetime import timedelta

from langchain_core.messages import AIMessage

from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
from src.agent.prompts.reengagement import TIMEOUT_MESSAGE
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.db.database import async_session
from src.services.job_service import JobService
from src.services.kommo_service import KommoService
from src.services.tag_service import TagService
from src.utils.logger import logger


async def timeout_node(state: AgentState) -> dict:
    """
    Node: Timeout - gerencia inatividade do lead.

    Fluxo:
        timeout_count == 0  (job timeout_5min disparou):
            Envia "[Nome], esta ai?" e agenda verificacao de 30 min no banco.
        timeout_count == 1  (job timeout_30min disparou):
            Adiciona tag 'lead_timeout', sync KOMMO e agenda job de 7 dias.
        timeout_count >= 2  (job inativo_7d disparou):
            Adiciona tag 'lead_inativo' e sync KOMMO.
    """
    phone = state["phone"]
    try:
        return await _timeout_node_impl(state)
    except Exception as exc:
        logger.exception("TIMEOUT | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("TIMEOUT | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": "timeout",
            "timeout_count": state.get("timeout_count", 0),
            "awaiting_response": state.get("awaiting_response", False),
        }


async def _timeout_node_impl(state: AgentState) -> dict:
    phone = state["phone"]
    lead_id = state.get("lead_id")
    timeout_count = state.get("timeout_count", 0)
    lead_name = state.get("lead_name") or "você"
    tags = dict(state.get("tags") or {})
    region = tags.get("localizacao", "Cuiaba")
    kommo_contact_id = state.get("kommo_contact_id")
    kommo_lead_id = state.get("kommo_lead_id")

    kommo = KommoService()

    # ------------------------------------------------------------------
    # Primeiro timeout (5 min) - sinaliza que o lead parou de responder
    # ------------------------------------------------------------------
    if timeout_count == 0:
        msg = TIMEOUT_MESSAGE.format(name=lead_name)
        logger.info("TIMEOUT | Primeiro timeout (5min) | phone=%s | lead_id=%s", phone, lead_id)
        await send_whatsapp_message(phone, msg)

        if lead_id:
            async with async_session() as session:
                job_svc = JobService(session)
                await job_svc.schedule_after(
                    lead_id,
                    "timeout_30min",
                    timedelta(minutes=30),
                    payload={"name": lead_name, "region": region},
                )
            logger.info("TIMEOUT | Job timeout_30min agendado | lead_id=%s", lead_id)

        return {
            "current_node": "timeout",
            "timeout_count": 1,
            "awaiting_response": True,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "messages": [AIMessage(content=msg)],
        }

    # ------------------------------------------------------------------
    # Segundo timeout (30 min) - lead inativo, agenda 7 dias
    # ------------------------------------------------------------------
    if timeout_count == 1:
        tags["lead_timeout"] = "true"
        logger.info(
            "TIMEOUT | Segundo timeout (30min), lead inativo | phone=%s | lead_id=%s", phone, lead_id
        )

        if lead_id:
            async with async_session() as session:
                tag_svc = TagService(session)
                job_svc = JobService(session)
                await tag_svc.set_tag(lead_id, "lead_timeout", "true")
                await job_svc.schedule_after(
                    lead_id,
                    "reengagement_24h",
                    timedelta(hours=24),
                    payload={"name": lead_name, "region": region},
                )
            logger.info(
                "TIMEOUT | Tag lead_timeout e job reengagement_24h agendados | lead_id=%s", lead_id
            )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)

        return {
            "current_node": "timeout",
            "timeout_count": 2,
            "awaiting_response": False,
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
        }

    # ------------------------------------------------------------------
    # Terceiro timeout (7 dias) - lead completamente inativo
    # ------------------------------------------------------------------
    tags["lead_inativo"] = "true"
    logger.info(
        "TIMEOUT | Terceiro timeout (7 dias), lead inativo permanente | phone=%s | lead_id=%s",
        phone,
        lead_id,
    )

    if lead_id:
        async with async_session() as session:
            tag_svc = TagService(session)
            await tag_svc.set_tag(lead_id, "lead_inativo", "true")
        logger.info("TIMEOUT | Tag lead_inativo salva | lead_id=%s", lead_id)

    await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)

    return {
        "current_node": "timeout",
        "timeout_count": 3,
        "awaiting_response": False,
        "tags": tags,
        "kommo_contact_id": kommo_contact_id,
        "kommo_lead_id": kommo_lead_id,
    }
