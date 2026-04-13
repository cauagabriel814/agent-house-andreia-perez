import logging
import sys

from src.config.settings import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Loggers de bibliotecas que devem ser silenciados (WARNING ou acima)
_NOISY_LOGGERS = (
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "sqlalchemy.dialects",
    "aio_pika",
    "aiormq",
    "httpx",
    "httpcore",
    "openai",
    "openai._base_client",
    "asyncio",
    "watchfiles",
    "uvicorn.access",
)


def setup_logger(name: str = "andreia") -> logging.Logger:
    """Configura logging da aplicacao.

    - Root logger recebe nosso handler para que QUALQUER modulo usando
      ``logging.getLogger(__name__)`` saia formatado.
    - Loggers de bibliotecas externas ficam em WARNING para nao poluir.
    - Nivel do app: INFO (mesmo com DEBUG=true no .env).
    """
    level = logging.INFO
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

    # --- Silenciar loggers verbosos ---
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # --- Root logger: handler unico para toda a aplicacao ---
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level)

    # --- Logger da aplicacao ---
    app_logger = logging.getLogger(name)
    app_logger.setLevel(level)
    app_logger.propagate = True

    return app_logger


logger = setup_logger()
