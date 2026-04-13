#!/usr/bin/env python
"""
Script de ingestão da base de conhecimento na vector store.

Uso:
    python scripts/ingest_knowledge.py
    python scripts/ingest_knowledge.py --no-clear   # sem limpar a coleção antes

Documentos aceitos: .docx e .pdf
"""
import argparse
import sys
from pathlib import Path

# Garante que src/ esteja no path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.knowledge.ingest import ingest_document

# Adicione aqui os documentos da base de conhecimento (docx ou pdf).
# O primeiro da lista limpa a coleção; os demais são acumulativos.
KNOWLEDGE_DOCS = [
    "data/knowledge_v2.pdf",   # Base de Conhecimento v2.0 (PDF preferencial)
    "data/knowledge.docx",     # Fallback: versão anterior em DOCX
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestão de documentos na vector store")
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Não limpar a coleção antes de inserir (pode gerar duplicatas)",
    )
    args = parser.parse_args()
    clear = not args.no_clear

    base_dir = Path(__file__).resolve().parents[1]
    total = 0
    ingested_any = False

    for rel_path in KNOWLEDGE_DOCS:
        full_path = base_dir / rel_path
        if not full_path.exists():
            print(f"[AVISO] Arquivo não encontrado, pulando: {rel_path}")
            continue
        n = ingest_document(str(full_path), clear=clear)
        print(f"[OK] Ingeridos {n} chunks de {rel_path}")
        total += n
        clear = False  # limpa apenas na primeira iteração
        ingested_any = True

    if not ingested_any:
        print("[ERRO] Nenhum documento encontrado. Verifique os caminhos em KNOWLEDGE_DOCS.")
        sys.exit(1)

    print(f"\nTotal: {total} chunks inseridos na vector store.")


if __name__ == "__main__":
    main()
