import uuid
from typing import Optional

from src.services.appointment_service import AppointmentService


async def schedule_visit(
    lead_id: str | uuid.UUID,
    visit_type: str,
    lead_name: str = "",
    lead_phone: str = "",
    datetime_str: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """
    Tool: Agenda visita/reuniao com corretor, avaliador, consultor ou especialista.

    Args:
        lead_id: ID interno do lead
        visit_type: avaliador | consultor | especialista | corretor
        lead_name: Nome do lead
        lead_phone: Telefone do lead
        datetime_str: Data/hora preferida no formato ISO 8601 (ex: "2026-04-01T10:00:00")
        notes: Observacoes adicionais para o agendamento
    """
    service = AppointmentService()
    return await service.schedule(
        appointment_type=visit_type,
        lead_id=lead_id,
        lead_name=lead_name,
        lead_phone=lead_phone,
        preferred_datetime=datetime_str,
        notes=notes,
    )


async def get_available_slots(
    visit_type: str,
    date_start: str,
    date_end: str,
) -> list[dict]:
    """
    Tool: Retorna horarios disponiveis para agendamento.

    Args:
        visit_type: avaliador | consultor | especialista | corretor
        date_start: Data inicio (YYYY-MM-DD)
        date_end: Data fim (YYYY-MM-DD)
    """
    service = AppointmentService()
    return await service.get_available_slots(visit_type, date_start, date_end)
