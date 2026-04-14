"""
metrics.py - Dashboard de KPIs do agente Andreia (Feature 18).

Endpoints:
  GET /metrics          - metricas operacionais gerais
  GET /metrics/dashboard - 8 KPIs monitorados no dashboard de negocio

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
from src.db.models.tag import LeadTag

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


@router.get("/dashboard")
async def get_dashboard_metrics():
    """
    Dashboard de KPIs de negocio — 8 metricas monitoradas:

    1. taxa_conversao_por_etapa   — distribuicao de conversas por no do agente
    2. tempo_medio_qualificacao   — horas entre inicio da conversa e scoring do lead
    3. taxa_resposta_corretor     — % de notificacoes atendidas e tempo medio de resposta
    4. taxa_agendamento_efetivado — % de leads em fluxo ativo que agendaram visita
    5. taxa_reengajamento         — leads reengajados nas ultimas 24h e 7d
    6. top_motivos_objecao        — top 5 barreiras/objecoes identificadas
    7. ticket_medio_por_classificacao — faixa de investimento media por classificacao do lead
    8. roi_por_canal_origem       — qualidade e conversao por canal UTM
    """
    async with async_session() as session:
        now = datetime.now(timezone.utc)

        # ------------------------------------------------------------------
        # 1. TAXA DE CONVERSÃO POR ETAPA
        # ------------------------------------------------------------------
        total_convs = await session.scalar(select(func.count()).select_from(Conversation))
        total_convs = total_convs or 0

        node_rows = (
            await session.execute(
                select(Conversation.current_node, func.count().label("total"))
                .where(Conversation.current_node.isnot(None))
                .group_by(Conversation.current_node)
                .order_by(func.count().desc())
            )
        ).all()

        # Leads detalhados por etapa
        leads_por_etapa_rows = (
            await session.execute(
                select(
                    Conversation.current_node,
                    Lead.id.label("lead_id"),
                    Lead.name.label("lead_name"),
                    Lead.phone,
                    Lead.classification,
                    Conversation.status.label("conv_status"),
                    Conversation.last_message_at,
                )
                .join(Lead, Lead.id == Conversation.lead_id)
                .where(Conversation.current_node.isnot(None))
                .order_by(Conversation.current_node, Conversation.last_message_at.desc())
            )
        ).all()

        leads_por_etapa: dict[str, list] = {}
        for row in leads_por_etapa_rows:
            node = row.current_node or "desconhecido"
            if node not in leads_por_etapa:
                leads_por_etapa[node] = []
            leads_por_etapa[node].append({
                "lead_id": str(row.lead_id),
                "nome": row.lead_name,
                "telefone": row.phone,
                "classificacao": row.classification,
                "status_conversa": row.conv_status,
                "ultima_mensagem": row.last_message_at.isoformat() if row.last_message_at else None,
            })

        taxa_conversao_por_etapa = {
            (row.current_node or "desconhecido"): {
                "total": row.total,
                "pct_do_total": round(row.total / total_convs * 100, 1) if total_convs else 0.0,
                "leads": leads_por_etapa.get(row.current_node or "desconhecido", []),
            }
            for row in node_rows
        }

        # ------------------------------------------------------------------
        # 2. TEMPO MÉDIO DE QUALIFICAÇÃO
        # Medido do created_at da primeira conversa do lead ao created_at do score.
        # ------------------------------------------------------------------
        qual_row = (
            await session.execute(
                text("""
                    SELECT
                        COUNT(*) AS total_qualificados,
                        AVG(delta_h) AS avg_h,
                        MIN(delta_h) AS min_h,
                        MAX(delta_h) AS max_h
                    FROM (
                        SELECT
                            ls.lead_id,
                            EXTRACT(EPOCH FROM (MIN(ls.created_at) - MIN(c.created_at))) / 3600 AS delta_h
                        FROM lead_scores ls
                        JOIN conversations c ON c.lead_id = ls.lead_id
                        GROUP BY ls.lead_id
                        HAVING MIN(ls.created_at) > MIN(c.created_at)
                    ) sub
                """)
            )
        ).one()

        tempo_medio_qualificacao = {
            "total_leads_qualificados": qual_row.total_qualificados or 0,
            "avg_horas": round(float(qual_row.avg_h), 2) if qual_row.avg_h else None,
            "min_horas": round(float(qual_row.min_h), 2) if qual_row.min_h else None,
            "max_horas": round(float(qual_row.max_h), 2) if qual_row.max_h else None,
        }

        # ------------------------------------------------------------------
        # 3. TAXA DE RESPOSTA DO CORRETOR
        # ------------------------------------------------------------------
        notif_row = (
            await session.execute(
                select(
                    func.count(Notification.id).label("total"),
                    func.count(Notification.sent_at).label("enviadas"),
                    func.count(Notification.acknowledged_at).label("atendidas"),
                    func.avg(
                        func.extract(
                            "epoch",
                            Notification.acknowledged_at - Notification.sent_at,
                        )
                        / 3600
                    ).label("avg_resp_h"),
                ).select_from(Notification)
            )
        ).one()

        enviadas = notif_row.enviadas or 0
        atendidas = notif_row.atendidas or 0
        taxa_resposta_corretor = {
            "total_notificacoes": notif_row.total or 0,
            "enviadas": enviadas,
            "atendidas": atendidas,
            "taxa_atendimento_pct": (
                round(atendidas / enviadas * 100, 1) if enviadas else None
            ),
            "tempo_medio_resposta_horas": (
                round(float(notif_row.avg_resp_h), 2) if notif_row.avg_resp_h else None
            ),
        }

        # ------------------------------------------------------------------
        # 4. TAXA DE AGENDAMENTO EFETIVADO
        # Tags de agendamento: visita_agendada, visita_tecnica_solicitada, apresentacao_agendada
        # ------------------------------------------------------------------
        _visita_tags = [
            "visita_agendada",
            "visita_tecnica_solicitada",
            "apresentacao_agendada",
        ]

        leads_em_fluxo = await session.scalar(
            select(func.count(func.distinct(Conversation.lead_id))).where(
                Conversation.current_node.in_(
                    ["buyer", "sale", "launch", "investor", "rental", "exchange"]
                )
            )
        )

        leads_com_agendamento = await session.scalar(
            select(func.count(func.distinct(LeadTag.lead_id))).where(
                LeadTag.tag_name.in_(_visita_tags),
                LeadTag.tag_value == "true",
            )
        )

        leads_em_fluxo = leads_em_fluxo or 0
        leads_com_agendamento = leads_com_agendamento or 0
        taxa_agendamento_efetivado = {
            "leads_em_fluxo": leads_em_fluxo,
            "agendamentos_efetivados": leads_com_agendamento,
            "taxa_agendamento_pct": (
                round(leads_com_agendamento / leads_em_fluxo * 100, 1)
                if leads_em_fluxo
                else None
            ),
        }

        # ------------------------------------------------------------------
        # 5. TAXA DE REENGAJAMENTO (24h / 7d)
        # Proxy: conversas cujo current_node == 'reengagement' atualizadas no periodo.
        # ------------------------------------------------------------------
        reengajados_24h = await session.scalar(
            select(func.count(func.distinct(Conversation.lead_id))).where(
                Conversation.current_node == "reengagement",
                Conversation.updated_at >= text("NOW() - INTERVAL '24 hours'"),
            )
        )
        reengajados_7d = await session.scalar(
            select(func.count(func.distinct(Conversation.lead_id))).where(
                Conversation.current_node == "reengagement",
                Conversation.updated_at >= text("NOW() - INTERVAL '7 days'"),
            )
        )
        leads_inativos = await session.scalar(
            select(func.count(func.distinct(Conversation.lead_id))).where(
                Conversation.status == "active",
                Conversation.last_lead_message_at
                < text("NOW() - INTERVAL '24 hours'"),
            )
        )

        reengajados_7d = reengajados_7d or 0
        leads_inativos = leads_inativos or 0
        taxa_reengajamento = {
            "reengajados_24h": reengajados_24h or 0,
            "reengajados_7d": reengajados_7d,
            "leads_inativos_atuais": leads_inativos,
            "taxa_reengajamento_7d_pct": (
                round(reengajados_7d / leads_inativos * 100, 1)
                if leads_inativos
                else None
            ),
        }

        # ------------------------------------------------------------------
        # 6. TOP 5 MOTIVOS DE OBJEÇÃO
        # Mapeamento de tags para barreiras identificadas pelo agente.
        # ------------------------------------------------------------------
        _barreira_tags = {
            "lead_fora_perfil": "Fora do perfil (ticket baixo)",
            "consultoria_agendada": "Barreira financeira",
            "lista_vip": "Barreira de timing (momento)",
            "tour_agendado": "Barreira de conhecimento",
        }

        motivos: dict[str, int] = {}
        for tag_name, label in _barreira_tags.items():
            count = await session.scalar(
                select(func.count(func.distinct(LeadTag.lead_id))).where(
                    LeadTag.tag_name == tag_name, LeadTag.tag_value == "true"
                )
            )
            if count:
                motivos[label] = count

        recusou_visita = await session.scalar(
            select(func.count(func.distinct(LeadTag.lead_id))).where(
                LeadTag.tag_name == "visita_tecnica_solicitada",
                LeadTag.tag_value == "false",
            )
        )
        if recusou_visita:
            motivos["Recusou visita tecnica"] = recusou_visita

        top_motivos_objecao = dict(
            sorted(motivos.items(), key=lambda x: x[1], reverse=True)[:5]
        )

        # ------------------------------------------------------------------
        # 7. TICKET MÉDIO POR CLASSIFICAÇÃO
        # Extrai valor numerico da tag faixa_valor (formatos: "800k", "500 mil",
        # "1 milhao", "800000", "R$ 800.000").
        # ------------------------------------------------------------------
        ticket_rows = (
            await session.execute(
                text("""
                    SELECT
                        l.classification,
                        COUNT(DISTINCT l.id) AS total_leads,
                        AVG(
                            CASE
                                WHEN lower(lt.tag_value) ~ 'milh'
                                    THEN (regexp_match(lt.tag_value, '[0-9]+'))[1]::numeric * 1000000
                                WHEN lower(lt.tag_value) ~ '[0-9]+\\s*k'
                                    THEN (regexp_match(lt.tag_value, '[0-9]+'))[1]::numeric * 1000
                                WHEN lower(lt.tag_value) ~ '[0-9]+\\s*mil'
                                    THEN (regexp_match(lt.tag_value, '[0-9]+'))[1]::numeric * 1000
                                WHEN lt.tag_value ~ '^[0-9.]+$'
                                    THEN replace(lt.tag_value, '.', '')::numeric
                                ELSE NULL
                            END
                        ) AS avg_ticket
                    FROM leads l
                    JOIN lead_tags lt ON lt.lead_id = l.id
                    WHERE
                        lt.tag_name = 'faixa_valor'
                        AND l.classification IS NOT NULL
                        AND lt.tag_value ~ '[0-9]'
                    GROUP BY l.classification
                    ORDER BY avg_ticket DESC NULLS LAST
                """)
            )
        ).all()

        ticket_medio_por_classificacao = {
            row.classification: {
                "total_leads": row.total_leads,
                "ticket_medio_estimado": int(row.avg_ticket) if row.avg_ticket else None,
            }
            for row in ticket_rows
        }

        # ------------------------------------------------------------------
        # 8. ROI POR CANAL DE ORIGEM (utm_source)
        # Metrica proxy: leads totais, score medio e taxa de agendamento por canal.
        # ------------------------------------------------------------------
        roi_rows = (
            await session.execute(
                text("""
                    SELECT
                        l.utm_source,
                        COUNT(DISTINCT l.id) AS total_leads,
                        ROUND(AVG(ls.total_score)::numeric, 1) AS avg_score,
                        COUNT(DISTINCT
                            CASE
                                WHEN lt.tag_name IN (
                                    'visita_agendada',
                                    'visita_tecnica_solicitada',
                                    'apresentacao_agendada'
                                ) AND lt.tag_value = 'true'
                                THEN l.id
                            END
                        ) AS agendamentos
                    FROM leads l
                    LEFT JOIN lead_scores ls ON ls.lead_id = l.id
                    LEFT JOIN lead_tags lt ON lt.lead_id = l.id
                    WHERE l.utm_source IS NOT NULL
                    GROUP BY l.utm_source
                    ORDER BY total_leads DESC
                    LIMIT 10
                """)
            )
        ).all()

        roi_por_canal_origem = {
            row.utm_source: {
                "total_leads": row.total_leads,
                "avg_score": float(row.avg_score) if row.avg_score else None,
                "agendamentos": row.agendamentos,
                "taxa_conversao_pct": (
                    round(row.agendamentos / row.total_leads * 100, 1)
                    if row.total_leads
                    else None
                ),
            }
            for row in roi_rows
        }

        # ------------------------------------------------------------------
        # RESPOSTA FINAL
        # ------------------------------------------------------------------
        return {
            "generated_at": now.isoformat(),
            "taxa_conversao_por_etapa": taxa_conversao_por_etapa,
            "tempo_medio_qualificacao": tempo_medio_qualificacao,
            "taxa_resposta_corretor": taxa_resposta_corretor,
            "taxa_agendamento_efetivado": taxa_agendamento_efetivado,
            "taxa_reengajamento": taxa_reengajamento,
            "top_motivos_objecao": top_motivos_objecao,
            "ticket_medio_por_classificacao": ticket_medio_por_classificacao,
            "roi_por_canal_origem": roi_por_canal_origem,
        }
