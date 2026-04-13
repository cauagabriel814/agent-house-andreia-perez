"""
investor_nurture.py - Sequencia de nutricao para leads investidores FRIO.

Agendado pelo fluxo investor apos o lead receber a mensagem de barreira.
Sequencia: Dia 1 → Dia 7 → Dia 15 → Dia 30

  Dia 1  : Boas-vindas + Guia do Mercado (mensagem estatica)
  Dia 7  : Novidades + Dicas (mensagem estatica)
  Dia 15 : Oportunidades Exclusivas (LLM personaliza com perfil do lead)
  Dia 30 : Check-in Personalizado (LLM personaliza com perfil do lead)

IMPORTANTE: _NURTURE_ACTIVE = False
  Os handlers estao desativados ate o conteudo definitivo ser aprovado.
  Para ativar, mude a flag para True e substitua os prompts TODO.

Payload esperado: {
    "phone": str,
    "nome": str,
    "tipo_imovel": str,
    "regiao": str,
    "investimento": str,
}
"""

import uuid

from langchain_openai import ChatOpenAI

from src.agent.prompts.investor import (
    INVESTOR_NURTURE_15D_SYSTEM,
    INVESTOR_NURTURE_1D,
    INVESTOR_NURTURE_30D_SYSTEM,
    INVESTOR_NURTURE_7D,
)
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.db.database import async_session
from src.services.lead_service import LeadService
from src.services.tag_service import TagService
from src.utils.logger import logger

# ---------------------------------------------------------------------------
# Flag global de ativacao
# Mude para True quando o conteudo definitivo estiver aprovado
# ---------------------------------------------------------------------------
_NURTURE_ACTIVE = False


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def execute_investor_nurture_1d(lead_id: str | uuid.UUID, payload: dict | None = None):
    """
    Job: Nutricao Dia 1 — Boas-vindas + Guia do Mercado.
    Mensagem estatica. Ativada quando _NURTURE_ACTIVE = True.
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("INVESTOR_NURTURE_1D | Lead nao encontrado | lead_id=%s", lead_id)
            return

    phone = payload.get("phone") or lead.phone
    nome = payload.get("nome") or lead.name or "voce"
    msg = INVESTOR_NURTURE_1D

    if _NURTURE_ACTIVE:
        logger.info("INVESTOR_NURTURE_1D | Enviando | phone=%s", phone)
        await send_whatsapp_message(phone, msg)
    else:
        logger.info(
            "INVESTOR_NURTURE_1D | Desativado (conteudo pendente) | phone=%s | nome=%s",
            phone,
            nome,
        )


async def execute_investor_nurture_7d(lead_id: str | uuid.UUID, payload: dict | None = None):
    """
    Job: Nutricao Dia 7 — Novidades + Dicas.
    Mensagem estatica. Ativada quando _NURTURE_ACTIVE = True.
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("INVESTOR_NURTURE_7D | Lead nao encontrado | lead_id=%s", lead_id)
            return

    phone = payload.get("phone") or lead.phone
    nome = payload.get("nome") or lead.name or "voce"
    msg = INVESTOR_NURTURE_7D

    if _NURTURE_ACTIVE:
        logger.info("INVESTOR_NURTURE_7D | Enviando | phone=%s", phone)
        await send_whatsapp_message(phone, msg)
    else:
        logger.info(
            "INVESTOR_NURTURE_7D | Desativado (conteudo pendente) | phone=%s | nome=%s",
            phone,
            nome,
        )


async def execute_investor_nurture_15d(lead_id: str | uuid.UUID, payload: dict | None = None):
    """
    Job: Nutricao Dia 15 — Oportunidades Exclusivas.
    LLM gera mensagem personalizada com perfil do lead consultado no banco.
    Ativada quando _NURTURE_ACTIVE = True.
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("INVESTOR_NURTURE_15D | Lead nao encontrado | lead_id=%s", lead_id)
            return

        # Consulta tags atualizadas no banco (barreira pode ter sido salva depois do agendamento)
        tag_svc = TagService(session)
        tags_db = await tag_svc.as_dict(lead_id)

    phone = payload.get("phone") or lead.phone
    nome = payload.get("nome") or lead.name or "voce"
    regiao = tags_db.get("localizacao") or payload.get("regiao") or "Cuiaba"
    investimento = tags_db.get("faixa_valor") or payload.get("investimento") or ""
    barreira = tags_db.get("barreira_frio") or payload.get("barreira") or ""

    if _NURTURE_ACTIVE:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7, api_key=settings.openai_api_key)
        prompt = INVESTOR_NURTURE_15D_SYSTEM.format(
            nome=nome,
            regiao=regiao,
            investimento=investimento,
            barreira=barreira,
        )
        response = await llm.ainvoke(prompt)
        msg = response.content.strip()

        logger.info("INVESTOR_NURTURE_15D | Enviando | phone=%s", phone)
        await send_whatsapp_message(phone, msg)
    else:
        logger.info(
            "INVESTOR_NURTURE_15D | Desativado | phone=%s | nome=%s | regiao=%s | barreira=%s",
            phone,
            nome,
            regiao,
            barreira,
        )


async def execute_investor_nurture_30d(lead_id: str | uuid.UUID, payload: dict | None = None):
    """
    Job: Nutricao Dia 30 — Check-in Personalizado.
    LLM gera mensagem personalizada com perfil do lead consultado no banco.
    Ativada quando _NURTURE_ACTIVE = True.
    """
    payload = payload or {}

    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_id(lead_id)
        if not lead:
            logger.warning("INVESTOR_NURTURE_30D | Lead nao encontrado | lead_id=%s", lead_id)
            return

        # Consulta tags atualizadas no banco
        tag_svc = TagService(session)
        tags_db = await tag_svc.as_dict(lead_id)

    phone = payload.get("phone") or lead.phone
    nome = payload.get("nome") or lead.name or "voce"
    regiao = tags_db.get("localizacao") or payload.get("regiao") or "Cuiaba"
    investimento = tags_db.get("faixa_valor") or payload.get("investimento") or ""
    barreira = tags_db.get("barreira_frio") or payload.get("barreira") or ""

    if _NURTURE_ACTIVE:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7, api_key=settings.openai_api_key)
        prompt = INVESTOR_NURTURE_30D_SYSTEM.format(
            nome=nome,
            regiao=regiao,
            investimento=investimento,
            barreira=barreira,
        )
        response = await llm.ainvoke(prompt)
        msg = response.content.strip()

        logger.info("INVESTOR_NURTURE_30D | Enviando | phone=%s", phone)
        await send_whatsapp_message(phone, msg)
    else:
        logger.info(
            "INVESTOR_NURTURE_30D | Desativado | phone=%s | nome=%s | regiao=%s | barreira=%s",
            phone,
            nome,
            regiao,
            barreira,
        )
