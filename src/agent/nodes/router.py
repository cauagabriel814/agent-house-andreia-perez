from langchain_openai import ChatOpenAI

from src.agent.prompts.active_listen import INTENT_CLASSIFICATION_PROMPT
from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.services.kommo_service import KommoService
from src.utils.logger import logger

_VALID_INTENTS = {
    "venda",
    "locacao",
    "investidor",
    "permuta",
    "interesse_especifico",
    "faq",
    "clarificacao",
    "generico",
}

# Intencoes que representam fluxos especificos de qualificacao
_FLOW_INTENTS = {"venda", "locacao", "investidor", "permuta", "interesse_especifico"}

# Descricao humana de cada intencao para a mensagem de transicao
_INTENT_LABEL = {
    "venda": "vender seu imóvel",
    "locacao": "colocar seu imóvel para locação",
    "investidor": "investir em imóveis",
    "permuta": "fazer uma permuta de imóvel",
    "interesse_especifico": "comprar ou alugar um imóvel específico",
}


def _build_context(state: AgentState) -> str:
    """Constroi string de contexto com o historico recente da conversa."""
    history = state.get("conversation_history") or []
    recent = history[-6:] if len(history) > 6 else history
    lines = []
    for entry in recent:
        role = "Lead" if entry.get("direction") == "in" else "Marina"
        content = entry.get("processed_content") or entry.get("raw_content") or ""
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "Sem historico anterior"


async def router_node(state: AgentState) -> dict:
    """
    Node: Roteamento de intencao - usa LLM para classificar a intencao do lead.

    Detecta uma das seguintes intencoes:
    - venda: lead quer vender sua propriedade
    - locacao: lead quer colocar imovel para locacao
    - investidor: lead quer investir em imoveis
    - permuta: lead quer permutar imovel
    - interesse_especifico: lead buscando imovel especifico para comprar/morar
    - faq: lead tem uma duvida pontual
    - generico: intencao nao identificada claramente

    Quando o lead troca de fluxo especifico (ex: venda -> permuta), envia
    mensagem de transicao reconhecendo a mudanca antes de seguir para o novo fluxo.

    Fluxo:
        router --> [route_by_intent] --> generic | faq | sale | rental | investor | exchange | specific
    """
    phone = state["phone"]
    try:
        return await _router_node_impl(state)
    except Exception as exc:
        logger.exception("ROUTER | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("ROUTER | Falha ao enviar fallback | phone=%s", phone)
        # Fallback seguro: tratar como intenção genérica para não travar o fluxo
        return {
            "current_node": "router",
            "detected_intent": "generico",
            "previous_intent": None,
        }


async def _router_node_impl(state: AgentState) -> dict:
    phone = state["phone"]
    lead_name = state.get("lead_name") or "você"
    current_message = state.get("current_message", "")
    processed_content = state.get("processed_content")
    effective_message = processed_content or current_message
    context = _build_context(state)
    existing_intent = state.get("detected_intent")
    kommo_lead_id = state.get("kommo_lead_id")

    logger.info("ROUTER | Classificando intencao | phone=%s", phone)

    llm = ChatOpenAI(
        model="gpt-5.4",
        temperature=0,
        api_key=settings.openai_api_key,
        timeout=30,
    )

    prompt = INTENT_CLASSIFICATION_PROMPT.format(
        message=effective_message,
        context=context,
    )

    response = await llm.ainvoke(prompt)
    raw_intent = response.content.strip().lower()

    # Normaliza: pega apenas a primeira palavra/token caso o LLM retorne algo extra
    first_token = raw_intent.split()[0] if raw_intent.split() else "generico"
    intent = first_token.strip("\"'.,;:")

    if intent not in _VALID_INTENTS:
        logger.warning(
            "ROUTER | Intencao desconhecida: %r -> usando 'generico' | phone=%s",
            raw_intent,
            phone,
        )
        intent = "generico"

    # ------------------------------------------------------------------
    # Transicao de fluxo: lead muda de um fluxo especifico para outro
    # ------------------------------------------------------------------
    previous_intent = None
    if (
        existing_intent in _FLOW_INTENTS
        and intent in _FLOW_INTENTS
        and intent != existing_intent
    ):
        previous_intent = existing_intent
        from_label = _INTENT_LABEL[existing_intent]
        to_label = _INTENT_LABEL[intent]

        transition_msg = (
            f"Entendido, {lead_name}! Vi que você estava interessado em {from_label}. "
            f"Agora você quer {to_label}, certo? "
            f"Sem problema, vou te ajudar nesse novo caminho!"
        )
        await send_whatsapp_message(phone, transition_msg)

        logger.info(
            "ROUTER | Transicao de fluxo: %s -> %s | phone=%s",
            existing_intent,
            intent,
            phone,
        )

    logger.info(
        "ROUTER | Intencao detectada: %s | phone=%s | message=%r",
        intent,
        phone,
        effective_message[:80],
    )

    # Atualiza estágio KOMMO para "em_qualificacao" quando lead entra em fluxo específico
    if intent in _FLOW_INTENTS and kommo_lead_id:
        try:
            stage_id = settings.kommo_stage_map_dict.get("em_qualificacao")
            if stage_id:
                kommo = KommoService()
                await kommo.update_lead_stage(kommo_lead_id, stage_id)
        except Exception:
            logger.exception("ROUTER | Falha ao atualizar estágio KOMMO | phone=%s", phone)

    return {
        "current_node": "router",
        "detected_intent": intent,
        "previous_intent": previous_intent,
    }
