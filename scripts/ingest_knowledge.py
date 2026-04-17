#!/usr/bin/env python
"""
Script de ingestão da base de conhecimento no PostgreSQL (pgvector).

Uso:
    python scripts/ingest_knowledge.py
    python scripts/ingest_knowledge.py --no-clear   # sem apagar chunks existentes

O conteúdo é lido de src/knowledge/knowledge_base.py (KNOWLEDGE_TEXT).
"""
import argparse
import sys
from pathlib import Path

# Garante que src/ esteja no path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.knowledge.ingest import ingest_text
from src.knowledge.knowledge_base import KNOWLEDGE_TEXT


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestão de conhecimento no PostgreSQL (pgvector)")
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Não apagar chunks existentes antes de inserir (pode gerar duplicatas)",
    )
    args = parser.parse_args()
    clear = not args.no_clear

    if not KNOWLEDGE_TEXT:
        print("[ERRO] KNOWLEDGE_TEXT está vazio em src/knowledge/knowledge_base.py")
        sys.exit(1)

    n = ingest_text(KNOWLEDGE_TEXT, source="knowledge_base", clear=clear)
    print(f"[OK] {n} chunks inseridos na tabela knowledge_chunks.")


if __name__ == "__main__":
    main()
