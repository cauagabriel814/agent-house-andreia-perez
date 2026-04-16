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

        leads_com_conversa = await session.scalar(
            select(func.count(func.distinct(Conversation.lead_id)))
        )

        leads_com_agendamento = await session.scalar(
            select(func.count(func.distinct(LeadTag.lead_id))).where(
                LeadTag.tag_name.in_(_visita_tags),
                LeadTag.tag_value == "true",
            )
        )

        leads_com_conversa = leads_com_conversa or 0
        leads_com_agendamento = leads_com_agendamento or 0
        taxa_agendamento_efetivado = {
            "total_leads": leads_com_conversa,
            "agendamentos_efetivados": leads_com_agendamento,
            "taxa_agendamento_pct": (
                round(leads_com_agendamento / leads_com_conversa * 100, 1)
                if leads_com_conversa
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


# ===========================================================================
# ROTAS DEDICADAS — uma métrica, dados completos de quem são os leads
# ===========================================================================


@router.get("/taxa-conversao")
async def get_taxa_conversao():
    """
    Todos os leads com flag de conversão.

    Convertido = agendou visita/apresentacao OU chegou ao node 'completed'.
    Retorna: total, convertidos, taxa_pct e lista de todos os leads.
    """
    async with async_session() as session:
        _visita_tags = ["visita_agendada", "visita_tecnica_solicitada", "apresentacao_agendada"]

        # Lead IDs convertidos via tag de agendamento
        converted_tag_rows = (
            await session.execute(
                select(func.distinct(LeadTag.lead_id)).where(
                    LeadTag.tag_name.in_(_visita_tags),
                    LeadTag.tag_value == "true",
                )
            )
        ).scalars().all()
        converted_ids = {str(lid) for lid in converted_tag_rows}

        # Todos os leads com sua conversa mais recente
        leads_rows = (
            await session.execute(
                text("""
                    SELECT
                        l.id        AS lead_id,
                        l.name      AS nome,
                        l.phone     AS telefone,
                        l.classification AS classificacao,
                        c.current_node   AS etapa_atual,
                        c.status         AS status_conversa
                    FROM leads l
                    LEFT JOIN LATERAL (
                        SELECT current_node, status
                        FROM conversations
                        WHERE lead_id = l.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) c ON true
                    ORDER BY l.created_at DESC
                """)
            )
        ).all()

        leads = []
        for row in leads_rows:
            lid = str(row.lead_id)
            convertido = lid in converted_ids or row.etapa_atual == "completed"
            leads.append({
                "lead_id": lid,
                "nome": row.nome,
                "telefone": row.telefone,
                "classificacao": row.classificacao,
                "etapa_atual": row.etapa_atual,
                "convertido": convertido,
            })

        total = len(leads)
        convertidos = sum(1 for l in leads if l["convertido"])
        return {
            "total": total,
            "convertidos": convertidos,
            "taxa_pct": round(convertidos / total * 100, 1) if total else None,
            "leads": leads,
        }


@router.get("/tempo-qualificacao")
async def get_tempo_qualificacao():
    """
    Leads qualificados com tempo da primeira mensagem até o scoring.

    Retorna: media_minutos, total e lista de leads com duração individual.
    """
    async with async_session() as session:
        rows = (
            await session.execute(
                text("""
                    SELECT
                        l.id   AS lead_id,
                        l.name AS nome,
                        l.phone AS telefone,
                        MIN(c.created_at) AS inicio_conversa,
                        MIN(ls.created_at) AS qualificado_em,
                        EXTRACT(EPOCH FROM (MIN(ls.created_at) - MIN(c.created_at))) / 60
                            AS duracao_minutos
                    FROM leads l
                    JOIN conversations c  ON c.lead_id  = l.id
                    JOIN lead_scores   ls ON ls.lead_id = l.id
                    GROUP BY l.id, l.name, l.phone
                    HAVING MIN(ls.created_at) > MIN(c.created_at)
                    ORDER BY duracao_minutos ASC
                """)
            )
        ).all()

        leads = [
            {
                "lead_id": str(row.lead_id),
                "nome": row.nome,
                "telefone": row.telefone,
                "inicio_conversa": row.inicio_conversa.isoformat() if row.inicio_conversa else None,
                "qualificado_em": row.qualificado_em.isoformat() if row.qualificado_em else None,
                "duracao_minutos": round(float(row.duracao_minutos), 1) if row.duracao_minutos else None,
            }
            for row in rows
        ]

        durações = [l["duracao_minutos"] for l in leads if l["duracao_minutos"] is not None]
        media = round(sum(durações) / len(durações), 1) if durações else None

        return {
            "total": len(leads),
            "media_minutos": media,
            "leads": leads,
        }


@router.get("/agendamento-efetivado")
async def get_agendamento_efetivado():
    """
    Leads que agendaram visita ou apresentação.

    Retorna: total e lista com nome, telefone, tipo de agendamento e data (se disponível).
    """
    async with async_session() as session:
        # Leads com tag de agendamento confirmado
        agend_rows = (
            await session.execute(
                text("""
                    SELECT
                        l.id    AS lead_id,
                        l.name  AS nome,
                        l.phone AS telefone,
                        lt.tag_name  AS tipo_agendamento,
                        lt.created_at AS agendado_em
                    FROM leads l
                    JOIN lead_tags lt ON lt.lead_id = l.id
                    WHERE lt.tag_name IN (
                        'visita_agendada', 'visita_tecnica_solicitada', 'apresentacao_agendada'
                    )
                    AND lt.tag_value = 'true'
                    ORDER BY lt.created_at DESC
                """)
            )
        ).all()

        # Tags de data para cruzar
        date_rows = (
            await session.execute(
                select(LeadTag.lead_id, LeadTag.tag_name, LeadTag.tag_value).where(
                    LeadTag.tag_name.in_(["data_visita", "data_apresentacao"])
                )
            )
        ).all()
        datas_por_lead = {str(r.lead_id): r.tag_value for r in date_rows}

        leads = [
            {
                "lead_id": str(row.lead_id),
                "nome": row.nome,
                "telefone": row.telefone,
                "tipo_agendamento": row.tipo_agendamento,
                "data_agendamento": datas_por_lead.get(str(row.lead_id)),
                "agendado_em": row.agendado_em.isoformat() if row.agendado_em else None,
            }
            for row in agend_rows
        ]

        return {
            "total": len(leads),
            "leads": leads,
        }


@router.get("/reengajamento")
async def get_reengajamento():
    """
    Jobs de reengajamento pendentes (ainda não executados, scheduled_for no futuro).

    Mostra quem são os leads e quanto tempo falta para entrar em contato.
    Não inclui leads com conversa encerrada (completed).
    """
    async with async_session() as session:
        _reeng_types = (
            "reengagement_24h", "reengagement_7d",
            "nurture_30d", "nurture_60d", "nurture_90d",
            "follow_up_48h", "follow_up_24h",
        )

        rows = (
            await session.execute(
                text("""
                    SELECT
                        sj.id           AS job_id,
                        l.id            AS lead_id,
                        l.name          AS nome,
                        l.phone         AS telefone,
                        sj.job_type,
                        sj.scheduled_for,
                        EXTRACT(EPOCH FROM (sj.scheduled_for - NOW())) / 3600
                            AS horas_restantes
                    FROM scheduled_jobs sj
                    JOIN leads l ON l.id = sj.lead_id
                    WHERE sj.status = 'pending'
                      AND sj.scheduled_for > NOW()
                      AND sj.job_type = ANY(:tipos)
                      AND NOT EXISTS (
                          SELECT 1 FROM conversations c
                          WHERE c.lead_id = sj.lead_id
                            AND c.current_node = 'completed'
                      )
                    ORDER BY sj.scheduled_for ASC
                """),
                {"tipos": list(_reeng_types)},
            )
        ).all()

        leads = [
            {
                "job_id": str(row.job_id),
                "lead_id": str(row.lead_id),
                "nome": row.nome,
                "telefone": row.telefone,
                "job_type": row.job_type,
                "agendado_para": row.scheduled_for.isoformat() if row.scheduled_for else None,
                "horas_restantes": round(float(row.horas_restantes), 1) if row.horas_restantes else None,
            }
            for row in rows
        ]

        return {
            "total_pendentes": len(leads),
            "leads": leads,
        }


@router.get("/ticket-medio")
async def get_ticket_medio():
    """
    Leads com preferência de imóvel (faixa_valor), localização e situação.

    Retorna: média geral, média por classificação e lista de leads com detalhes.
    """
    async with async_session() as session:
        rows = (
            await session.execute(
                text("""
                    SELECT
                        l.id             AS lead_id,
                        l.name           AS nome,
                        l.phone          AS telefone,
                        l.classification AS classificacao,
                        MAX(CASE WHEN lt.tag_name = 'faixa_valor'    THEN lt.tag_value END) AS faixa_valor,
                        MAX(CASE WHEN lt.tag_name = 'localizacao'    THEN lt.tag_value END) AS localizacao,
                        MAX(CASE WHEN lt.tag_name = 'situacao_imovel' THEN lt.tag_value END) AS situacao_imovel,
                        -- extrai valor numérico estimado
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
                        ) FILTER (WHERE lt.tag_name = 'faixa_valor') AS ticket_estimado
                    FROM leads l
                    JOIN lead_tags lt ON lt.lead_id = l.id
                    WHERE EXISTS (
                        SELECT 1 FROM lead_tags lt2
                        WHERE lt2.lead_id = l.id AND lt2.tag_name = 'faixa_valor'
                    )
                    GROUP BY l.id, l.name, l.phone, l.classification
                    ORDER BY ticket_estimado DESC NULLS LAST
                """)
            )
        ).all()

        leads = []
        tickets_por_class: dict[str, list[float]] = {}

        for row in rows:
            ticket = int(row.ticket_estimado) if row.ticket_estimado else None
            leads.append({
                "lead_id": str(row.lead_id),
                "nome": row.nome,
                "telefone": row.telefone,
                "classificacao": row.classificacao,
                "faixa_valor": row.faixa_valor,
                "ticket_estimado": ticket,
                "localizacao": row.localizacao,
                "situacao_imovel": row.situacao_imovel,
            })
            if ticket and row.classificacao:
                tickets_por_class.setdefault(row.classificacao, []).append(ticket)

        todos_tickets = [l["ticket_estimado"] for l in leads if l["ticket_estimado"]]
        media_geral = int(sum(todos_tickets) / len(todos_tickets)) if todos_tickets else None

        por_classificacao = {
            cls: {"media": int(sum(vals) / len(vals)), "total_leads": len(vals)}
            for cls, vals in tickets_por_class.items()
        }

        return {
            "total_leads": len(leads),
            "media_geral": media_geral,
            "por_classificacao": por_classificacao,
            "leads": leads,
        }
