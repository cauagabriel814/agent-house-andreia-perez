"""
scheduler.py - Loop principal de execucao de jobs agendados.

Arquitetura (Feature 16):
  - Roda a cada 60 segundos buscando jobs pendentes no banco
  - ANTES de executar: verifica se o lead respondeu desde que o job foi criado
    (usando last_lead_message_at da conversa vs. job.created_at)
  - Se respondeu: pula o job (o lead retomou o fluxo normalmente)
  - Se nao respondeu: executa o job e marca como 'executed'
  - Cada job e executado em uma task asyncio independente

Tipos de jobs suportados:
  timeout_5min / timeout_30min  -> run_agent_for_timeout (Feature 15)
  reengagement_24h              -> execute_reengagement_24h
  reengagement_7d               -> execute_reengagement_7d
  nurture_30d/60d/90d           -> execute_nurture_*
  follow_up_48h                 -> execute_follow_up_48h (locacao)
  follow_up_24h                 -> execute_follow_up_24h (lancamento morno)
  reminder_24h_before           -> execute_reminder_24h (visita agendada)
  retorno_9h                    -> execute_retorno_9h (fora do horario)
"""

import asyncio
from datetime import timezone

from src.agent.runner import run_agent_for_timeout
from src.db.database import async_session
from src.db.models.scheduled_job import ScheduledJob
from src.jobs.follow_up_48h import execute_follow_up_24h, execute_follow_up_48h
from src.jobs.investor_nurture import (
    execute_investor_nurture_1d,
    execute_investor_nurture_7d,
    execute_investor_nurture_15d,
    execute_investor_nurture_30d,
)
from src.jobs.investor_quente_followup import execute_investor_quente_followup
from src.jobs.nurture_long import execute_nurture_30d, execute_nurture_60d, execute_nurture_90d
from src.jobs.reengagement_24h import execute_reengagement_24h
from src.jobs.reengagement_7d import execute_reengagement_7d
from src.jobs.reminder_24h import execute_reminder_24h
from src.jobs.retorno_9h import execute_retorno_9h
from src.services.conversation_service import ConversationService
from src.services.job_service import JobService
from src.utils.logger import logger

# Task do scheduler (singleton)
_scheduler_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Verificacao: lead respondeu desde que o job foi criado?
# ---------------------------------------------------------------------------


async def _lead_responded_since_job(job: ScheduledJob) -> bool:
    """
    Retorna True se o lead enviou uma mensagem REAL apos o job ser criado.

    Usa last_lead_message_at da conversa, que so e atualizado por run_agent
    (mensagens reais do lead), nunca por run_agent_for_timeout.

    Isso evita executar jobs quando o lead ja voltou a interagir — especialmente
    em race conditions onde cancel_pending_by_lead e o scheduler correm juntos.
    """
    async with async_session() as session:
        conv_svc = ConversationService(session)
        conv = await conv_svc.get_active_by_lead(job.lead_id)
        if not conv or not conv.last_lead_message_at:
            return False

        lead_ts = conv.last_lead_message_at
        job_ts = job.created_at

        # Normalizar timezone para comparacao segura (naive vs aware)
        if lead_ts.tzinfo is None:
            lead_ts = lead_ts.replace(tzinfo=timezone.utc)
        if job_ts.tzinfo is None:
            job_ts = job_ts.replace(tzinfo=timezone.utc)

        return lead_ts > job_ts


# ---------------------------------------------------------------------------
# Dispatcher de jobs por tipo
# ---------------------------------------------------------------------------


async def _execute_job(job: ScheduledJob) -> None:
    """
    Executa um job pelo tipo apos verificar se o lead nao respondeu.

    Se o lead respondeu desde que o job foi criado, o job e ignorado.
    """
    lead_id = job.lead_id
    payload = job.payload or {}
    job_type = job.job_type

    # Verificar se o lead ja respondeu (safety net para race conditions)
    try:
        if await _lead_responded_since_job(job):
            logger.info(
                "SCHEDULER | Job ignorado: lead respondeu apos agendamento | "
                "job_type=%s | lead_id=%s | job_id=%s",
                job_type,
                lead_id,
                job.id,
            )
            return
    except Exception:
        logger.exception(
            "SCHEDULER | Erro ao verificar resposta do lead | job_id=%s", job.id
        )

    try:
        if job_type in ("timeout_5min", "timeout_30min", "inativo_7d"):
            await run_agent_for_timeout(lead_id)

        elif job_type == "reengagement_24h":
            await execute_reengagement_24h(lead_id, payload)

        elif job_type == "reengagement_7d":
            await execute_reengagement_7d(lead_id, payload)

        elif job_type == "nurture_30d":
            await execute_nurture_30d(lead_id, payload)

        elif job_type == "nurture_60d":
            await execute_nurture_60d(lead_id, payload)

        elif job_type == "nurture_90d":
            await execute_nurture_90d(lead_id, payload)

        elif job_type == "follow_up_48h":
            await execute_follow_up_48h(lead_id, payload)

        elif job_type == "follow_up_24h":
            await execute_follow_up_24h(lead_id, payload)

        elif job_type == "investor_quente_followup_10min":
            await execute_investor_quente_followup(lead_id, payload)

        elif job_type == "investor_nurture_1d":
            await execute_investor_nurture_1d(lead_id, payload)

        elif job_type == "investor_nurture_7d":
            await execute_investor_nurture_7d(lead_id, payload)

        elif job_type == "investor_nurture_15d":
            await execute_investor_nurture_15d(lead_id, payload)

        elif job_type == "investor_nurture_30d":
            await execute_investor_nurture_30d(lead_id, payload)

        elif job_type == "reminder_24h_before":
            await execute_reminder_24h(lead_id, payload)

        elif job_type == "retorno_9h":
            await execute_retorno_9h(lead_id, payload)

        else:
            logger.warning(
                "SCHEDULER | Tipo de job nao reconhecido | job_type=%s | lead_id=%s",
                job_type,
                lead_id,
            )

    except Exception:
        logger.exception(
            "SCHEDULER | Erro ao executar job | job_type=%s | lead_id=%s | job_id=%s",
            job_type,
            lead_id,
            job.id,
        )


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------


async def run_scheduler_loop(interval_seconds: int = 60) -> None:
    """
    Loop principal do scheduler — roda a cada N segundos.

    Para cada ciclo:
      1. Busca jobs pendentes com scheduled_for <= NOW()
      2. Marca cada job como 'executed' antes de disparar (evita reprocessamento)
      3. Dispara _execute_job em background (nao bloqueia o loop)
    """
    logger.info("SCHEDULER | Loop iniciado | intervalo=%ds", interval_seconds)

    while True:
        try:
            async with async_session() as session:
                service = JobService(session)
                pending_jobs = await service.get_pending_jobs()

                if pending_jobs:
                    logger.info("SCHEDULER | Processando %d job(s) pendente(s)", len(pending_jobs))
                    for job in pending_jobs:
                        await service.mark_executed(job)
                        payload_preview = str(job.payload or {})[:100]
                        logger.info(
                            "SCHEDULER | Executando: %s | lead_id=%s | job_id=%s | payload=%s",
                            job.job_type,
                            job.lead_id,
                            job.id,
                            payload_preview,
                        )
                        asyncio.create_task(_execute_job(job))
                else:
                    logger.debug("SCHEDULER | Nenhum job pendente")

        except Exception:
            logger.exception("SCHEDULER | Erro no loop do scheduler")

        await asyncio.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# Controle do ciclo de vida
# ---------------------------------------------------------------------------


async def start_scheduler(interval_seconds: int = 60) -> asyncio.Task:
    """Inicia o scheduler como background task."""
    global _scheduler_task
    _scheduler_task = asyncio.create_task(run_scheduler_loop(interval_seconds))
    logger.info("SCHEDULER | Scheduler iniciado")
    return _scheduler_task


async def stop_scheduler() -> None:
    """Para o scheduler de forma segura."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None
        logger.info("SCHEDULER | Scheduler parado")


def is_scheduler_running() -> bool:
    """Retorna True se o scheduler esta ativo."""
    return _scheduler_task is not None and not _scheduler_task.done()
