from fastapi import APIRouter

from src.jobs.scheduler import is_scheduler_running
from src.queue.connection import get_rabbitmq_connection
from src.queue.consumer import is_consumer_running

router = APIRouter()

# Estado do agente em memoria
_agent_running = True


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
