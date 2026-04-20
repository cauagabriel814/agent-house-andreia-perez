import uuid
from datetime import timedelta

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.fallback import (
    TECHNICAL_ERROR_MESSAGE,
    build_redirect_message,
    build_smart_redirect,
    get_last_bot_message,
    is_clarification,
    is_faq_question_async,
)
from src.agent.prompts.rental import (
    RENTAL_ASK_EMAIL,
    RENTAL_ASK_PERGUNTAS,
    RENTAL_ENCERRAMENTO,
    RENTAL_INITIAL,
    RENTAL_INTRO,
)
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.db.database import async_session
from src.services.job_service import JobService
from src.services.kommo_service import KommoService
from src.services.tag_service import TagService
from src.utils.logger import logger

_EXTRACTION_PROMPT = (
    "Extraia o(a) {field} da seguinte mensagem do lead de forma concisa. "
    "A mensagem pode ser transcrição de áudio: pode conter linguagem falada informal, "
    "ausência de pontuação, valores por extenso (ex: 'quinhentos mil' = R$500.000, "
    "'dois quartos' = 2 quartos, 'cem metros' = 100m²). Interprete com tolerância. "
    "Responda apenas com o valor extraido, sem explicacoes adicionais. "
    "Se a mensagem for uma pergunta, assunto completamente diferente, texto sem sentido, "
    "palavra aleatoria ou resposta claramente irrelevante para o campo solicitado, "
    "responda EXATAMENTE 'off_topic'. "
    "Se a informacao nao foi fornecida mas a mensagem e relevante ao contexto imobiliario, "
    "responda 'nao informado'.\n\n"
    "Mensagem: {message}"
)

_IS_EMAIL_PROMPT = (
    "Extraia o endereco de e-mail da seguinte mensagem. "
    "Responda apenas com o e-mail encontrado. "
    "Se nao houver e-mail valido, responda 'nao informado'.\n\n"
    "Mensagem: {message}"
)


async def _extract_field(message: str, field: str) -> str:
    """Usa LLM para extrair um campo especifico da resposta do lead."""
    llm = ChatOpenAI(
        model="gpt-5.4",
        temperature=0,
        api_key=settings.openai_api_key,
        timeout=30,
    )
    prompt = _EXTRACTION_PROMPT.format(field=field, message=message)
    response = await llm.ainvoke(prompt)
    return response.content.strip()


async def _extract_email(message: str) -> str:
    """Extrai e-mail da mensagem do lead."""
    llm = ChatOpenAI(
        model="gpt-5.4",
        temperature=0,
        api_key=settings.openai_api_key,
        timeout=30,
    )
    prompt = _IS_EMAIL_PROMPT.format(message=message)
    response = await llm.ainvoke(prompt)
    return response.content.strip()


async def _save_tag(lead_id: str | uuid.UUID | None, tags: dict, key: str, value: str) -> dict:
    """Persiste tag no banco e retorna o dict de tags atualizado."""
    tags_update = dict(tags)
    tags_update[key] = value
    if lead_id:
        async with async_session() as session:
            tag_svc = TagService(session)
            await tag_svc.set_tag(lead_id, key, value)
    return tags_update


def _is_off_topic(value: str) -> bool:
    """Mensagem completamente fora do contexto (off_topic)."""
    return value.strip().lower() == "off_topic"


def _is_missing(value: str) -> bool:
    """Campo relevante mas não fornecido (nao informado) — aceitar e seguir."""
    return value.strip().lower() in ("nao informado", "nao_informado")


async def rental_node(state: AgentState) -> dict:
    """
    Node: Fluxo de locacao (proprietario) - Feature 11.

    Qualifica proprietario que quer alugar seu imovel, coleta dados
    e envia proposta por email com follow-up agendado em 48h.

    Etapas (rastreadas por last_question):
      1. Primeira chamada (current_node != "rental")
             -> Envia RENTAL_INITIAL (apresenta servicos + pergunta tipo/regiao)
             -> last_question = "rental_dados"

      2. rental_dados: extrai tipo e regiao, faz perguntas importantes
             -> TAG: tipo_imovel_locacao, localizacao_imovel_locacao
             -> last_question = "rental_perguntas"

      3. rental_perguntas: extrai valor/ocupacao/reforma/experiencia, seta TAG principal, pede email
             -> TAG: valor_esperado_locacao, imovel_ocupado, precisa_reforma,
                     experiencia_locacao, proprietario_locacao
             -> last_question = "rental_email"

      4. rental_email: extrai email, agenda follow-up 48h, encerra fluxo
             -> TAG: email_lead
             -> Job: follow_up_48h
             -> TODO Feature 17: integrar Email Marketing + CRM
    """
    phone = state["phone"]
    try:
        return await _rental_node_impl(state)
    except Exception as exc:
        logger.exception("RENTAL | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("RENTAL | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", "rental"),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
            "tags": state.get("tags") or {},
            "reask_count": state.get("reask_count", 0),
        }


async def _rental_node_impl(state: AgentState) -> dict:
    phone = state["phone"]
    lead_id = state.get("lead_id")
    current_node = state.get("current_node", "")
    last_question = state.get("last_question")
    current_message = state.get("current_message", "")
    processed_content = state.get("processed_content")
    effective_message = processed_content or current_message
    tags = dict(state.get("tags") or {})
    kommo_contact_id = state.get("kommo_contact_id")
    kommo_lead_id = state.get("kommo_lead_id")
    reask_count = state.get("reask_count", 0)
    kommo = KommoService()
    last_bot_message = get_last_bot_message(state.get("messages") or [])

    # FAQ: lead perguntou sobre a empresa ou processos → encaminhar para FAQ
    if await is_faq_question_async(effective_message):
        logger.info("RENTAL | FAQ detectado em fluxo ativo | phone=%s", phone)
        return {
            "current_node": "faq",
            "last_question": last_question,
            "awaiting_response": True,
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
        }

    # Clarificação: lead pediu esclarecimento de uma pergunta já feita
    if last_question and is_clarification(effective_message):
        logger.info("RENTAL | Clarificacao detectada | lq=%s | phone=%s", last_question, phone)
        redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
        await send_whatsapp_message(phone, redirect_msg)
        return {
            "current_node": "rental",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "last_question": last_question,
            "awaiting_response": True,
            "reask_count": reask_count,
        }

    # ------------------------------------------------------------------
    # Etapa 1: Primeira chamada (vinda do router)
    # Nota: se last_question já tem prefixo "rental_", é retorno de FAQ — não reinicia.
    # ------------------------------------------------------------------
    if current_node != "rental" and not (last_question and last_question.startswith("rental_")):
        logger.info("RENTAL | Iniciando fluxo de locacao | phone=%s", phone)

        # Extrai tipo e regiao já da mensagem que ativou o fluxo
        tipo_init = await _extract_field(
            effective_message,
            "tipo ou estilo do imovel (casa, apartamento, cobertura, etc)",
        )
        regiao_init = await _extract_field(effective_message, "regiao ou bairro do imovel")

        if _is_off_topic(tipo_init) or _is_missing(tipo_init):
            tipo_init = "nao informado"
        if _is_off_topic(regiao_init) or _is_missing(regiao_init):
            regiao_init = "nao informado"

        if tipo_init != "nao informado":
            tags = await _save_tag(lead_id, tags, "tipo_imovel_locacao", tipo_init)
        if regiao_init != "nao informado":
            tags = await _save_tag(lead_id, tags, "localizacao_imovel_locacao", regiao_init)

        # Sempre envia o intro do serviço
        await send_whatsapp_message(phone, RENTAL_INTRO)

        if tipo_init != "nao informado" and regiao_init != "nao informado":
            # Ambos já capturados — pula direto para as perguntas
            logger.info(
                "RENTAL | Tipo=%r e Regiao=%r ja capturados na entrada | pulando para perguntas | phone=%s",
                tipo_init, regiao_init, phone,
            )
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            await send_whatsapp_message(phone, RENTAL_ASK_PERGUNTAS)
            return {
                "current_node": "rental",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "rental_perguntas",
                "reask_count": 0,
                "messages": [AIMessage(content=RENTAL_INTRO), AIMessage(content=RENTAL_ASK_PERGUNTAS)],
            }

        if tipo_init != "nao informado":
            msg_ask = "E em qual região ou bairro o imóvel fica?"
        elif regiao_init != "nao informado":
            msg_ask = "Qual é o tipo do imóvel? (casa, apartamento, cobertura...)"
        else:
            msg_ask = (
                "Pode me contar mais sobre seu imóvel? "
                "Qual o tipo (casa, apartamento, cobertura...) e em qual região fica?"
            )

        await send_whatsapp_message(phone, msg_ask)
        return {
            "current_node": "rental",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "rental_dados",
            "reask_count": 0,
            "messages": [AIMessage(content=RENTAL_INTRO), AIMessage(content=msg_ask)],
        }

    # ------------------------------------------------------------------
    # Etapa 2: Capturou tipo/regiao, fazer perguntas importantes
    # ------------------------------------------------------------------
    if last_question == "rental_dados":
        logger.info("RENTAL | Capturando tipo e regiao | phone=%s", phone)

        tipo = await _extract_field(
            effective_message,
            "tipo ou estilo do imovel (casa, apartamento, cobertura, etc)",
        )
        regiao = await _extract_field(effective_message, "regiao ou bairro do imovel")

        # Só redireciona se AMBOS os campos são completamente off_topic
        if _is_off_topic(tipo) and _is_off_topic(regiao):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "rental",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }

        # Normaliza campos não fornecidos
        if _is_off_topic(tipo) or _is_missing(tipo):
            tipo = "nao informado"
        if _is_off_topic(regiao) or _is_missing(regiao):
            regiao = "nao informado"

        # Mescla com dados parciais já salvos (caso seja segunda passagem)
        if tipo == "nao informado" and tags.get("tipo_imovel_locacao"):
            tipo = tags["tipo_imovel_locacao"]
        if regiao == "nao informado" and tags.get("localizacao_imovel_locacao"):
            regiao = tags["localizacao_imovel_locacao"]

        # Salva o que temos até agora
        tags = await _save_tag(lead_id, tags, "tipo_imovel_locacao", tipo)
        tags = await _save_tag(lead_id, tags, "localizacao_imovel_locacao", regiao)

        # Pergunta especifica pelo campo faltante (apenas na primeira tentativa)
        if reask_count == 0:
            if tipo == "nao informado" and regiao != "nao informado":
                msg = "Entendido! E qual é o tipo do imóvel? (casa, apartamento, cobertura...)"
                logger.info("RENTAL | Tipo faltando, pedindo especificamente | phone=%s", phone)
                await send_whatsapp_message(phone, msg)
                return {
                    "current_node": "rental",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": "rental_dados",
                    "awaiting_response": True,
                    "reask_count": 1,
                    "messages": [AIMessage(content=msg)],
                }
            if regiao == "nao informado" and tipo != "nao informado":
                msg = "E em qual região ou bairro o imóvel fica?"
                logger.info("RENTAL | Regiao faltando, pedindo especificamente | phone=%s", phone)
                await send_whatsapp_message(phone, msg)
                return {
                    "current_node": "rental",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": "rental_dados",
                    "awaiting_response": True,
                    "reask_count": 1,
                    "messages": [AIMessage(content=msg)],
                }

        logger.info(
            "RENTAL | Tipo=%r | Regiao=%r | phone=%s", tipo, regiao, phone
        )
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, RENTAL_ASK_PERGUNTAS)
        return {
            "current_node": "rental",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "rental_perguntas",
            "reask_count": 0,
            "messages": [AIMessage(content=RENTAL_ASK_PERGUNTAS)],
        }

    # ------------------------------------------------------------------
    # Etapa 3: Capturou perguntas, setar TAG principal e pedir email
    # ------------------------------------------------------------------
    if last_question == "rental_perguntas":
        logger.info(
            "RENTAL | Capturando perguntas e setando TAG proprietario_locacao | phone=%s",
            phone,
        )

        valor = await _extract_field(effective_message, "valor de locacao esperado pelo proprietario")
        ocupado = await _extract_field(
            effective_message,
            "se o imovel esta ocupado no momento (sim, nao ou nao informado)",
        )
        reforma = await _extract_field(
            effective_message,
            "se o imovel precisa de reforma (sim, nao ou nao informado)",
        )
        experiencia = await _extract_field(
            effective_message,
            "experiencia anterior do proprietario com locacao do imovel",
        )

        # Só redireciona se TODOS os campos são completamente off_topic
        all_off_topic = all(_is_off_topic(v) for v in [valor, ocupado, reforma, experiencia])
        if all_off_topic and reask_count < 2:
            redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
            await send_whatsapp_message(phone, redirect_msg)
            return {
                "current_node": "rental",
                "tags": tags,
                "last_question": last_question,
                "awaiting_response": True,
                "reask_count": reask_count + 1,
            }

        # Normaliza campos não fornecidos
        if _is_off_topic(valor) or _is_missing(valor):
            valor = "nao informado"
        if _is_off_topic(ocupado) or _is_missing(ocupado):
            ocupado = "nao informado"
        if _is_off_topic(reforma) or _is_missing(reforma):
            reforma = "nao informado"
        if _is_off_topic(experiencia) or _is_missing(experiencia):
            experiencia = "nao informado"

        # Mescla com dados parciais já salvos (caso seja segunda passagem)
        if valor == "nao informado" and tags.get("valor_esperado_locacao"):
            valor = tags["valor_esperado_locacao"]
        if ocupado == "nao informado" and tags.get("imovel_ocupado"):
            ocupado = tags["imovel_ocupado"]
        if reforma == "nao informado" and tags.get("precisa_reforma"):
            reforma = tags["precisa_reforma"]
        if experiencia == "nao informado" and tags.get("experiencia_locacao"):
            experiencia = tags["experiencia_locacao"]

        tags = await _save_tag(lead_id, tags, "valor_esperado_locacao", valor)
        tags = await _save_tag(lead_id, tags, "imovel_ocupado", ocupado)
        tags = await _save_tag(lead_id, tags, "precisa_reforma", reforma)
        tags = await _save_tag(lead_id, tags, "experiencia_locacao", experiencia)

        # Pergunta pelos campos faltando (apenas na primeira tentativa)
        if reask_count == 0:
            perguntas_faltando = []
            if valor == "nao informado":
                perguntas_faltando.append("• Qual o valor de locação esperado?")
            if ocupado == "nao informado":
                perguntas_faltando.append("• O imóvel está ocupado no momento?")
            if reforma == "nao informado":
                perguntas_faltando.append("• O imóvel precisa de alguma reforma?")

            algum_respondido = any(v != "nao informado" for v in [valor, ocupado, reforma, experiencia])

            if perguntas_faltando and algum_respondido:
                # Alguns campos respondidos, outros faltando — pede especificamente
                msg = "Obrigado! Só preciso de mais algumas informações:\n" + "\n".join(perguntas_faltando)
                logger.info(
                    "RENTAL | Campos faltando, pedindo especificamente | phone=%s | faltando=%s",
                    phone,
                    perguntas_faltando,
                )
                await send_whatsapp_message(phone, msg)
                return {
                    "current_node": "rental",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "awaiting_response": True,
                    "last_question": "rental_perguntas",
                    "reask_count": 1,
                    "messages": [AIMessage(content=msg)],
                }

            if perguntas_faltando and not algum_respondido:
                # Nenhum campo respondido — redireciona com as perguntas originais
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                logger.info(
                    "RENTAL | Nenhum campo respondido, redirecionando | phone=%s",
                    phone,
                )
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "rental",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "awaiting_response": True,
                    "last_question": "rental_perguntas",
                    "reask_count": 1,
                    "messages": [AIMessage(content=redirect_msg)],
                }

        tags = await _save_tag(lead_id, tags, "proprietario_locacao", "true")

        logger.info(
            "RENTAL | Valor=%r | Ocupado=%r | Reforma=%r | phone=%s",
            valor,
            ocupado,
            reforma,
            phone,
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, RENTAL_ASK_EMAIL)
        return {
            "current_node": "rental",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "rental_email",
            "reask_count": 0,
            "messages": [AIMessage(content=RENTAL_ASK_EMAIL)],
        }

    # ------------------------------------------------------------------
    # Etapa 4: Capturou email, agendar follow-up e encerrar
    # ------------------------------------------------------------------
    if last_question == "rental_email":
        logger.info("RENTAL | Capturando email e encerrando fluxo | phone=%s", phone)

        email = await _extract_email(effective_message)
        tags = await _save_tag(lead_id, tags, "email_lead", email)

        if lead_id:
            async with async_session() as session:
                job_svc = JobService(session)
                await job_svc.schedule_after(
                    lead_id=lead_id,
                    job_type="follow_up_48h",
                    delay=timedelta(hours=48),
                    payload={"phone": phone, "email": email},
                )
            logger.info(
                "RENTAL | Follow-up 48h agendado | phone=%s | lead_id=%s",
                phone,
                lead_id,
            )

        logger.info(
            "RENTAL | Email=%r | phone=%s | lead_id=%s",
            email,
            phone,
            lead_id,
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        stage_id = settings.kommo_stage_map_dict.get("proposta_enviada")
        if stage_id and kommo_lead_id:
            await kommo.update_lead_stage(kommo_lead_id, stage_id)

        await send_whatsapp_message(phone, RENTAL_ENCERRAMENTO)
        return {
            "current_node": "rental",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
            "reask_count": 0,
            "messages": [AIMessage(content=RENTAL_ENCERRAMENTO)],
        }

    # ------------------------------------------------------------------
    # Fallback: estado desconhecido - reiniciar etapa de dados
    # ------------------------------------------------------------------
    logger.warning(
        "RENTAL | Estado desconhecido last_question=%r | phone=%s", last_question, phone
    )
    await send_whatsapp_message(phone, RENTAL_INITIAL)
    return {
        "current_node": "rental",
        "awaiting_response": True,
        "last_question": "rental_dados",
        "reask_count": 0,
        "messages": [AIMessage(content=RENTAL_INITIAL)],
    }
