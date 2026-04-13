import uuid

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
from src.agent.prompts.greeting import (
    GREETING_NEW_LEAD,
    GREETING_OUT_OF_HOURS,
    GREETING_RECURRING_LEAD,
    GREETING_SMART_SYSTEM,
    GREETING_SMART_USER,
)
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.db.database import async_session
from src.services.job_service import JobService
from src.services.kommo_service import KommoService
from src.services.lead_service import LeadService
from src.services.tag_service import TagService
from src.utils.datetime_utils import is_business_hours, next_business_9h
from src.utils.logger import logger


def _build_interest_from_tags(tags: dict[str, str]) -> str | None:
    """
    Deriva o interesse principal do lead a partir das tags historicas.
    Retorna None se nao houver dados suficientes para mencionar o interesse.
    """
    if "proprietario_venda" in tags:
        return "venda de imovel"
    if "proprietario_locacao" in tags:
        return "locacao de imovel"
    if "lead_permuta" in tags:
        return "permuta de imovel"
    if "investidor_yield" in tags or "investidor_valorizacao" in tags:
        tipo = tags.get("lead_tipo_imovel", "imovel")
        return f"investimento em {tipo}"
    if "lead_tipo_imovel" in tags:
        return tags["lead_tipo_imovel"]
    return None


async def _sync_kommo_on_greeting(
    phone: str,
    lead_id: str | uuid.UUID | None,
    lead_name: str | None,
    kommo_contact_id: str | None,
    kommo_lead_id: str | None,
) -> tuple[str | None, str | None]:
    """
    Cria/encontra contato e negocio no KOMMO quando um lead chega.
    Retorna (kommo_contact_id, kommo_lead_id) atualizados.
    Falhas sao silenciosas.
    """
    kommo = KommoService()
    if not kommo.is_enabled():
        return kommo_contact_id, kommo_lead_id

    # Ja tem IDs persistidos — nao recriar
    if kommo_contact_id and kommo_lead_id:
        return kommo_contact_id, kommo_lead_id

    contact, _ = await kommo.get_or_create_contact(phone, name=lead_name)
    if not contact:
        return kommo_contact_id, kommo_lead_id

    new_contact_id = str(contact["id"])
    # Cria o deal sem status_id para evitar NotSupportedChoice — KOMMO coloca
    # no primeiro estágio do pipeline automaticamente. Em seguida tenta mover
    # para lead_novo via update_lead_stage (falha é silenciosa).
    deal = await kommo.create_lead_deal(
        contact_id=new_contact_id,
        phone=phone,
        pipeline_id=settings.kommo_pipeline_id or None,
    )
    new_lead_id = str(deal["id"]) if deal else kommo_lead_id

    # Tentar mover para o estágio lead_novo após criação
    if new_lead_id and new_lead_id != kommo_lead_id:
        stage_id = settings.kommo_stage_map_dict.get("lead_novo")
        if stage_id:
            await kommo.update_lead_stage(new_lead_id, stage_id)

    # Persistir IDs no banco (somente quando ambos foram obtidos com sucesso)
    if lead_id and new_contact_id and new_lead_id:
        async with async_session() as session:
            lead_svc = LeadService(session)
            lead_obj = await lead_svc.get_by_id(lead_id)
            if lead_obj:
                await lead_svc.save_kommo_ids(lead_obj, new_contact_id, new_lead_id)

    logger.info(
        "GREETING | KOMMO | contato=%s negocio=%s | phone=%s",
        new_contact_id,
        new_lead_id,
        phone,
    )
    return new_contact_id, new_lead_id


async def greeting_node(state: AgentState) -> dict:
    """
    Node: Saudacao + verificacao de horario comercial.

    Fluxo:
      - Fora do horario  -> mensagem padrao + tag lead_fora_horario -> END
      - Lead novo        -> saudacao de boas-vindas -> END
      - Lead recorrente  -> saudacao personalizada com nome/interesse/regiao -> END

    Em todos os casos define current_node = "greeting" para que, na proxima
    mensagem, route_entry encaminhe para active_listen.
    """
    phone = state["phone"]
    try:
        return await _greeting_node_impl(state)
    except Exception as exc:
        logger.exception("GREETING | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("GREETING | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", ""),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
        }


async def _greeting_node_impl(state: AgentState) -> dict:
    phone = state["phone"]
    lead_id = state.get("lead_id")
    is_recurring = state.get("is_recurring", False)
    lead_name = state.get("lead_name")
    tags = dict(state.get("tags") or {})

    # Se há fluxo ativo, extrai contexto da mensagem recebida agora.
    # Isso captura respostas que o lead enviou durante/após um timeout
    # (ex: "Segurança 24h" chegou enquanto current_node era "timeout").
    last_question_active = state.get("last_question") or ""
    _FLOW_PREFIXES = ("buyer_", "specific_", "launch_", "investor_", "sale_", "rental_", "exchange_")
    if any(last_question_active.startswith(p) for p in _FLOW_PREFIXES):
        from src.utils.context_extractor import extract_context_from_message
        current_message = state.get("current_message", "")
        processed_content = state.get("processed_content")
        effective_message = processed_content or current_message
        if effective_message.strip():
            tags = await extract_context_from_message(effective_message, tags, lead_id)

    # ------------------------------------------------------------------
    # 1. Verificar horario comercial
    # ------------------------------------------------------------------
    in_business_hours = is_business_hours()

    # ------------------------------------------------------------------
    # 2. Fora do horario
    # ------------------------------------------------------------------
    if not in_business_hours:
        logger.info("GREETING | Fora do horario comercial | phone=%s", phone)

        await send_whatsapp_message(phone, GREETING_OUT_OF_HOURS)

        # Persiste tag no banco e atualiza dict de tags do state
        tags_update = dict(state.get("tags") or {})
        tags_update["lead_fora_horario"] = "true"

        if lead_id:
            async with async_session() as session:
                tag_svc = TagService(session)
                await tag_svc.set_tag(lead_id, "lead_fora_horario", "true")

            # Agendar retorno automatico no proximo dia util as 9h
            scheduled_for = next_business_9h()
            async with async_session() as session:
                job_svc = JobService(session)
                await job_svc.create_job(
                    lead_id=lead_id,
                    job_type="retorno_9h",
                    scheduled_for=scheduled_for,
                    payload={"nome": state.get("lead_name") or ""},
                )
            logger.info(
                "GREETING | Job retorno_9h agendado para %s | lead_id=%s",
                scheduled_for.isoformat(),
                lead_id,
            )

        logger.info("GREETING | Tag lead_fora_horario salva | lead_id=%s", lead_id)

        kommo_contact_id, kommo_lead_id = await _sync_kommo_on_greeting(
            phone, lead_id, lead_name,
            state.get("kommo_contact_id"),
            state.get("kommo_lead_id"),
        )
        kommo = KommoService()
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags_update)

        return {
            "business_hours": False,
            "current_node": "greeting",
            "tags": tags_update,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "messages": [AIMessage(content=GREETING_OUT_OF_HOURS)],
        }

    # ------------------------------------------------------------------
    # 3. Dentro do horario - lead recorrente
    # ------------------------------------------------------------------
    if is_recurring and lead_id:
        async with async_session() as session:
            tag_svc = TagService(session)
            historical_tags = await tag_svc.as_dict(lead_id)

        name = lead_name or "voce"
        interest = _build_interest_from_tags(historical_tags)
        region = historical_tags.get("localizacao")

        parts = [GREETING_RECURRING_LEAD[0].format(name=name)]
        if interest and region:
            parts.append(GREETING_RECURRING_LEAD[1].format(interest=interest, region=region))
        parts.append(GREETING_RECURRING_LEAD[2])

        message = parts

        logger.info(
            "GREETING | Lead recorrente | phone=%s | name=%s | interest=%s | region=%s",
            phone,
            name,
            interest,
            region,
        )

    # ------------------------------------------------------------------
    # 4. Dentro do horario - lead novo (saudacao contextual via LLM)
    # ------------------------------------------------------------------
    else:
        logger.info("GREETING | Lead novo | phone=%s", phone)
        current_message = state.get("current_message", "")
        processed_content = state.get("processed_content")
        first_message = processed_content or current_message

        # Detecta se a mensagem tem intenção clara para decidir o tipo de saudação
        from src.agent.edges.conditions import _message_has_intent
        has_intent = _message_has_intent(first_message)

        if has_intent:
            # Mensagem com intenção: saudação curta via LLM (o fluxo continua no mesmo ciclo)
            smart_greeting = None
            if first_message and first_message.strip():
                try:
                    llm = ChatOpenAI(
                        model="gpt-4o-mini",
                        temperature=0.4,
                        api_key=settings.openai_api_key,
                        timeout=15,
                    )
                    response = await llm.ainvoke([
                        {"role": "system", "content": GREETING_SMART_SYSTEM},
                        {"role": "user", "content": GREETING_SMART_USER.format(message=first_message)},
                    ])
                    smart_greeting = response.content.strip()
                except Exception:
                    logger.warning(
                        "GREETING | Falha ao gerar saudacao LLM, usando padrao | phone=%s", phone
                    )
            message = smart_greeting or "Olá! Aqui é a Marina da Casa Andreia Perez! 😊"
            logger.info("GREETING | Saudacao curta (tem intencao) | phone=%s", phone)
        else:
            # Saudação pura: usa template completo com "Me conta, como posso te ajudar?"
            message = GREETING_NEW_LEAD
            logger.info("GREETING | Template completo (sem intencao) | phone=%s", phone)

    if isinstance(message, list):
        for part in message:
            await send_whatsapp_message(phone, part)
        ai_content = "\n\n".join(message)
    else:
        await send_whatsapp_message(phone, message)
        ai_content = message

    kommo_contact_id, kommo_lead_id = await _sync_kommo_on_greeting(
        phone, lead_id, lead_name,
        state.get("kommo_contact_id"),
        state.get("kommo_lead_id"),
    )

    return {
        "business_hours": True,
        "current_node": "greeting",
        "awaiting_response": True,
        "tags": tags,
        "kommo_contact_id": kommo_contact_id,
        "kommo_lead_id": kommo_lead_id,
        "messages": [AIMessage(content=ai_content)],
    }
