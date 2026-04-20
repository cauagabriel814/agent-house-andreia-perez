"""
runner.py - Ponto de entrada do agente LangGraph.

Responsabilidades:
  1. Carregar (ou criar) lead e conversa no banco
  2. Reconstruir o AgentState a partir dos dados persistidos
  3. Invocar o grafo compilado com a nova mensagem
  4. Persistir o state atualizado de volta no banco
  5. Gerenciar ciclo de timeout: cancelar jobs ao receber mensagem,
     agendar timeout_5min quando agente aguarda resposta (Feature 15)
  6. Registrar last_lead_message_at apenas para mensagens reais do lead,
     permitindo que o scheduler verifique se o lead respondeu (Feature 16)
"""

import time
import uuid
from datetime import timedelta
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.graph import build_graph
from src.agent.state import AgentState
from src.config.settings import settings
from src.db.database import async_session
from src.services.conversation_service import ConversationService
from src.services.job_service import JobService
from src.services.lead_service import LeadService
from src.utils.logger import logger

# Grafo compilado (singleton - criado uma unica vez ao importar o modulo)
_graph = build_graph()


# ---------------------------------------------------------------------------
# Serializacao / desserializacao de mensagens LangChain <-> JSON
# ---------------------------------------------------------------------------

_MSG_TYPE_MAP: dict[str, type[BaseMessage]] = {
    "HumanMessage": HumanMessage,
    "AIMessage": AIMessage,
    "SystemMessage": SystemMessage,
}


def _serialize_messages(messages: list[BaseMessage]) -> list[dict]:
    """Converte mensagens LangChain para dicts serializaveis (JSONB)."""
    result = []
    for msg in messages:
        if isinstance(msg, BaseMessage):
            result.append(
                {
                    "type": msg.__class__.__name__,
                    "content": msg.content,
                    "additional_kwargs": getattr(msg, "additional_kwargs", {}),
                }
            )
    return result


def _deserialize_messages(data: list[dict]) -> list[BaseMessage]:
    """Reconstroi mensagens LangChain a partir de dicts (lidos do JSONB)."""
    messages: list[BaseMessage] = []
    for item in data:
        msg_cls = _MSG_TYPE_MAP.get(item.get("type", ""), HumanMessage)
        messages.append(
            msg_cls(
                content=item.get("content", ""),
                additional_kwargs=item.get("additional_kwargs", {}),
            )
        )
    return messages


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    """
    Prepara o AgentState para armazenamento no banco (JSONB).
    Converte objetos nao-serializaveis (ex.: BaseMessage, UUID) em dicts/strings.
    """
    serialized: dict[str, Any] = {}
    for key, value in state.items():
        if key == "messages":
            serialized[key] = _serialize_messages(value or [])
        elif isinstance(value, uuid.UUID):
            serialized[key] = str(value)
        elif isinstance(value, (str, int, float, bool, dict, list, type(None))):
            serialized[key] = value
        # Descarta valores nao-serializaveis (ex.: objetos SQLAlchemy, closures)
    return serialized


# ---------------------------------------------------------------------------
# Funcao principal - mensagem real do lead
# ---------------------------------------------------------------------------


async def run_agent(
    phone: str,
    message: str,
    message_type: str = "text",
    utm_source: Optional[str] = None,
) -> dict[str, Any]:
    """
    Orquestra uma rodada de processamento do agente Andreia.

    Parametros:
        phone        : Numero de telefone do lead (formato E.164, ex.: 5565999999999)
        message      : Conteudo textual da mensagem (ja processado se for midia)
        message_type : Tipo original (text, audio, image, document, ...)
        utm_source   : Origem da campanha, se disponivel

    Retorna o AgentState final apos a execucao do grafo.
    """
    async with async_session() as session:
        lead_svc = LeadService(session)
        conv_svc = ConversationService(session)
        job_svc = JobService(session)

        # ---------------------------------------------------------------
        # 1. Lead: busca ou cria
        # ---------------------------------------------------------------
        lead, is_new = await lead_svc.get_or_create(phone, utm_source=utm_source)

        if not is_new and not lead.is_recurring:
            await lead_svc.mark_as_recurring(lead)

        # ---------------------------------------------------------------
        # 2. Conversa ativa: busca ou cria
        # ---------------------------------------------------------------
        conv, _ = await conv_svc.get_or_create_active(lead.id)

        # ---------------------------------------------------------------
        # 3. Cancelar jobs pendentes: lead respondeu, timeout nao necessario
        # ---------------------------------------------------------------
        cancelled = await job_svc.cancel_pending_by_lead(lead.id)
        if cancelled > 0:
            logger.info(
                "RUNNER | %d job(s) cancelado(s) por nova mensagem | lead_id=%s",
                cancelled,
                lead.id,
            )

        # ---------------------------------------------------------------
        # 4. Reconstituir AgentState a partir dos dados persistidos
        # ---------------------------------------------------------------
        persisted: dict[str, Any] = conv.graph_state or {}

        # Historico de mensagens LangChain (desserializado do banco)
        previous_messages = _deserialize_messages(persisted.get("messages", []))

        # Adiciona a nova mensagem do usuario ao historico
        current_human_message = HumanMessage(content=message)
        all_messages = previous_messages + [current_human_message]

        state: AgentState = {
            # Identificacao — UUIDs convertidos para string no state
            "phone": phone,
            "lead_id": str(lead.id),
            "conversation_id": str(conv.id),
            # Mensagem atual
            "current_message": message,
            "message_type": message_type,
            "processed_content": message,
            # Contexto do lead (prioriza dados do banco; cai back para state persistido)
            "lead_name": lead.name or persisted.get("lead_name"),
            "lead_email": lead.email or persisted.get("lead_email"),
            "is_recurring": not is_new,
            "classification": lead.classification or persisted.get("classification"),
            # Historico
            "messages": all_messages,
            "conversation_history": persisted.get("conversation_history", []),
            # Tags coletadas (preserva acumulado entre mensagens)
            "tags": persisted.get("tags", {}),
            # Roteamento
            "current_node": conv.current_node or persisted.get("current_node", ""),
            "detected_intent": persisted.get("detected_intent"),
            "previous_intent": persisted.get("previous_intent"),
            # Scoring
            "score_data": persisted.get("score_data"),
            "total_score": persisted.get("total_score"),
            # Controle de fluxo
            # Reseta timeout_count pois o lead esta respondendo ativamente
            "awaiting_response": False,
            "last_question": persisted.get("last_question"),
            "timeout_count": 0,
            "reask_count": persisted.get("reask_count", 0),
            "ai_fallback_count": persisted.get("ai_fallback_count", 0),
            # Metadados
            "business_hours": True,  # verificado dentro do greeting_node (Feature 7)
            "utm_source": utm_source or lead.utm_source,
            # KOMMO CRM — prioriza valor do banco (mais autoritativo)
            "kommo_contact_id": lead.kommo_contact_id or persisted.get("kommo_contact_id"),
            "kommo_lead_id": lead.kommo_lead_id or persisted.get("kommo_lead_id"),
        }

        current_flow = state["current_node"] or "greeting"
        logger.info(
            "RUNNER | Inicio | phone=%s | lead=%s | flow=%s | novo=%s",
            phone,
            lead.id,
            current_flow,
            "sim" if is_new else "nao",
        )

        # ---------------------------------------------------------------
        # 5. Invocar o grafo compilado (com metadata LangSmith)
        # ---------------------------------------------------------------
        langsmith_config = RunnableConfig(
            run_name=f"andreia-{phone[-4:]}-{state['current_node'] or 'start'}",
            metadata={
                "lead_id": str(lead.id),
                "conversation_id": str(conv.id),
                "flow": state["current_node"] or "greeting",
                "classification": lead.classification,
                "model_used": settings.openai_api_key and "gpt" or "unknown",
            },
            tags=[
                f"env:{settings.app_env}",
                f"project:{settings.langchain_project}",
            ],
        )

        _t0 = time.monotonic()
        try:
            result: dict[str, Any] = await _graph.ainvoke(state, langsmith_config)
        except Exception as exc:
            logger.exception(
                "RUNNER | Erro ao invocar o grafo | phone=%s | erro=%s",
                phone,
                str(exc),
            )
            try:
                from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
                from src.agent.tools.uazapi import send_whatsapp_message
                await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
            except Exception:
                logger.exception(
                    "RUNNER | Falha ao enviar mensagem de fallback | phone=%s", phone
                )
            raise
        _response_time_ms = int((time.monotonic() - _t0) * 1000)

        # ---------------------------------------------------------------
        # 6. Persistir o state atualizado no banco
        # ---------------------------------------------------------------
        serializable_state = _serialize_state(result)
        final_node = result.get("current_node", "")

        await conv_svc.update_graph_state(
            conversation=conv,
            graph_state=serializable_state,
            current_node=final_node,
        )

        # Registra timestamp da mensagem real do lead (Feature 16)
        await conv_svc.touch_lead_message(conv)

        # ---------------------------------------------------------------
        # 7. Agendar timeout_5min se o agente esta aguardando resposta
        # ---------------------------------------------------------------
        if result.get("awaiting_response"):
            await job_svc.schedule_after(
                lead.id,
                "timeout_5min",
                timedelta(minutes=5),
                payload={"phone": phone},
            )

        # ---------------------------------------------------------------
        # Log final com tudo que importa
        # ---------------------------------------------------------------
        intent = result.get("detected_intent") or "-"
        classification = result.get("classification") or "-"
        tags_count = len(result.get("tags") or {})
        awaiting = result.get("awaiting_response", False)
        timeout_cnt = result.get("timeout_count", 0)
        tempo_s = _response_time_ms / 1000

        logger.info(
            "RUNNER | Concluido | phone=%s | lead=%s | %s -> %s | "
            "intent=%s | class=%s | tags=%d | awaiting=%s | timeouts=%d | tempo=%.1fs",
            phone,
            lead.id,
            current_flow,
            final_node or "(fim)",
            intent,
            classification,
            tags_count,
            awaiting,
            timeout_cnt,
            tempo_s,
        )

        return result


# ---------------------------------------------------------------------------
# Funcao de timeout - chamada pelo scheduler (Feature 15)
# ---------------------------------------------------------------------------


async def run_agent_for_timeout(lead_id: str | uuid.UUID) -> dict[str, Any] | None:
    """
    Aciona o timeout_node para um lead que nao respondeu.

    Diferente de run_agent, nao adiciona uma HumanMessage ao historico
    (nao e uma mensagem real do lead). O message_type="timeout" faz com
    que route_entry encaminhe diretamente para o timeout_node.

    Retorna o AgentState final ou None se lead/conversa nao for encontrado.
    """
    async with async_session() as session:
        lead_svc = LeadService(session)
        conv_svc = ConversationService(session)

        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("RUNNER_TIMEOUT | Lead nao encontrado | lead_id=%s", lead_id)
            return None

        conv = await conv_svc.get_active_by_lead(lead.id)
        if not conv:
            logger.warning(
                "RUNNER_TIMEOUT | Conversa ativa nao encontrada | lead_id=%s", lead_id
            )
            return None

        persisted: dict[str, Any] = conv.graph_state or {}
        previous_messages = _deserialize_messages(persisted.get("messages", []))

        state: AgentState = {
            # Identificacao — UUIDs como string
            "phone": lead.phone,
            "lead_id": str(lead.id),
            "conversation_id": str(conv.id),
            # Mensagem sintetica de timeout (nao adicionada ao historico como HumanMessage)
            "current_message": "",
            "message_type": "timeout",  # aciona route_entry -> timeout_node
            "processed_content": None,
            # Contexto do lead
            "lead_name": lead.name or persisted.get("lead_name"),
            "lead_email": lead.email or persisted.get("lead_email"),
            "is_recurring": lead.is_recurring,
            "classification": lead.classification or persisted.get("classification"),
            # Historico preservado (sem nova mensagem humana)
            "messages": previous_messages,
            "conversation_history": persisted.get("conversation_history", []),
            # Tags preservadas
            "tags": persisted.get("tags", {}),
            # Roteamento preservado
            "current_node": conv.current_node or persisted.get("current_node", ""),
            "detected_intent": persisted.get("detected_intent"),
            # Scoring preservado
            "score_data": persisted.get("score_data"),
            "total_score": persisted.get("total_score"),
            # Controle de fluxo - preserva timeout_count para logica do timeout_node
            "awaiting_response": persisted.get("awaiting_response", True),
            "last_question": persisted.get("last_question"),
            "timeout_count": persisted.get("timeout_count", 0),
            "reask_count": persisted.get("reask_count", 0),
            # Metadados
            "business_hours": True,
            "utm_source": lead.utm_source,
            # KOMMO CRM
            "kommo_contact_id": lead.kommo_contact_id or persisted.get("kommo_contact_id"),
            "kommo_lead_id": lead.kommo_lead_id or persisted.get("kommo_lead_id"),
        }

        logger.info(
            "RUNNER | Timeout #%d | phone=%s | lead=%s",
            state["timeout_count"],
            lead.phone,
            lead.id,
        )

        langsmith_config = RunnableConfig(
            run_name=f"andreia-timeout-{lead.phone[-4:]}",
            metadata={
                "lead_id": str(lead.id),
                "conversation_id": str(conv.id),
                "flow": "timeout",
                "classification": lead.classification,
                "timeout_count": state["timeout_count"],
            },
            tags=[
                f"env:{settings.app_env}",
                "trigger:timeout",
            ],
        )

        _t0 = time.monotonic()
        try:
            result: dict[str, Any] = await _graph.ainvoke(state, langsmith_config)
        except Exception as exc:
            logger.exception(
                "RUNNER_TIMEOUT | Erro ao invocar grafo | lead_id=%s | erro=%s",
                lead_id,
                str(exc),
            )
            try:
                from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
                from src.agent.tools.uazapi import send_whatsapp_message
                await send_whatsapp_message(lead.phone, TECHNICAL_ERROR_MESSAGE)
            except Exception:
                logger.exception(
                    "RUNNER_TIMEOUT | Falha ao enviar mensagem de fallback | lead_id=%s",
                    lead_id,
                )
            raise
        _response_time_ms = int((time.monotonic() - _t0) * 1000)

        serializable_state = _serialize_state(result)
        final_node = result.get("current_node", "")

        await conv_svc.update_graph_state(
            conversation=conv,
            graph_state=serializable_state,
            current_node=final_node,
        )

        logger.info(
            "RUNNER | Timeout concluido | phone=%s | lead=%s | node=%s | tempo=%.1fs",
            lead.phone,
            lead_id,
            final_node,
            _response_time_ms / 1000,
        )

        return result
