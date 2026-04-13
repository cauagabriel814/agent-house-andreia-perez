"""
Appointment Service - Agendamento de visitas e consultorias via REST API generica.

Suporta os tipos de agendamento do PLANNING.md:
  - avaliador: Visita tecnica para proprietario vender (Feature 10)
  - consultor:  Consultoria para investidor (Feature 12)
  - especialista: Apresentacao de lancamento (Feature 14)
  - corretor: Visita a imovel pronto com comprador (Feature 14)
"""

import uuid
from typing import Optional

import httpx

from src.config.settings import settings
from src.utils.logger import logger

# Tipos de agendamento suportados
APPOINTMENT_TYPES = {
    "avaliador": "Visita Tecnica - Avaliacao",
    "consultor": "Consultoria Financeira - Investidor",
    "especialista": "Apresentacao - Lancamento",
    "corretor": "Visita ao Imovel - Comprador",
}


class AppointmentService:
    """Client HTTP para sistema de agenda (REST API generica)."""

    def __init__(self):
        self.base_url = settings.appointment_base_url.rstrip("/")
        self.api_key = settings.appointment_api_key
        self._enabled = bool(self.base_url and self.api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _is_enabled(self) -> bool:
        if not self._enabled:
            logger.warning(
                "Agenda nao configurada (APPOINTMENT_BASE_URL ou APPOINTMENT_API_KEY ausentes). "
                "Operacao ignorada."
            )
            return False
        return True

    async def get_available_slots(
        self,
        appointment_type: str,
        date_start: str,
        date_end: str,
    ) -> list[dict]:
        """
        Retorna horarios disponiveis para um tipo de agendamento.

        Args:
            appointment_type: avaliador | consultor | especialista | corretor
            date_start: data inicio no formato YYYY-MM-DD
            date_end: data fim no formato YYYY-MM-DD

        Returns:
            Lista de slots disponiveis: [{"datetime": "...", "slot_id": "..."}]
        """
        if not self._is_enabled():
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/slots",
                    headers=self._headers(),
                    params={
                        "type": appointment_type,
                        "date_start": date_start,
                        "date_end": date_end,
                    },
                )
                response.raise_for_status()
                data = response.json()
                slots = data if isinstance(data, list) else data.get("slots", [])
                logger.info(
                    "Agenda | Slots disponiveis | type=%s | total=%d",
                    appointment_type,
                    len(slots),
                )
                return slots
        except Exception as exc:
            logger.error("Agenda | Falha ao buscar slots | type=%s | erro=%s", appointment_type, exc)
            return []

    async def schedule(
        self,
        appointment_type: str,
        lead_id: str | uuid.UUID,
        lead_name: str,
        lead_phone: str,
        preferred_datetime: Optional[str] = None,
        notes: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> dict:
        """
        Agenda uma visita ou consultoria.

        Args:
            appointment_type: avaliador | consultor | especialista | corretor
            lead_id: ID interno do lead
            lead_name: Nome do lead
            lead_phone: Telefone do lead
            preferred_datetime: Datetime preferido no formato ISO 8601 (opcional)
            notes: Observacoes adicionais
            extra: Campos extras para o sistema de agenda

        Returns:
            {"status": "scheduled", "booking_ref": "...", "datetime": "..."}
        """
        if not self._is_enabled():
            return {"status": "skipped", "reason": "appointment_not_configured"}

        type_label = APPOINTMENT_TYPES.get(appointment_type, appointment_type)
        payload: dict = {
            "type": appointment_type,
            "type_label": type_label,
            "external_id": str(lead_id),
            "contact_name": lead_name,
            "contact_phone": lead_phone,
            "preferred_datetime": preferred_datetime,
            "notes": notes or "",
        }
        if extra:
            payload.update(extra)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/appointments",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                booking_ref = data.get("booking_ref") or data.get("id", "")
                logger.info(
                    "Agenda | Agendado | type=%s | lead_id=%s | booking_ref=%s",
                    appointment_type,
                    lead_id,
                    booking_ref,
                )
                return {"status": "scheduled", "booking_ref": booking_ref, **data}
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Agenda | Erro HTTP | type=%s | lead_id=%s | status=%s",
                appointment_type,
                lead_id,
                exc.response.status_code,
            )
            return {"status": "error", "code": exc.response.status_code}
        except Exception as exc:
            logger.error("Agenda | Falha ao agendar | type=%s | lead_id=%s | erro=%s", appointment_type, lead_id, exc)
            return {"status": "error", "reason": str(exc)}

    async def cancel(self, booking_ref: str, reason: Optional[str] = None) -> dict:
        """Cancela um agendamento existente."""
        if not self._is_enabled():
            return {"status": "skipped", "reason": "appointment_not_configured"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(
                    f"{self.base_url}/appointments/{booking_ref}",
                    headers=self._headers(),
                    json={"reason": reason or ""},
                )
                response.raise_for_status()
                logger.info("Agenda | Cancelado | booking_ref=%s", booking_ref)
                return {"status": "cancelled", "booking_ref": booking_ref}
        except Exception as exc:
            logger.error("Agenda | Falha ao cancelar | booking_ref=%s | erro=%s", booking_ref, exc)
            return {"status": "error", "reason": str(exc)}
