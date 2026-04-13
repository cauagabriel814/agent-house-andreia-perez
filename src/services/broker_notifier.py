"""
Broker Notifier Service - Envia notificacoes para corretores via WhatsApp (UAZAPI).

Formatos de mensagem por tipo (PLANNING.md Feature 17):
  corretor_urgente → LEAD QUENTE - SLA 2h (investidor/comprador/lancamento)
  corretor_padrao  → LEAD MORNO  - SLA 24h
  sistema          → LEAD FRIO   - Nutricao automatica
"""

from typing import Optional

from src.config.settings import settings
from src.db.models.notification import Notification
from src.services.uazapi import UazapiService
from src.utils.logger import logger


def _format_urgent(payload: dict, sla_hours: Optional[int]) -> str:
    """Formata mensagem de lead QUENTE/URGENTE para o corretor."""
    score = payload.get("score", "-")
    nome = payload.get("nome") or payload.get("name", "-")
    telefone = payload.get("phone", "-")
    email = payload.get("email", "-") or "-"
    tipo = payload.get("tipo_imovel") or payload.get("tipo", "-")
    regiao = payload.get("regiao", "-")
    budget = payload.get("budget") or payload.get("faixa_investimento", "-")
    visita = payload.get("visita") or payload.get("data_visita", "-")
    sla_label = f"{sla_hours} HORA" if sla_hours == 1 else f"{sla_hours} HORAS" if sla_hours else "-"
    pagamento = payload.get("pagamento", "")
    urgencia = payload.get("urgencia", "")

    linhas = [
        "🔥 *LEAD QUENTE - URGENTE*",
        f"📊 Score: *{score} pontos*",
        f"👤 Nome: {nome}",
        f"📱 Tel: {telefone}",
        f"📧 Email: {email}",
        f"🏠 Interesse: {tipo}",
        f"📍 Regiao: {regiao}",
        f"💰 Budget: R$ {budget}",
    ]
    if pagamento and pagamento != "-":
        linhas.append(f"💳 Pagamento: {pagamento}")
    if urgencia and urgencia != "-":
        linhas.append(f"⏳ Urgencia: {urgencia}")
    if visita and visita != "-":
        linhas.append(f"📅 Visita: {visita}")
    linhas.append(f"⏰ *SLA: {sla_label}*")

    return "\n".join(linhas)


def _format_padrao(payload: dict, sla_hours: Optional[int]) -> str:
    """Formata mensagem de lead MORNO para o corretor."""
    score = payload.get("score", "-")
    nome = payload.get("nome") or payload.get("name", "-")
    telefone = payload.get("phone", "-")
    tipo = payload.get("tipo_imovel") or payload.get("tipo", "-")
    regiao = payload.get("regiao", "-")
    selecao_data = payload.get("selecao_data") or payload.get("created_at", "-")
    sla_label = f"{sla_hours} HORAS" if sla_hours else "-"

    linhas = [
        "⚠️ *LEAD MORNO*",
        f"📊 Score: *{score} pontos*",
        f"👤 Nome: {nome}",
        f"📱 Tel: {telefone}",
    ]
    if tipo and tipo != "-":
        linhas.append(f"🏠 Perfil: {tipo}")
    if regiao and regiao != "-":
        linhas.append(f"📍 Regiao: {regiao}")
    if selecao_data and selecao_data != "-":
        linhas.append(f"📋 Selecao enviada em: {selecao_data}")
    linhas.append(f"⏰ *SLA: {sla_label}*")

    return "\n".join(linhas)


def _format_sistema(payload: dict) -> str:
    """Formata mensagem de lead FRIO para o corretor (nutricao automatica)."""
    nome = payload.get("nome") or payload.get("name", "-")
    telefone = payload.get("phone", "-")
    barreira = payload.get("barreira", "-")
    estrategia = payload.get("estrategia", "nutricao_automatica")

    estrategia_display = estrategia.replace("_", " ").title()
    barreira_display = barreira.replace("_", " ").title() if barreira != "-" else "-"

    linhas = [
        "❄️ *LEAD FRIO*",
        "🤖 Nutricao automatica ativa",
        f"👤 Nome: {nome}",
        f"📱 Tel: {telefone}",
        f"🚧 Barreira: {barreira_display}",
        f"📌 Estrategia: {estrategia_display}",
        "📅 *REVISAO: 30 DIAS*",
    ]

    return "\n".join(linhas)


def format_broker_message(notification: Notification) -> str:
    """
    Formata a mensagem de notificacao para o corretor com base no tipo.

    Tipos suportados:
      - corretor_urgente → lead quente (SLA 1-2h)
      - corretor_padrao  → lead morno  (SLA 24h)
      - sistema          → lead frio   (nutricao)
    """
    payload = notification.payload or {}
    ntype = notification.type
    sla = notification.sla_hours

    if ntype == "corretor_urgente":
        return _format_urgent(payload, sla)
    elif ntype == "corretor_padrao":
        return _format_padrao(payload, sla)
    elif ntype == "sistema":
        return _format_sistema(payload)
    else:
        # Fallback generico
        return (
            f"📬 *Notificacao Andreia*\n"
            f"Tipo: {ntype}\n"
            f"Lead: {payload.get('phone', '-')}\n"
            f"Payload: {payload}"
        )


class BrokerNotifierService:
    """
    Envia notificacoes formatadas para os corretores via WhatsApp.

    Os telefones dos corretores sao configurados em CORRETOR_PHONES no .env.
    """

    def __init__(self):
        self.uazapi = UazapiService()
        self.broker_phones = settings.corretor_phones_list
        self._enabled = bool(self.broker_phones)

    def _is_enabled(self) -> bool:
        if not self._enabled:
            logger.warning(
                "Nenhum telefone de corretor configurado (CORRETOR_PHONES). "
                "Notificacao nao enviada via WhatsApp."
            )
            return False
        return True

    async def dispatch(self, notification: Notification) -> list[dict]:
        """
        Formata e envia a notificacao para todos os corretores configurados.

        Returns:
            Lista de resultados de envio, um por corretor.
        """
        if not self._is_enabled():
            return [{"status": "skipped", "reason": "no_broker_phones_configured"}]

        message = format_broker_message(notification)
        results = []

        for phone in self.broker_phones:
            try:
                result = await self.uazapi.send_text_message(phone, message)
                logger.info(
                    "BrokerNotifier | Enviado | notification_id=%s | corretor=%s | type=%s",
                    notification.id,
                    phone,
                    notification.type,
                )
                results.append({"phone": phone, "status": "sent", "result": result})
            except Exception as exc:
                logger.error(
                    "BrokerNotifier | Falha ao enviar | notification_id=%s | corretor=%s | erro=%s",
                    notification.id,
                    phone,
                    exc,
                )
                results.append({"phone": phone, "status": "error", "reason": str(exc)})

        return results
