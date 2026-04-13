"""
Email Service - Envio de emails via SMTP (proposta de locacao, materiais, etc).
"""

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.config.settings import settings
from src.utils.logger import logger


class EmailService:
    """Servico de envio de emails via SMTP."""

    def __init__(self):
        self.smtp_host = settings.email_smtp_host
        self.smtp_port = settings.email_smtp_port
        self.smtp_user = settings.email_smtp_user
        self.smtp_password = settings.email_smtp_password
        self.from_address = settings.email_from or settings.email_smtp_user
        self.from_name = settings.email_from_name
        self._enabled = bool(self.smtp_user and self.smtp_password and self.from_address)

    def _is_enabled(self) -> bool:
        if not self._enabled:
            logger.warning("Email nao configurado (EMAIL_SMTP_USER ou EMAIL_SMTP_PASSWORD ausentes). Operacao ignorada.")
            return False
        return True

    @staticmethod
    def _clean_val(v: str, default: str = "Não informado") -> str:
        """Sanitiza valores de tags: trata off_topic, nao informado, None, etc."""
        if not v:
            return default
        if v.strip().lower() in ("nao informado", "nao_informado", "off_topic"):
            return default
        return v.strip()

    def _build_message(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
    ) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_address}>"
        msg["To"] = to

        if body_text:
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        return msg

    def _send_sync(self, msg: MIMEMultipart, to: str) -> bool:
        """Envio sincrono via SMTP com STARTTLS."""
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_address, to, msg.as_string())
            return True
        except smtplib.SMTPException as exc:
            logger.error("Email | Erro SMTP | to=%s | erro=%s", to, exc)
            return False
        except Exception as exc:
            logger.error("Email | Falha ao enviar | to=%s | erro=%s", to, exc)
            return False

    async def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
    ) -> dict:
        """Envia um email. Executa SMTP em thread para nao bloquear o loop asyncio."""
        if not self._is_enabled():
            return {"status": "skipped", "reason": "email_not_configured"}

        msg = self._build_message(to, subject, body_html, body_text)
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, self._send_sync, msg, to)

        if success:
            logger.info("Email | Enviado | to=%s | subject=%s", to, subject)
            return {"status": "sent", "to": to, "subject": subject}
        return {"status": "error", "to": to}

    async def send_rental_proposal(self, to: str, lead_name: str, property_data: Optional[dict] = None) -> dict:
        """Envia proposta de parceria de locacao para proprietario."""
        subject = f"Proposta de Parceria - Locacao de Imovel | {self.from_name}"
        nome_display = lead_name or "Cliente"
        dados_imovel = ""
        if property_data:
            dados_imovel = f"""
            <p><strong>Imovel cadastrado:</strong></p>
            <ul>
              <li>Tipo: {property_data.get('tipo', '-')}</li>
              <li>Regiao: {property_data.get('regiao', '-')}</li>
              <li>Valor esperado: {property_data.get('valor', '-')}</li>
            </ul>
            """

        body_html = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333;">
          <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #8B4513;">Residere | Imoveis de Alto Padrao</h2>
            <p>Ola, <strong>{nome_display}</strong>!</p>
            <p>Muito obrigada pelo interesse em confiar seu imovel a <strong>Residere</strong>.
            Somos especialistas em locacao de imoveis de alto padrao em Cuiaba/MT.</p>
            {dados_imovel}
            <h3>Nossa proposta de parceria inclui:</h3>
            <ul>
              <li>✅ Divulgacao qualificada em todos os canais premium</li>
              <li>✅ Selecao criteriosa de inquilinos (analise de credito completa)</li>
              <li>✅ Vistoria detalhada de entrada e saida</li>
              <li>✅ Gestao completa de contratos e documentacao</li>
              <li>✅ Repasse pontual e transparente</li>
              <li>✅ Suporte dedicado ao proprietario 24/7</li>
            </ul>
            <p>Nossa comissao e competitiva e o servico e completo, para que voce nao
            precise se preocupar com nada.</p>
            <p>Em breve nossa equipe entrara em contato para agendar uma visita tecnica
            e apresentar a proposta detalhada.</p>
            <p>Qualquer duvida, estou a disposicao!</p>
            <p>Atenciosamente,<br>
            <strong>Andreia</strong><br>
            Assistente Virtual | {self.from_name}</p>
          </div>
        </body></html>
        """

        body_text = (
            f"Ola, {nome_display}!\n\n"
            f"Obrigada pelo interesse. Nossa equipe entrara em contato em breve.\n\n"
            f"Atenciosamente,\nAndreia - {self.from_name}"
        )

        return await self.send(to, subject, body_html, body_text)

    async def send_launch_specialist_notification(
        self,
        lead_name: str,
        lead_phone: str,
        lead_email: str,
        score: int,
        planta: str,
        pagamento: str,
        urgencia: str,
        empreendimento: str,
        origem: str,
    ) -> dict:
        """Notifica especialista de lançamento sobre lead quente (SLA 1h)."""
        to = settings.email_especialista_lancamento
        if not to:
            logger.warning("Email | email_especialista_lancamento nao configurado. Notificacao ignorada.")
            return {"status": "skipped", "reason": "email_especialista_lancamento_not_configured"}

        subject = f"🔴 LEAD LANÇAMENTO - URGENTE | {lead_name or lead_phone}"

        apresentacao = urgencia or "A definir"
        origem_display = origem or "Direto"

        body_html = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333; background: #f5f5f5;">
          <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: #1a1a2e; color: #fff; padding: 12px 20px; border-radius: 8px 8px 0 0;">
              <strong>📋 NOTIFICAÇÃO ESPECIALISTA</strong>
            </div>
            <div style="background: #fff; border: 1px solid #ddd; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
              <div style="background: #fff3cd; border-left: 4px solid #e53e3e; padding: 12px 16px; border-radius: 4px; margin-bottom: 20px;">
                <strong style="color: #e53e3e;">🔴 LEAD LANÇAMENTO - URGENTE</strong>
              </div>
              <table style="width: 100%; border-collapse: collapse;">
                <tr>
                  <td style="padding: 8px 0; color: #666; width: 40%;"><strong>Empreendimento:</strong></td>
                  <td style="padding: 8px 0;">{empreendimento}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Lead:</strong></td>
                  <td style="padding: 8px 0;">{lead_name or "Não informado"}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>WhatsApp:</strong></td>
                  <td style="padding: 8px 0;">{lead_phone}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Email:</strong></td>
                  <td style="padding: 8px 0;">{lead_email or "Não informado"}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Interesse:</strong></td>
                  <td style="padding: 8px 0;">{planta or "Não informado"}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Pagamento:</strong></td>
                  <td style="padding: 8px 0;">{pagamento or "Não informado"}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Score:</strong></td>
                  <td style="padding: 8px 0;"><strong style="color: #e53e3e;">{score}pts</strong></td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Apresentação:</strong></td>
                  <td style="padding: 8px 0;">{apresentacao}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Origem:</strong></td>
                  <td style="padding: 8px 0;">{origem_display}</td>
                </tr>
              </table>
              <div style="margin-top: 20px; background: #fff3cd; padding: 12px 16px; border-radius: 4px; text-align: center;">
                <strong>⏱ SLA: 1 HORA</strong>
              </div>
            </div>
          </div>
        </body></html>
        """

        body_text = (
            f"NOTIFICAÇÃO ESPECIALISTA\n"
            f"{'='*40}\n"
            f"🔴 LEAD LANÇAMENTO - URGENTE\n\n"
            f"Empreendimento: {empreendimento}\n"
            f"Lead: {lead_name or 'Não informado'}\n"
            f"WhatsApp: {lead_phone}\n"
            f"Email: {lead_email or 'Não informado'}\n"
            f"Interesse: {planta or 'Não informado'}\n"
            f"Pagamento: {pagamento or 'Não informado'}\n"
            f"Score: {score}pts\n"
            f"Apresentação: {apresentacao}\n"
            f"Origem: {origem_display}\n\n"
            f"⏱ SLA: 1 HORA\n"
        )

        return await self.send(to, subject, body_html, body_text)

    async def send_investor_morno_followup_notification(
        self,
        lead_name: str,
        lead_phone: str,
        score: int,
        perfil: str,
        data_selecao: str,
    ) -> dict:
        """Notifica corretor sobre lead MORNO com follow-up programado (SLA 24h)."""
        to = settings.email_corretor
        if not to:
            logger.warning("Email | email_corretor nao configurado. Notificacao ignorada.")
            return {"status": "skipped", "reason": "email_corretor_not_configured"}

        subject = f"⚠️ LEAD MORNO - FOLLOW-UP | {lead_name or lead_phone}"

        body_html = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333; background: #f5f5f5;">
          <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: #1a1a2e; color: #fff; padding: 12px 20px; border-radius: 8px 8px 0 0;">
              <strong>📋 NOTIFICAÇÃO CORRETOR</strong>
            </div>
            <div style="background: #fff; border: 1px solid #ddd; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
              <div style="background: #fff8e1; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 4px; margin-bottom: 20px;">
                <strong style="color: #b45309;">⚠️ LEAD MORNO</strong>
              </div>
              <table style="width: 100%; border-collapse: collapse;">
                <tr>
                  <td style="padding: 8px 0; color: #666; width: 40%;"><strong>Score:</strong></td>
                  <td style="padding: 8px 0;"><strong style="color: #b45309;">{score} pontos</strong></td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Nome:</strong></td>
                  <td style="padding: 8px 0;">{self._clean_val(lead_name)}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Tel:</strong></td>
                  <td style="padding: 8px 0;">{lead_phone}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666; vertical-align: top;"><strong>Perfil:</strong></td>
                  <td style="padding: 8px 0;">{self._clean_val(perfil).replace(" | ", "<br>")}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Seleção enviada em:</strong></td>
                  <td style="padding: 8px 0;">{data_selecao}</td>
                </tr>
              </table>
              <div style="margin-top: 20px; background: #fff8e1; padding: 12px 16px; border-radius: 4px; text-align: center;">
                <strong>⏱ SLA: 24 HORAS</strong>
              </div>
            </div>
          </div>
        </body></html>
        """

        body_text = (
            f"NOTIFICAÇÃO CORRETOR\n"
            f"{'='*40}\n"
            f"⚠️ LEAD MORNO\n\n"
            f"Score: {score} pontos\n"
            f"Nome: {self._clean_val(lead_name)}\n"
            f"Tel: {lead_phone}\n"
            f"Perfil: {self._clean_val(perfil).replace(' | ', chr(10) + '        ')}\n"
            f"Seleção enviada em: {data_selecao}\n\n"
            f"⏱ SLA: 24 HORAS\n"
        )

        return await self.send(to, subject, body_html, body_text)

    async def send_investor_frio_notification(
        self,
        lead_name: str,
        lead_phone: str,
        score: int,
        perfil: str,
        data_entrada: str,
        barreira: str = "",
        estrategia: str = "",
    ) -> dict:
        """Notifica sistema sobre lead FRIO em nutrição ativa (Revisão: 30 dias)."""
        to = settings.email_corretor
        if not to:
            logger.warning("Email | email_corretor nao configurado. Notificacao ignorada.")
            return {"status": "skipped", "reason": "email_corretor_not_configured"}

        subject = f"❄️ LEAD FRIO - NUTRIÇÃO ATIVA | {lead_name or lead_phone}"

        barreira_display = self._clean_val(barreira) if barreira else "A identificar"
        estrategia_display = self._clean_val(estrategia) if estrategia else "Nutrição automática"

        body_html = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333; background: #f5f5f5;">
          <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: #1a1a2e; color: #fff; padding: 12px 20px; border-radius: 8px 8px 0 0;">
              <strong>📋 NOTIFICAÇÃO SISTEMA</strong>
            </div>
            <div style="background: #fff; border: 1px solid #ddd; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
              <div style="background: #eff6ff; border-left: 4px solid #3b82f6; padding: 12px 16px; border-radius: 4px; margin-bottom: 20px;">
                <strong style="color: #1d4ed8;">❄️ LEAD FRIO — NUTRIÇÃO AUTOMÁTICA ATIVA</strong>
              </div>
              <table style="width: 100%; border-collapse: collapse;">
                <tr>
                  <td style="padding: 8px 0; color: #666; width: 40%;"><strong>Score:</strong></td>
                  <td style="padding: 8px 0;"><strong style="color: #1d4ed8;">{score} pontos</strong></td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Nome:</strong></td>
                  <td style="padding: 8px 0;">{self._clean_val(lead_name)}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Tel:</strong></td>
                  <td style="padding: 8px 0;">{lead_phone}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666; vertical-align: top;"><strong>Perfil:</strong></td>
                  <td style="padding: 8px 0;">{self._clean_val(perfil).replace(" | ", "<br>")}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Barreira:</strong></td>
                  <td style="padding: 8px 0;">{barreira_display}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Estratégia:</strong></td>
                  <td style="padding: 8px 0;">{estrategia_display}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Entrada na nutrição:</strong></td>
                  <td style="padding: 8px 0;">{data_entrada}</td>
                </tr>
              </table>
              <div style="margin-top: 20px; background: #eff6ff; padding: 12px 16px; border-radius: 4px; text-align: center;">
                <strong>📅 REVISÃO: 30 DIAS</strong>
              </div>
            </div>
          </div>
        </body></html>
        """

        body_text = (
            f"NOTIFICAÇÃO SISTEMA\n"
            f"{'='*40}\n"
            f"❄️ LEAD FRIO — NUTRIÇÃO AUTOMÁTICA ATIVA\n\n"
            f"Score: {score} pontos\n"
            f"Nome: {self._clean_val(lead_name)}\n"
            f"Tel: {lead_phone}\n"
            f"Perfil: {self._clean_val(perfil).replace(' | ', chr(10) + '        ')}\n"
            f"Barreira: {barreira_display}\n"
            f"Estratégia: {estrategia_display}\n"
            f"Entrada na nutrição: {data_entrada}\n\n"
            f"📅 REVISÃO: 30 DIAS\n"
        )

        return await self.send(to, subject, body_html, body_text)

    async def send_investor_corretor_notification(
        self,
        lead_name: str,
        lead_phone: str,
        lead_email: str,
        score: int,
        tipo_imovel: str,
        regiao: str,
        budget: str,
        data_visita: str,
    ) -> dict:
        """Notifica corretor sobre lead quente investidor com visita confirmada (SLA 2h)."""
        to = settings.email_corretor
        if not to:
            logger.warning("Email | email_corretor nao configurado. Notificacao ignorada.")
            return {"status": "skipped", "reason": "email_corretor_not_configured"}

        subject = f"🔴 LEAD QUENTE - URGENTE | {lead_name or lead_phone}"

        body_html = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333; background: #f5f5f5;">
          <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: #1a1a2e; color: #fff; padding: 12px 20px; border-radius: 8px 8px 0 0;">
              <strong>📋 NOTIFICAÇÃO CORRETOR</strong>
            </div>
            <div style="background: #fff; border: 1px solid #ddd; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
              <div style="background: #fff3cd; border-left: 4px solid #e53e3e; padding: 12px 16px; border-radius: 4px; margin-bottom: 20px;">
                <strong style="color: #e53e3e;">🔴 LEAD QUENTE - URGENTE</strong>
              </div>
              <table style="width: 100%; border-collapse: collapse;">
                <tr>
                  <td style="padding: 8px 0; color: #666; width: 40%;"><strong>Score:</strong></td>
                  <td style="padding: 8px 0;"><strong style="color: #e53e3e;">{score} pontos</strong></td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Nome:</strong></td>
                  <td style="padding: 8px 0;">{lead_name or "Não informado"}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Tel:</strong></td>
                  <td style="padding: 8px 0;">{lead_phone}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Email:</strong></td>
                  <td style="padding: 8px 0;">{lead_email or "Não informado"}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666; vertical-align: top;"><strong>Imóveis:</strong></td>
                  <td style="padding: 8px 0;">{self._clean_val(tipo_imovel).replace(" | ", "<br>")}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Região:</strong></td>
                  <td style="padding: 8px 0;">{self._clean_val(regiao)}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #666;"><strong>Budget:</strong></td>
                  <td style="padding: 8px 0;">{self._clean_val(budget)}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                  <td style="padding: 8px 0; color: #666;"><strong>Visita:</strong></td>
                  <td style="padding: 8px 0;"><strong>{self._clean_val(data_visita, "A confirmar")}</strong></td>
                </tr>
              </table>
              <div style="margin-top: 20px; background: #fff3cd; padding: 12px 16px; border-radius: 4px; text-align: center;">
                <strong>⏱ SLA: 2 HORAS</strong>
              </div>
            </div>
          </div>
        </body></html>
        """

        body_text = (
            f"NOTIFICAÇÃO CORRETOR\n"
            f"{'='*40}\n"
            f"🔴 LEAD QUENTE - URGENTE\n\n"
            f"Score: {score} pontos\n"
            f"Nome: {self._clean_val(lead_name)}\n"
            f"Tel: {lead_phone}\n"
            f"Email: {self._clean_val(lead_email)}\n"
            f"Imóveis: {self._clean_val(tipo_imovel).replace(' | ', chr(10) + '         ')}\n"
            f"Região: {self._clean_val(regiao)}\n"
            f"Budget: {self._clean_val(budget)}\n"
            f"Visita: {self._clean_val(data_visita, 'A confirmar')}\n\n"
            f"⏱ SLA: 2 HORAS\n"
        )

        return await self.send(to, subject, body_html, body_text)

    async def send_launch_material(self, to: str, lead_name: str, launch_data: Optional[dict] = None) -> dict:
        """Envia material de lancamento (plantas, tabela, tour virtual) para lead."""
        subject = f"Material Exclusivo - Lancamento | {self.from_name}"
        nome_display = lead_name or "Cliente"
        launch_info = launch_data or {}

        body_html = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333;">
          <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #8B4513;">Residere | Imoveis de Alto Padrao</h2>
            <p>Ola, <strong>{nome_display}</strong>!</p>
            <p>Conforme conversamos, segue o material completo do empreendimento
            <strong>{launch_info.get('nome', 'nosso lancamento exclusivo')}</strong>.</p>
            <h3>Material incluido:</h3>
            <ul>
              <li>📐 Plantas e decorados</li>
              <li>💰 Tabela de precos atualizada</li>
              <li>🌐 Tour virtual 360</li>
              <li>📊 Simulacao financeira</li>
            </ul>
            <p>Condicoes especiais disponiveis para a lista VIP. Entre em contato para
            garantir o seu apartamento!</p>
            <p>Atenciosamente,<br>
            <strong>Andreia</strong><br>
            Assistente Virtual | {self.from_name}</p>
          </div>
        </body></html>
        """

        body_text = (
            f"Ola, {nome_display}!\n\n"
            f"Segue o material do lancamento conforme solicitado.\n\n"
            f"Atenciosamente,\nAndreia - {self.from_name}"
        )

        return await self.send(to, subject, body_html, body_text)
