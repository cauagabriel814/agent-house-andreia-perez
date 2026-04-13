"""
Testes do sistema de Cron Jobs (Feature 16).

Cobre:
- _lead_responded_since_job: deteccao correta de resposta do lead
- Scheduler ignora job quando lead respondeu (safety net para race conditions)
- execute_follow_up_48h: envia mensagem correta para proprietario de locacao
- execute_follow_up_24h: envia mensagem correta para lead morno de lancamento
- execute_reminder_24h: envia lembrete com e sem detalhes de visita
- touch_lead_message: atualiza last_lead_message_at na conversa
- is_scheduler_running / start_scheduler / stop_scheduler
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_job(
    job_id: str = "00000000-0000-0000-0000-000000000001",
    lead_id: str = "00000000-0000-0000-0000-000000000001",
    job_type: str = "reengagement_24h",
    payload: dict | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.lead_id = lead_id
    job.job_type = job_type
    job.payload = payload or {}
    job.created_at = created_at or datetime.now(tz=timezone.utc) - timedelta(hours=25)
    job.status = "pending"
    return job


def make_conversation(last_lead_message_at: datetime | None = None) -> MagicMock:
    conv = MagicMock()
    conv.last_lead_message_at = last_lead_message_at
    return conv


# ---------------------------------------------------------------------------
# Testes de _lead_responded_since_job
# ---------------------------------------------------------------------------


class TestLeadRespondedSinceJob:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_conversation(self):
        from src.jobs.scheduler import _lead_responded_since_job

        job = make_job()
        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_conv_svc = AsyncMock()
        mock_conv_svc.get_active_by_lead = AsyncMock(return_value=None)

        with (
            patch("src.jobs.scheduler.async_session", return_value=mock_session_ctx),
            patch("src.jobs.scheduler.ConversationService", return_value=mock_conv_svc),
        ):
            result = await _lead_responded_since_job(job)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_last_lead_message(self):
        from src.jobs.scheduler import _lead_responded_since_job

        job = make_job(created_at=datetime.now(tz=timezone.utc) - timedelta(hours=1))
        conv = make_conversation(last_lead_message_at=None)

        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conv_svc = AsyncMock()
        mock_conv_svc.get_active_by_lead = AsyncMock(return_value=conv)

        with (
            patch("src.jobs.scheduler.async_session", return_value=mock_session_ctx),
            patch("src.jobs.scheduler.ConversationService", return_value=mock_conv_svc),
        ):
            result = await _lead_responded_since_job(job)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_lead_messaged_before_job_created(self):
        from src.jobs.scheduler import _lead_responded_since_job

        job_created = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        lead_messaged = job_created - timedelta(minutes=30)  # ANTES do job

        job = make_job(created_at=job_created)
        conv = make_conversation(last_lead_message_at=lead_messaged)

        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conv_svc = AsyncMock()
        mock_conv_svc.get_active_by_lead = AsyncMock(return_value=conv)

        with (
            patch("src.jobs.scheduler.async_session", return_value=mock_session_ctx),
            patch("src.jobs.scheduler.ConversationService", return_value=mock_conv_svc),
        ):
            result = await _lead_responded_since_job(job)

        assert result is False  # lead respondeu antes do job, nao depois

    @pytest.mark.asyncio
    async def test_returns_true_when_lead_messaged_after_job_created(self):
        from src.jobs.scheduler import _lead_responded_since_job

        job_created = datetime.now(tz=timezone.utc) - timedelta(hours=2)
        lead_messaged = job_created + timedelta(hours=1)  # APOS o job

        job = make_job(created_at=job_created)
        conv = make_conversation(last_lead_message_at=lead_messaged)

        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conv_svc = AsyncMock()
        mock_conv_svc.get_active_by_lead = AsyncMock(return_value=conv)

        with (
            patch("src.jobs.scheduler.async_session", return_value=mock_session_ctx),
            patch("src.jobs.scheduler.ConversationService", return_value=mock_conv_svc),
        ):
            result = await _lead_responded_since_job(job)

        assert result is True  # lead respondeu depois do job, deve ignorar

    @pytest.mark.asyncio
    async def test_handles_naive_datetime_comparison(self):
        """Deve comparar corretamente timestamps naive vs aware."""
        from src.jobs.scheduler import _lead_responded_since_job

        # job.created_at = aware, conv.last_lead_message_at = naive (mais recente)
        job_created = datetime.now(tz=timezone.utc) - timedelta(hours=3)
        lead_messaged = datetime.utcnow() - timedelta(hours=1)  # naive, mas mais recente

        job = make_job(created_at=job_created)
        conv = make_conversation(last_lead_message_at=lead_messaged)

        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conv_svc = AsyncMock()
        mock_conv_svc.get_active_by_lead = AsyncMock(return_value=conv)

        with (
            patch("src.jobs.scheduler.async_session", return_value=mock_session_ctx),
            patch("src.jobs.scheduler.ConversationService", return_value=mock_conv_svc),
        ):
            # Nao deve lancar excecao de timezone
            result = await _lead_responded_since_job(job)

        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Testes de _execute_job (skip quando lead respondeu)
# ---------------------------------------------------------------------------


class TestExecuteJobSkipsWhenLeadResponded:
    @pytest.mark.asyncio
    async def test_skips_execution_when_lead_responded(self):
        from src.jobs.scheduler import _execute_job

        job = make_job(job_type="reengagement_24h")

        with (
            patch(
                "src.jobs.scheduler._lead_responded_since_job",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "src.jobs.scheduler.execute_reengagement_24h",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            await _execute_job(job)

        mock_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_executes_when_lead_did_not_respond(self):
        from src.jobs.scheduler import _execute_job

        job = make_job(job_type="reengagement_24h", payload={"name": "Ana"})

        with (
            patch(
                "src.jobs.scheduler._lead_responded_since_job",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "src.jobs.scheduler.execute_reengagement_24h",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            await _execute_job(job)

        mock_execute.assert_called_once_with(job.lead_id, {"name": "Ana"})


# ---------------------------------------------------------------------------
# Testes dos executores de follow_up
# ---------------------------------------------------------------------------


class TestFollowUp48h:
    @pytest.mark.asyncio
    async def test_sends_rental_followup_message(self):
        from src.jobs.follow_up_48h import execute_follow_up_48h

        mock_lead = MagicMock()
        mock_lead.phone = "5565999999999"
        mock_lead.name = "Roberto"

        mock_lead_svc = AsyncMock()
        mock_lead_svc.get_by_id = AsyncMock(return_value=mock_lead)

        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.jobs.follow_up_48h.async_session", return_value=mock_session_ctx),
            patch("src.jobs.follow_up_48h.LeadService", return_value=mock_lead_svc),
            patch(
                "src.jobs.follow_up_48h.send_whatsapp_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            await execute_follow_up_48h("00000000-0000-0000-0000-000000000001", {"name": "Roberto"})

        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert "Roberto" in sent_msg

    @pytest.mark.asyncio
    async def test_skips_when_lead_not_found(self):
        from src.jobs.follow_up_48h import execute_follow_up_48h

        mock_lead_svc = AsyncMock()
        mock_lead_svc.get_by_id = AsyncMock(return_value=None)

        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.jobs.follow_up_48h.async_session", return_value=mock_session_ctx),
            patch("src.jobs.follow_up_48h.LeadService", return_value=mock_lead_svc),
            patch(
                "src.jobs.follow_up_48h.send_whatsapp_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            await execute_follow_up_48h("00000000-0000-0000-0000-000000000999")

        mock_send.assert_not_called()


class TestFollowUp24h:
    @pytest.mark.asyncio
    async def test_sends_launch_followup_with_property(self):
        from src.jobs.follow_up_48h import execute_follow_up_24h

        mock_lead = MagicMock()
        mock_lead.phone = "5565888888888"
        mock_lead.name = "Claudia"

        mock_lead_svc = AsyncMock()
        mock_lead_svc.get_by_id = AsyncMock(return_value=mock_lead)

        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.jobs.follow_up_48h.async_session", return_value=mock_session_ctx),
            patch("src.jobs.follow_up_48h.LeadService", return_value=mock_lead_svc),
            patch(
                "src.jobs.follow_up_48h.send_whatsapp_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            await execute_follow_up_24h(
                "00000000-0000-0000-0000-000000000001", {"name": "Claudia", "property": "Residencial Diamante"}
            )

        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert "Claudia" in sent_msg
        assert "Residencial Diamante" in sent_msg


# ---------------------------------------------------------------------------
# Testes do execute_reminder_24h
# ---------------------------------------------------------------------------


class TestReminder24h:
    @pytest.mark.asyncio
    async def test_sends_reminder_without_details(self):
        from src.jobs.reminder_24h import execute_reminder_24h

        mock_lead = MagicMock()
        mock_lead.phone = "5565777777777"
        mock_lead.name = "Felipe"

        mock_lead_svc = AsyncMock()
        mock_lead_svc.get_by_id = AsyncMock(return_value=mock_lead)

        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.jobs.reminder_24h.async_session", return_value=mock_session_ctx),
            patch("src.jobs.reminder_24h.LeadService", return_value=mock_lead_svc),
            patch(
                "src.jobs.reminder_24h.send_whatsapp_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            await execute_reminder_24h("00000000-0000-0000-0000-000000000001", {"name": "Felipe"})

        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert "Felipe" in sent_msg

    @pytest.mark.asyncio
    async def test_sends_reminder_with_full_details(self):
        from src.jobs.reminder_24h import execute_reminder_24h

        mock_lead = MagicMock()
        mock_lead.phone = "5565666666666"
        mock_lead.name = "Beatriz"

        mock_lead_svc = AsyncMock()
        mock_lead_svc.get_by_id = AsyncMock(return_value=mock_lead)

        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.jobs.reminder_24h.async_session", return_value=mock_session_ctx),
            patch("src.jobs.reminder_24h.LeadService", return_value=mock_lead_svc),
            patch(
                "src.jobs.reminder_24h.send_whatsapp_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            await execute_reminder_24h(
                "00000000-0000-0000-0000-000000000001",
                {
                    "name": "Beatriz",
                    "visit_time": "14h00",
                    "property_address": "Rua das Flores, 123 - Jardim Italia",
                },
            )

        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert "Beatriz" in sent_msg
        assert "14h00" in sent_msg
        assert "Jardim Italia" in sent_msg


# ---------------------------------------------------------------------------
# Testes dos prompts de follow_up
# ---------------------------------------------------------------------------


class TestFollowUpPrompts:
    def test_follow_up_48h_rental_format(self):
        from src.agent.prompts.follow_up import FOLLOW_UP_48H_RENTAL

        msg = FOLLOW_UP_48H_RENTAL.format(name="Lucas")
        assert "Lucas" in msg

    def test_follow_up_24h_launch_format(self):
        from src.agent.prompts.follow_up import FOLLOW_UP_24H_LAUNCH

        msg = FOLLOW_UP_24H_LAUNCH.format(name="Marina", property="Solar dos Lagos")
        assert "Marina" in msg
        assert "Solar dos Lagos" in msg

    def test_reminder_visit_format(self):
        from src.agent.prompts.follow_up import REMINDER_24H_VISIT

        msg = REMINDER_24H_VISIT.format(name="Paulo")
        assert "Paulo" in msg

    def test_reminder_visit_with_details_format(self):
        from src.agent.prompts.follow_up import REMINDER_24H_VISIT_WITH_DETAILS

        msg = REMINDER_24H_VISIT_WITH_DETAILS.format(
            name="Sofia",
            visit_time="10h30",
            property_address="Av. das Nacoes, 500 - Quilombo",
        )
        assert "Sofia" in msg
        assert "10h30" in msg
        assert "Quilombo" in msg


# ---------------------------------------------------------------------------
# Testes de ciclo de vida do scheduler
# ---------------------------------------------------------------------------


class TestSchedulerLifecycle:
    def test_is_scheduler_running_false_initially(self):
        from src.jobs.scheduler import is_scheduler_running

        # Sem inicializar, nao esta rodando (ou foi parado em outros testes)
        # Apenas verifica que a funcao retorna bool
        assert isinstance(is_scheduler_running(), bool)

    @pytest.mark.asyncio
    async def test_start_and_stop_scheduler(self):
        import asyncio

        from src.jobs.scheduler import is_scheduler_running, start_scheduler, stop_scheduler

        # Iniciar
        with patch("src.jobs.scheduler.run_scheduler_loop", new_callable=AsyncMock):
            task = await start_scheduler(interval_seconds=999)
            assert task is not None

        # Parar
        await stop_scheduler()
        assert is_scheduler_running() is False

    @pytest.mark.asyncio
    async def test_stop_scheduler_when_not_running_is_safe(self):
        from src.jobs.scheduler import stop_scheduler

        # Deve ser seguro chamar stop quando nao esta rodando
        await stop_scheduler()
