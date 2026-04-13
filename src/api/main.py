import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Logger PRIMEIRO — configura niveis antes de qualquer outro import
from src.utils.logger import logger  # noqa: E402

from src.api.routes.auth import router as auth_router
from src.api.routes.chat import router as chat_router
from src.api.routes.health import router as health_router
from src.api.routes.metrics import router as metrics_router
from src.api.routes.properties_admin import router as properties_admin_router
from src.api.routes.test_chat import router as test_chat_router
from src.api.routes.users import router as users_router
from src.api.routes.webhook import router as webhook_router
from src.config.settings import settings
from src.queue.connection import close_rabbitmq_connection, setup_queues


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia ciclo de vida da aplicacao (startup/shutdown).

    A API e responsavel apenas por receber webhooks e publicar mensagens na fila.
    O processamento do agente (consumer + scheduler) roda no processo worker.py separado.
    """
    # --- LangSmith: ativar tracing via variaveis de ambiente ---
    if settings.langchain_tracing_v2 and settings.langchain_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        logger.info(
            "STARTUP | LangSmith tracing ativado | project=%s", settings.langchain_project
        )
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.info("STARTUP | LangSmith tracing desativado (LANGCHAIN_API_KEY nao configurado)")

    logger.info("Andreia API iniciando... (env=%s)", settings.app_env)

    # --- RabbitMQ: apenas declara as filas para o publisher funcionar ---
    try:
        await setup_queues()
        logger.info("STARTUP | Filas RabbitMQ declaradas")
    except Exception as exc:
        logger.error("STARTUP | Erro ao conectar RabbitMQ: %s", exc)

    yield

    logger.info("Andreia API encerrando...")
    await close_rabbitmq_connection()


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(chat_router)
app.include_router(test_chat_router)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(properties_admin_router)
