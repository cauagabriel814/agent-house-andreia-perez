import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.lead import Lead
from src.utils.logger import logger


class LeadService:
    """CRUD e logica de negocios para leads."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, lead_id: str | uuid.UUID) -> Optional[Lead]:
        result = await self.session.execute(select(Lead).where(Lead.id == lead_id))
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Optional[Lead]:
        result = await self.session.execute(select(Lead).where(Lead.phone == phone))
        return result.scalar_one_or_none()

    async def get_or_create(self, phone: str, **kwargs) -> tuple[Lead, bool]:
        """Busca lead pelo telefone ou cria novo. Retorna (lead, criado)."""
        lead = await self.get_by_phone(phone)
        if lead:
            return lead, False
        lead = await self.create(phone, **kwargs)
        return lead, True

    async def create(self, phone: str, **kwargs) -> Lead:
        lead = Lead(phone=phone, **kwargs)
        self.session.add(lead)
        await self.session.commit()
        await self.session.refresh(lead)
        return lead

    async def update(self, lead: Lead, **kwargs) -> Lead:
        """Atualiza campos do lead via UPDATE direto (evita StaleDataError em concorrência)."""
        values = {**kwargs, "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)}
        result = await self.session.execute(
            update(Lead).where(Lead.id == lead.id).values(**values)
        )
        await self.session.commit()
        if result.rowcount == 0:
            logger.warning("LeadService.update | 0 rows affected | lead_id=%s", lead.id)
        for key, value in values.items():
            setattr(lead, key, value)
        return lead

    async def mark_as_recurring(self, lead: Lead) -> Lead:
        return await self.update(lead, is_recurring=True)

    async def update_classification(self, lead: Lead, classification: str, score: int) -> Lead:
        return await self.update(lead, classification=classification, score=score)

    async def save_kommo_ids(
        self, lead: Lead, kommo_contact_id: str, kommo_lead_id: str
    ) -> Lead:
        """Persiste os IDs do KOMMO no registro do lead."""
        return await self.update(
            lead,
            kommo_contact_id=kommo_contact_id,
            kommo_lead_id=kommo_lead_id,
        )
