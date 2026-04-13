from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.nodes.greeting import _build_interest_from_tags, greeting_node
from src.agent.prompts.greeting import (
    GREETING_NEW_LEAD,
    GREETING_OUT_OF_HOURS,
    GREETING_RECURRING_LEAD,
)
from src.utils.datetime_utils import is_business_hours


# ---------------------------------------------------------------------------
# Testes de is_business_hours
# ---------------------------------------------------------------------------


def test_business_hours_weekday():
    dt = datetime(2026, 3, 23, 10, 0)  # Segunda 10h
    assert is_business_hours(dt) is True


def test_outside_business_hours_weekday():
    dt = datetime(2026, 3, 23, 20, 0)  # Segunda 20h
    assert is_business_hours(dt) is False


def test_sunday_always_outside():
    dt = datetime(2026, 3, 22, 10, 0)  # Domingo 10h
    assert is_business_hours(dt) is False


def test_saturday_within_hours():
    dt = datetime(2026, 3, 28, 10, 0)  # Sabado 10h
    assert is_business_hours(dt) is True


def test_saturday_outside_hours():
    dt = datetime(2026, 3, 28, 14, 0)  # Sabado 14h
    assert is_business_hours(dt) is False


# ---------------------------------------------------------------------------
# Testes de _build_interest_from_tags
# ---------------------------------------------------------------------------


def test_build_interest_venda():
    assert _build_interest_from_tags({"proprietario_venda": "true"}) == "venda de imovel"


def test_build_interest_locacao():
    assert _build_interest_from_tags({"proprietario_locacao": "true"}) == "locacao de imovel"


def test_build_interest_permuta():
    assert _build_interest_from_tags({"lead_permuta": "true"}) == "permuta de imovel"


def test_build_interest_investidor_yield():
    tags = {"investidor_yield": "true", "lead_tipo_imovel": "apartamento"}
    assert _build_interest_from_tags(tags) == "investimento em apartamento"


def test_build_interest_investidor_valorizacao_sem_tipo():
    tags = {"investidor_valorizacao": "true"}
    assert _build_interest_from_tags(tags) == "investimento em imovel"


def test_build_interest_tipo_imovel_fallback():
    assert _build_interest_from_tags({"lead_tipo_imovel": "cobertura"}) == "cobertura"


def test_build_interest_sem_tags():
    assert _build_interest_from_tags({}) == "imoveis de alto padrao"


# ---------------------------------------------------------------------------
# Testes do greeting_node
# ---------------------------------------------------------------------------

_BASE_STATE = {
    "phone": "5565999999999",
    "lead_id": "00000000-0000-0000-0000-000000000001",
    "is_recurring": False,
    "lead_name": None,
    "tags": {},
    "messages": [],
    "conversation_history": [],
}


@pytest.mark.asyncio
@patch("src.agent.nodes.greeting.is_business_hours", return_value=False)
@patch("src.agent.nodes.greeting.send_whatsapp_message", new_callable=AsyncMock)
@patch("src.agent.nodes.greeting.async_session")
async def test_greeting_fora_do_horario(mock_session_ctx, mock_send, mock_bh):
    """Fora do horario: envia mensagem padrao e adiciona tag lead_fora_horario."""
    # Configura o context manager da sessao
    mock_session = AsyncMock()
    mock_tag_svc = AsyncMock()
    mock_tag_svc.set_tag = AsyncMock()
    mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("src.agent.nodes.greeting.TagService", return_value=mock_tag_svc):
        result = await greeting_node(dict(_BASE_STATE))

    mock_send.assert_called_once_with("5565999999999", GREETING_OUT_OF_HOURS)
    assert result["business_hours"] is False
    assert result["current_node"] == "greeting"
    assert result["tags"].get("lead_fora_horario") == "true"
    assert len(result["messages"]) == 1
    assert result["messages"][0].content == GREETING_OUT_OF_HOURS


@pytest.mark.asyncio
@patch("src.agent.nodes.greeting.is_business_hours", return_value=True)
@patch("src.agent.nodes.greeting.send_whatsapp_message", new_callable=AsyncMock)
async def test_greeting_lead_novo(mock_send, mock_bh):
    """Dentro do horario com lead novo: envia saudacao padrao de boas-vindas."""
    result = await greeting_node(dict(_BASE_STATE))

    mock_send.assert_called_once_with("5565999999999", GREETING_NEW_LEAD)
    assert result["business_hours"] is True
    assert result["current_node"] == "greeting"
    assert result["messages"][0].content == GREETING_NEW_LEAD


@pytest.mark.asyncio
@patch("src.agent.nodes.greeting.is_business_hours", return_value=True)
@patch("src.agent.nodes.greeting.send_whatsapp_message", new_callable=AsyncMock)
@patch("src.agent.nodes.greeting.async_session")
async def test_greeting_lead_recorrente_com_dados(mock_session_ctx, mock_send, mock_bh):
    """Lead recorrente com tags historicas: envia saudacao personalizada."""
    mock_session = AsyncMock()
    mock_tag_svc = AsyncMock()
    mock_tag_svc.as_dict = AsyncMock(
        return_value={
            "investidor_yield": "true",
            "lead_tipo_imovel": "apartamento",
            "localizacao": "Jardim Italia",
        }
    )
    mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

    state = {**_BASE_STATE, "is_recurring": True, "lead_name": "Carlos"}

    with patch("src.agent.nodes.greeting.TagService", return_value=mock_tag_svc):
        result = await greeting_node(state)

    expected_msg = GREETING_RECURRING_LEAD.format(
        name="Carlos",
        interest="investimento em apartamento",
        region="Jardim Italia",
    )
    mock_send.assert_called_once_with("5565999999999", expected_msg)
    assert result["business_hours"] is True
    assert result["current_node"] == "greeting"
    assert result["messages"][0].content == expected_msg


@pytest.mark.asyncio
@patch("src.agent.nodes.greeting.is_business_hours", return_value=True)
@patch("src.agent.nodes.greeting.send_whatsapp_message", new_callable=AsyncMock)
@patch("src.agent.nodes.greeting.async_session")
async def test_greeting_lead_recorrente_sem_tags(mock_session_ctx, mock_send, mock_bh):
    """Lead recorrente sem tags: usa nome + interesse e regiao padrao (Cuiaba)."""
    mock_session = AsyncMock()
    mock_tag_svc = AsyncMock()
    mock_tag_svc.as_dict = AsyncMock(return_value={})
    mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

    state = {**_BASE_STATE, "is_recurring": True, "lead_name": "Ana"}

    with patch("src.agent.nodes.greeting.TagService", return_value=mock_tag_svc):
        result = await greeting_node(state)

    expected_msg = GREETING_RECURRING_LEAD.format(
        name="Ana",
        interest="imoveis de alto padrao",
        region="Cuiaba",
    )
    mock_send.assert_called_once_with("5565999999999", expected_msg)
    assert result["current_node"] == "greeting"
