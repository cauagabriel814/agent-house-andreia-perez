"""
Conftest para testes de jobs.

Mocka o modulo src.agent.runner antes de qualquer importacao para evitar
o carregamento da cadeia pesada: runner -> graph -> nodes -> langchain_openai.
Os testes de scheduler nao precisam do runner real (usam mocks proprios).
"""

import sys
from unittest.mock import AsyncMock, MagicMock

# Registra o mock ANTES que qualquer teste tente importar src.jobs.scheduler,
# que por sua vez importa src.agent.runner no nivel de modulo.
_mock_runner = MagicMock()
_mock_runner.run_agent_for_timeout = AsyncMock()

sys.modules.setdefault("src.agent.runner", _mock_runner)
