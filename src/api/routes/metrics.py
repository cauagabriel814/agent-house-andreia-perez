"""
metrics.py - Dashboard de KPIs do agente Andreia (Feature 18).

Endpoint: GET /metrics
Retorna metricas agregadas do banco de dados para monitoramento operacional.
Complementa o tracing automatico do LangSmith com dados de negocio.
"""

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import case, func, select, text

from src.db.database import async_session
from src.db.models.conversation import Conversation
from src.db.models.lead import Lead
from src.db.models.notification import Notification
from src.db.models.scheduled_job import ScheduledJob
from src.db.models.score import LeadScore

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
async def get_metrics():
    """
    Dashboard de KPIs do agente Andreia.

    Retorna:
    - leads: distribuicao por classificacao e periodo
    - conversas: status ativo/encerrado
    - scores: media e distribuicao por classificacao
    - jobs: status dos jobs agendados por tipo
    - notificacoes: taxa de envio e atendimento por SLA
    - funil: distribuicao de leads por intencao detectada
    """
    async with async_session() as session:
        now = datetime.now(timezone.utc)

        # ------------------------------------------------------------------
        # LEADS
        # ------------------------------------------------------------------
        total_leads = await session.scalar(select(func.count()).select_from(Lead))

        # Leads por classificacao
        leads_by_class_rows = (
            await session.execute(
                select(
                    Lead.classification,
                    func.count().label("total"),
                ).group_by(Lead.classification)
            )
        ).all()
        leads_by_classification = {
            (row.classification or "sem_classificacao"): row.total
            for row in leads_by_class_rows
        }

        # Novos leads por periodo
        new_24h = await session.scalar(
            select(func.count()).select_from(Lead).where(
                Lead.created_at >= text("NOW() - INTERVAL '24 hours'")
            )
        )
        new_7d = await session.scalar(
            select(func.count()).select_from(Lead).where(
                Lead.created_at >= text("NOW() - INTERVAL '7 days'")
            )
        )
        new_30d = await session.scalar(
            select(func.count()).select_from(Lead).where(
                Lead.created_at >= text("NOW() - INTERVAL '30 days'")
            )
        )

        # Leads recorrentes
        recurring = await session.scalar(
            select(func.count()).select_from(Lead).where(Lead.is_recurring.is_(True))
        )

        # Top origens UTM
        utm_rows = (
            await session.execute(
                select(Lead.utm_source, func.count().label("total"))
                .where(Lead.utm_source.isnot(None))
                .group_by(Lead.utm_source)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
        utm_sources = {row.utm_source: row.total for row in utm_rows}

        # ------------------------------------------------------------------
        # CONVERSAS
        # ------------------------------------------------------------------
        conv_rows = (
            await session.execute(
                select(Conversation.status, func.count().label("total")).group_by(
                    Conversation.status
                )
            )
        ).all()
        conversations_by_status = {row.status: row.total for row in conv_rows}

        # Conversas com intent detectada (extraida do graph_state JSONB)
        intent_rows = (
            await session.execute(
                select(
                    Conversation.graph_state["detected_intent"].astext.label("intent"),
                    func.count().label("total"),
                )
                .where(Conversation.graph_state["detected_intent"].astext.isnot(None))
                .group_by(text("intent"))
                .order_by(func.count().desc())
            )
        ).all()
        intents_distribution = {(row.intent or "desconhecido"): row.total for row in intent_rows}

        # ------------------------------------------------------------------
        # SCORES
        # ------------------------------------------------------------------
        score_rows = (
            await session.execute(
                select(
                    LeadScore.classification,
                    func.count().label("total"),
                    func.avg(LeadScore.total_score).label("avg_score"),
                    func.min(LeadScore.total_score).label("min_score"),
                    func.max(LeadScore.total_score).label("max_score"),
                )
                .group_by(LeadScore.classification)
                .order_by(func.count().desc())
            )
        ).all()
        scores_by_classification = {
            (row.classification or "sem_classificacao"): {
                "total": row.total,
                "avg_score": round(float(row.avg_score), 1) if row.avg_score else None,
                "min_score": row.min_score,
                "max_score": row.max_score,
            }
            for row in score_rows
        }

        overall_avg_score = await session.scalar(
            select(func.avg(LeadScore.total_score)).select_from(LeadScore)
        )

        # ------------------------------------------------------------------
        # JOBS AGENDADOS
        # ------------------------------------------------------------------
        job_status_rows = (
            await session.execute(
                select(ScheduledJob.status, func.count().label("total")).group_by(
                    ScheduledJob.status
                )
            )
        ).all()
        jobs_by_status = {row.status: row.total for row in job_status_rows}

        job_type_rows = (
            await session.execute(
                select(
                    ScheduledJob.job_type,
                    ScheduledJob.status,
                    func.count().label("total"),
                )
                .group_by(ScheduledJob.job_type, ScheduledJob.status)
                .order_by(ScheduledJob.job_type)
            )
        ).all()
        jobs_by_type: dict[str, dict[str, int]] = {}
        for row in job_type_rows:
            if row.job_type not in jobs_by_type:
                jobs_by_type[row.job_type] = {}
            jobs_by_type[row.job_type][row.status] = row.total

        # ------------------------------------------------------------------
        # NOTIFICACOES
        # ------------------------------------------------------------------
        notif_rows = (
            await session.execute(
                select(
                    Notification.type,
                    func.count().label("total"),
                    func.count(Notification.sent_at).label("sent"),
                    func.count(Notification.acknowledged_at).label("acknowledged"),
                ).group_by(Notification.type)
            )
        ).all()
        notifications = {
            row.type: {
                "total": row.total,
                "sent": row.sent,
                "acknowledged": row.acknowledged,
                "ack_rate": (
                    round(row.acknowledged / row.sent * 100, 1) if row.sent else None
                ),
            }
            for row in notif_rows
        }

        # ------------------------------------------------------------------
        # RESPOSTA FINAL
        # ------------------------------------------------------------------
        return {
            "generated_at": now.isoformat(),
            "leads": {
                "total": total_leads,
                "recurring": recurring,
                "new_leads": {
                    "last_24h": new_24h,
                    "last_7d": new_7d,
                    "last_30d": new_30d,
                },
                "by_classification": leads_by_classification,
                "by_utm_source": utm_sources,
            },
            "conversations": {
                "by_status": conversations_by_status,
                "by_intent_detected": intents_distribution,
            },
            "scores": {
                "overall_avg": (
                    round(float(overall_avg_score), 1) if overall_avg_score else None
                ),
                "by_classification": scores_by_classification,
            },
            "scheduled_jobs": {
                "by_status": jobs_by_status,
                "by_type": jobs_by_type,
            },
            "notifications": notifications,
        }
