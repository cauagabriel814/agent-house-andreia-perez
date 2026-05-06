import asyncio

import httpx
from fastapi import APIRouter

from src.config.settings import settings
from src.jobs.scheduler import is_scheduler_running
from src.queue.connection import get_rabbitmq_connection
from src.queue.consumer import is_consumer_running

router = APIRouter()

# Estado do agente em memoria
_agent_running = True


async def _check_openai() -> dict:
    """Verifica se a chave OpenAI e valida e a conta tem creditos."""
    if not settings.openai_api_key:
        return {"ok": False, "reason": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
        if response.status_code == 200:
            return {"ok": True}
        if response.status_code in (401, 403):
            return {"ok": False, "reason": "invalid_key"}
        if response.status_code == 429:
            return {"ok": False, "reason": "quota_exceeded"}
        return {"ok": False, "reason": f"http_{response.status_code}"}
    except Exception as exc:
        return {"ok": False, "reason": f"unreachable ({exc.__class__.__name__})"}


async def _check_uazapi() -> dict:
    """Verifica se a instancia UAZAPI esta conectada."""
    if not settings.uazapi_base_url or not settings.uazapi_instance_id:
        return {"ok": False, "reason": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.uazapi_base_url}/instance/status",
                headers={
                    "token": settings.uazapi_instance_id,
                    "Accept": "application/json",
                },
            )
        if response.status_code == 200:
            data = response.json()
            state = (
                data.get("state")
                or data.get("status")
                or (data.get("instance") or {}).get("state")
                or {}
            )
            # state pode ser um dict: {"connected": True, "loggedIn": True, ...}
            if isinstance(state, dict):
                if state.get("connected") or state.get("loggedIn"):
                    return {"ok": True, "state": state}
                return {"ok": False, "reason": f"disconnected (state={state!r})"}
            # state pode ser uma string: "open", "connected", etc.
            if str(state).lower() in ("open", "connected"):
                return {"ok": True, "state": state}
            return {"ok": False, "reason": f"disconnected (state={state!r})"}
        return {"ok": False, "reason": f"http_{response.status_code}"}
    except Exception as exc:
        return {"ok": False, "reason": f"unreachable ({exc.__class__.__name__})"}


@router.get("/agent/readiness")
async def agent_readiness():
    """
    Verifica se todos os servicos externos estao operacionais:
    - Servidor (sempre ok se essa rota responde)
    - OpenAI (chave valida + conta com creditos)
    - UAZAPI (instancia conectada)

    Retorna status geral e lista dos servicos com problema.
    """
    openai_result, uazapi_result = await asyncio.gather(
        _check_openai(),
        _check_uazapi(),
    )

    services = {
        "server": {"ok": True},
        "openai": openai_result,
        "uazapi": uazapi_result,
    }

    issues = [name for name, result in services.items() if not result["ok"]]

    return {
        "status": "ok" if not issues else "degraded",
        "services": services,
        "issues": issues,
    }


@router.get("/health")
async def health_check():
    """Health check do sistema."""
    rabbitmq_ok = False
    try:
        conn = await get_rabbitmq_connection()
        rabbitmq_ok = not conn.is_closed
    except Exception:
        pass

    return {
        "status": "ok",
        "agent_running": _agent_running,
        "rabbitmq": "connected" if rabbitmq_ok else "disconnected",
        "consumer": "running" if is_consumer_running() else "stopped",
        "scheduler": "running" if is_scheduler_running() else "stopped",
    }


@router.post("/agent/stop")
async def stop_agent():
    """Pausar o agente."""
    global _agent_running
    _agent_running = False
    return {"status": "agent_stopped"}


@router.post("/agent/start")
async def start_agent():
    """Retomar o agente."""
    global _agent_running
    _agent_running = True
    return {"status": "agent_started"}


@router.get("/agent/status")
async def agent_status():
    """Status atual do agente."""
    return {
        "running": _agent_running,
        "scheduler": is_scheduler_running(),
    }
