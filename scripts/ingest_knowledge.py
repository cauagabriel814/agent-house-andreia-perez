#!/usr/bin/env python
"""
Script de ingestão da base de conhecimento na vector store.

Uso:
    python scripts/ingest_knowledge.py
    python scripts/ingest_knowledge.py --no-clear   # sem limpar a coleção antes

Aceita texto inline (KNOWLEDGE_TEXT) ou arquivos .docx/.pdf (KNOWLEDGE_DOCS).
O texto inline tem prioridade. Os arquivos são usados como fallback.
"""
import argparse
import sys
from pathlib import Path

# Garante que src/ esteja no path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.knowledge.ingest import ingest_document, ingest_text

# ------------------------------------------------------------
# Base de conhecimento inline
# Edite aqui para atualizar as informações sem precisar de arquivo.
# ------------------------------------------------------------
KNOWLEDGE_TEXT = """
- Nós queremos que o cliente sempre marque uma visita pessoalmente a imobiliária pois acreditamos que o contato olho a olho ainda é muito forte para fechar vendas, mas caso o cliente queira fechar sem a visita não queremos força-lo. Dito isso logo abaixo ira o endereço da imobiliária

IMOBILIARIA CASA ANDREIA PEREZ

Endereço: Av. Presidente Marques, 522 - Santa Helena, Cuiabá - MT, 78045-008

Telefone da empresa: 65 99265-1348


- A maioria das construtoras que trabalhamos com ticket a partir de 200 mil reais até 400 mil reais possuem a possibilidade do uso do FGTS para facilitar a vida do cliente. Construtoras como MRV, Gerencial, Pacaembu e outras construtoras com imóveis neste ticket. A caixa consegue financiar até 80% do valor do imóvel mas tudo ira depender do relacionamento do cliente com o banco.

- Atendemos clientes das diversas faixas, desde minha casa minha vida até altíssimo padrão. Nós somos uma imobiliária que sempre busca corresponder ao que o cliente busca com a missão de conectar o cliente ao seu sonho e ao novo capítulo da sua história, por isso possuímos diversas construtoras parceiras mas cada uma focada em imóveis de valores diferentes por exemplo:

- São Benedito – imóveis a partir de 500.000 até 2.000.000
- Plaenge – focada em imóveis a partir de 800.000 até 4.000.000
- Abitte – focada no altíssimo padrão em condomínios horizontais a partir de 500.000 até 2.500.000
- GT urbanismo – focado em condomínios horizontais também a partir de 450.000 até 700.000
- Gerencial – imóveis a partir de 300.000 até 2.000.000
- MRV – imóveis a partir de 200.000 até 300.000 (trabalhando com FGTS e com programa minha casa minha vida)

Estes são nossos principais parceiros mas como mencionado antes sempre iremos querer que a IA direcione o cliente para um atendimento humano para o fechamento ou agendamento de uma visita à imobiliária. No caso de uma simulação ou consulta pedimos que aguarde um instante e que direcione para um dos corretores se responsabilizarem por estes assuntos.
""".strip()

# Arquivos de fallback (usados apenas se KNOWLEDGE_TEXT estiver vazio)
KNOWLEDGE_DOCS = [
    "data/knowledge_v2.pdf",
    "data/knowledge.docx",
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

    if KNOWLEDGE_TEXT:
        n = ingest_text(KNOWLEDGE_TEXT, source="knowledge_inline", clear=clear)
        print(f"[OK] Ingeridos {n} chunks do texto inline.")
        print(f"\nTotal: {n} chunks inseridos na vector store.")
        return

    # Fallback: arquivos
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
        clear = False
        ingested_any = True

    if not ingested_any:
        print("[ERRO] Nenhum documento encontrado. Verifique KNOWLEDGE_TEXT ou KNOWLEDGE_DOCS.")
        sys.exit(1)

    print(f"\nTotal: {total} chunks inseridos na vector store.")


if __name__ == "__main__":
    main()
