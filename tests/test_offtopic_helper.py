"""Testes do helper de off-topic com LLM."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.prompts.fallback import build_smart_redirect


@pytest.mark.asyncio
async def test_smart_redirect_uses_llm_response():
    fake_response = MagicMock()
    fake_response.content = (
        "Boa pergunta! Atendemos sim. Me conta, qual a regiao do seu imovel?"
    )

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=fake_response)

    with patch(
        "src.agent.prompts.fallback.ChatOpenAI", return_value=mock_llm
    ):
        result = await build_smart_redirect(
            "voces atendem em Jundiai?", "sale_regiao"
        )

    assert "regiao" in result.lower() or "imovel" in result.lower()
    mock_llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_smart_redirect_fallback_on_llm_error():
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("timeout"))

    with patch(
        "src.agent.prompts.fallback.ChatOpenAI", return_value=mock_llm
    ):
        result = await build_smart_redirect("qualquer coisa", "sale_regiao")

    # Cai no build_redirect_message seco
    assert "regi" in result.lower()
    assert "😊" in result


@pytest.mark.asyncio
async def test_smart_redirect_fallback_on_empty_llm_response():
    fake_response = MagicMock()
    fake_response.content = ""

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=fake_response)

    with patch(
        "src.agent.prompts.fallback.ChatOpenAI", return_value=mock_llm
    ):
        result = await build_smart_redirect("teste", "buyer_tipo")

    # Fallback seco do build_redirect_message usa o label de buyer_tipo
    assert "pronto" in result.lower() or "preciso" in result.lower()
