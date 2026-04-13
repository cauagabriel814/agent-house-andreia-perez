"""
Testes do fluxo de Timeout + Reengajamento (Feature 15).

Cobre:
- route_entry roteia para "timeout" quando message_type="timeout"
- timeout_node: primeiro timeout (count=0) envia mensagem e agenda job 30min
- timeout_node: segundo timeout (count>=1) adiciona tag lead_timeout e agenda reengajamento
- reengagement_node: reseta timeout_count para zero
- Prompts de reengajamento formatados corretamente
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_state(**overrides) -> dict:
    base = {
        "phone": "5565999999999",
        "lead_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000010",
        "current_message": "",
        "message_type": "text",
        "processed_content": None,
        "lead_name": "Joao",
        "lead_email": None,
        "is_recurring": False,
        "classification": None,
        "messages": [],
        "conversation_history": [],
        "tags": {},
        "current_node": "",
        "detected_intent": None,
        "score_data": None,
        "total_score": None,
        "awaiting_response": False,
        "last_question": None,
        "timeout_count": 0,
        "business_hours": True,
        "utm_source": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Testes de roteamento (conditions.py)
# ---------------------------------------------------------------------------


class TestRouteEntry:
    def test_timeout_message_type_routes_to_timeout(self):
        from src.agent.edges.conditions import route_entry

        state = make_state(message_type="timeout", current_node="investor")
        assert route_entry(state) == "timeout"

    def test_timeout_message_type_overrides_current_node(self):
        from src.agent.edges.conditions import route_entry

        state = make_state(message_type="timeout", current_node="greeting")
        assert route_entry(state) == "timeout"

    def test_normal_text_message_does_not_route_to_timeout(self):
        from src.agent.edges.conditions import route_entry

        state = make_state(message_type="text", current_node="")
        assert route_entry(state) == "greeting"

    def test_after_timeout_lead_responds_routes_to_greeting(self):
        from src.agent.edges.conditions import route_entry

        # Apos timeout, mensagem normal com current_node="timeout" deve reiniciar fluxo
        state = make_state(message_type="text", current_node="timeout")
        assert route_entry(state) == "greeting"

    def test_audio_message_does_not_route_to_timeout(self):
        from src.agent.edges.conditions import route_entry

        state = make_state(message_type="audio", current_node="greeting")
        assert route_entry(state) == "active_listen"


# ---------------------------------------------------------------------------
# Testes do timeout_node
# ---------------------------------------------------------------------------


class TestTimeoutNode:
    @pytest.mark.asyncio
    async def test_first_timeout_sends_message_and_schedules_30min(self):
        from src.agent.nodes.timeout import timeout_node

        state = make_state(
            timeout_count=0, lead_name="Maria", tags={"localizacao": "Jardim Italia"}
        )

        mock_job_svc = AsyncMock()
        mock_session = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "src.agent.nodes.timeout.send_whatsapp_message", new_callable=AsyncMock
            ) as mock_send,
            patch("src.agent.nodes.timeout.async_session", return_value=mock_session_ctx),
            patch("src.agent.nodes.timeout.JobService", return_value=mock_job_svc),
        ):
            result = await timeout_node(state)

        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert "Maria" in sent_msg

        assert result["timeout_count"] == 1
        assert result["awaiting_response"] is True
        assert result["current_node"] == "timeout"
        assert len(result["messages"]) == 1

    @pytest.mark.asyncio
    async def test_second_timeout_adds_tag_and_schedules_reengagement(self):
        from src.agent.nodes.timeout import timeout_node

        state = make_state(
            timeout_count=1,
            lead_name="Pedro",
            lead_id="00000000-0000-0000-0000-000000000005",
            tags={"localizacao": "Quilombo"},
        )

        mock_job_svc = AsyncMock()
        mock_tag_svc = AsyncMock()
        mock_session = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "src.agent.nodes.timeout.send_whatsapp_message", new_callable=AsyncMock
            ) as mock_send,
            patch("src.agent.nodes.timeout.async_session", return_value=mock_session_ctx),
            patch("src.agent.nodes.timeout.JobService", return_value=mock_job_svc),
            patch("src.agent.nodes.timeout.TagService", return_value=mock_tag_svc),
        ):
            result = await timeout_node(state)

        # Segundo timeout nao envia mensagem ao lead
        mock_send.assert_not_called()

        assert result["tags"].get("lead_timeout") == "true"
        assert result["timeout_count"] == 2
        assert result["awaiting_response"] is False
        assert result["current_node"] == "timeout"

    @pytest.mark.asyncio
    async def test_higher_timeout_count_also_triggers_second_flow(self):
        from src.agent.nodes.timeout import timeout_node

        # timeout_count=2 ou mais tambem deve seguir o fluxo de "lead inativo"
        state = make_state(timeout_count=2, lead_id=None, tags={})

        with (
            patch(
                "src.agent.nodes.timeout.send_whatsapp_message", new_callable=AsyncMock
            ) as mock_send,
        ):
            result = await timeout_node(state)

        mock_send.assert_not_called()
        assert result["tags"].get("lead_timeout") == "true"

    @pytest.mark.asyncio
    async def test_first_timeout_uses_default_name_when_no_lead_name(self):
        from src.agent.nodes.timeout import timeout_node

        state = make_state(timeout_count=0, lead_name=None, lead_id=None)

        with (
            patch(
                "src.agent.nodes.timeout.send_whatsapp_message", new_callable=AsyncMock
            ) as mock_send,
        ):
            result = await timeout_node(state)

        sent_msg = mock_send.call_args[0][1]
        assert "voce" in sent_msg.lower()

    @pytest.mark.asyncio
    async def test_second_timeout_uses_region_from_tags(self):
        from src.agent.nodes.timeout import timeout_node

        state = make_state(
            timeout_count=1,
            lead_id="00000000-0000-0000-0000-000000000003",
            tags={"localizacao": "Despraiado"},
        )

        mock_job_svc = AsyncMock()
        mock_tag_svc = AsyncMock()
        mock_session = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.agent.nodes.timeout.send_whatsapp_message", new_callable=AsyncMock),
            patch("src.agent.nodes.timeout.async_session", return_value=mock_session_ctx),
            patch("src.agent.nodes.timeout.JobService", return_value=mock_job_svc),
            patch("src.agent.nodes.timeout.TagService", return_value=mock_tag_svc),
        ):
            result = await timeout_node(state)

        # Verifica que schedule_after foi chamado com o payload correto
        mock_job_svc.schedule_after.assert_called_once()
        call_kwargs = mock_job_svc.schedule_after.call_args
        assert call_kwargs[1]["payload"]["region"] == "Despraiado"


# ---------------------------------------------------------------------------
# Testes do reengagement_node
# ---------------------------------------------------------------------------


class TestReengagementNode:
    @pytest.mark.asyncio
    async def test_resets_timeout_count(self):
        from src.agent.nodes.reengagement import reengagement_node

        state = make_state(timeout_count=2)
        result = await reengagement_node(state)

        assert result["timeout_count"] == 0
        assert result["awaiting_response"] is False
        assert result["current_node"] == "reengagement"

    @pytest.mark.asyncio
    async def test_works_with_any_timeout_count(self):
        from src.agent.nodes.reengagement import reengagement_node

        for count in (0, 1, 2, 5):
            state = make_state(timeout_count=count)
            result = await reengagement_node(state)
            assert result["timeout_count"] == 0


# ---------------------------------------------------------------------------
# Testes dos prompts de reengajamento
# ---------------------------------------------------------------------------


class TestReengagementPrompts:
    def test_reengagement_24h_format(self):
        from src.agent.prompts.reengagement import REENGAGEMENT_24H

        msg = REENGAGEMENT_24H.format(name="Ana", region="Despraiado")
        assert "Ana" in msg
        assert "Despraiado" in msg

    def test_reengagement_7d_format(self):
        from src.agent.prompts.reengagement import REENGAGEMENT_7D

        msg = REENGAGEMENT_7D.format(name="Carlos", region="Cuiaba")
        assert "Carlos" in msg

    def test_timeout_message_format(self):
        from src.agent.prompts.reengagement import TIMEOUT_MESSAGE

        msg = TIMEOUT_MESSAGE.format(name="Lucia")
        assert "Lucia" in msg

    def test_nurture_prompts_exist_and_format(self):
        from src.agent.prompts.reengagement import NURTURE_30D, NURTURE_60D, NURTURE_90D

        for template in (NURTURE_30D, NURTURE_60D, NURTURE_90D):
            assert "{name}" in template
            assert "{region}" in template

            formatted = template.format(name="Teste", region="Cuiaba")
            assert "Teste" in formatted
            assert "Cuiaba" in formatted
