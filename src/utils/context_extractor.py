"""
context_extractor.py — Extração proativa de contexto global.

Chamado no início de cada nó do agente para capturar qualquer informação
útil que o lead mencione, mesmo que seja resposta a uma pergunta diferente.
Assim o agente nunca pergunta de novo algo que o lead já disse.

Campos extraídos proativamente:
  - situacao_imovel   → pronto | lancamento
  - faixa_valor       → valor/faixa de investimento
  - lead_identificado → nome do lead
  - forma_pagamento   → à vista | financiamento | permuta ...
  - urgencia          → prazo/urgência para compra
"""

import json

from langchain_openai import ChatOpenAI

from src.config.settings import settings
from src.db.database import async_session
from src.services.tag_service import TagService
from src.utils.logger import logger

# ---------------------------------------------------------------------------
# Prompt único para extração de todos os campos em uma só chamada LLM
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = (
    "Analise a mensagem abaixo e extraia APENAS os campos que estão claramente mencionados.\n"
    "Retorne um JSON com os campos abaixo. Use null para campos não mencionados.\n\n"
    "Campos:\n"
    '- tipo_imovel: "pronto" (imóvel pronto/entrega imediata/já construído) | '
    '"lancamento" (lançamento/na planta/em construção) | null\n'
    "- faixa_valor: string com valor ou faixa de investimento mencionada | null\n"
    "- nome: primeiro nome do lead caso se identifique | null\n"
    "- forma_pagamento: forma de pagamento mencionada "
    "(financiamento, à vista, permuta, FGTS...) | null\n"
    "- urgencia: prazo ou urgência mencionada "
    "(ex: '3 meses', 'urgente', 'sem pressa') | null\n"
    "- prioridades: diferenciais/prioridades mencionados para o imóvel "
    "(ex: 'segurança 24h', 'lazer', 'localização', 'vista', 'privacidade') | null\n\n"
    "Mensagem: {message}\n\n"
    "Retorne SOMENTE o JSON válido, sem markdown ou explicações."
)

# Valores que indicam "não coletado ainda" — não sobrescrevem
_EMPTY_VALUES = {"nao informado", "nao_informado", "", "indefinido", "null", "none"}

# Mapeamento: chave no JSON extraído → tag salva no banco
_FIELD_TO_TAG = {
    "tipo_imovel":    "situacao_imovel",
    "faixa_valor":    "faixa_valor",
    "nome":           "lead_identificado",
    "forma_pagamento": "forma_pagamento",
    "urgencia":       "urgencia",
    "prioridades":    "prioridades",
}


def _tag_is_set(tags: dict, key: str) -> bool:
    """Retorna True se o tag já tem valor válido."""
    val = tags.get(key)
    return bool(val) and str(val).strip().lower() not in _EMPTY_VALUES


def _value_is_valid(value) -> bool:
    """Retorna True se o valor extraído é útil."""
    if value is None:
        return False
    return str(value).strip().lower() not in _EMPTY_VALUES


async def extract_context_from_message(
    message: str,
    tags: dict,
    lead_id=None,
) -> dict:
    """
    Extrai contexto útil da mensagem e atualiza as tags com campos ainda não coletados.

    Só dispara a chamada LLM se houver ao menos um campo ainda não preenchido.
    Retorna o dict de tags atualizado (nunca sobrescreve tags já definidas).
    """
    tags = dict(tags)

    # Se todos os campos já estão preenchidos, não faz nada
    fields_missing = [tag for tag in _FIELD_TO_TAG.values() if not _tag_is_set(tags, tag)]
    if not fields_missing:
        return tags

    try:
        llm = ChatOpenAI(
            model="gpt-5.4",
            temperature=0,
            api_key=settings.openai_api_key,
            timeout=20,
        )
        response = await llm.ainvoke(_EXTRACTION_PROMPT.format(message=message))
        content = response.content.strip()

        # Remove blocos markdown se presentes
        if content.startswith("```"):
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else content
            if content.startswith("json"):
                content = content[4:]

        extracted: dict = json.loads(content)

        for field_key, tag_key in _FIELD_TO_TAG.items():
            if _tag_is_set(tags, tag_key):
                continue  # já coletado — não sobrescreve

            value = extracted.get(field_key)
            if not _value_is_valid(value):
                continue

            str_value = str(value).strip()
            tags[tag_key] = str_value

            if lead_id:
                async with async_session() as session:
                    tag_svc = TagService(session)
                    await tag_svc.set_tag(lead_id, tag_key, str_value)

            logger.info(
                "CONTEXT | %s=%r extraído proativamente da mensagem", tag_key, str_value
            )

    except Exception as exc:
        logger.warning("CONTEXT | Falha na extração proativa (não crítico): %s", exc)

    return tags
