"""
Script para inicializar o banco de dados.

USO:
  # Subir o Docker primeiro:
  docker-compose up -d

  # Rodar as migrations via Alembic (recomendado para producao):
  alembic upgrade head

  # OU criar as tabelas diretamente via SQLAlchemy (dev/testes):
  python scripts/init_db.py
"""
import asyncio
import sys
from pathlib import Path

# Garante que o projeto esta no path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.database import drop_db, init_db  # noqa: E402
from src.utils.logger import logger  # noqa: E402


async def main(drop: bool = False):
    if drop:
        logger.warning("Removendo todas as tabelas...")
        await drop_db()
        logger.info("Tabelas removidas.")

    logger.info("Criando tabelas...")
    await init_db()
    logger.info("Banco de dados inicializado com sucesso.")


if __name__ == "__main__":
    drop_first = "--drop" in sys.argv
    asyncio.run(main(drop=drop_first))
