import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.tag import LeadTag


class TagService:
    """Gerenciamento de tags dos leads."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_by_lead(self, lead_id: str | uuid.UUID) -> list[LeadTag]:
        result = await self.session.execute(
            select(LeadTag).where(LeadTag.lead_id == lead_id).order_by(LeadTag.created_at)
        )
        return list(result.scalars().all())

    async def get_by_name(self, lead_id: str | uuid.UUID, tag_name: str) -> Optional[LeadTag]:
        result = await self.session.execute(
            select(LeadTag).where(LeadTag.lead_id == lead_id, LeadTag.tag_name == tag_name)
        )
        return result.scalar_one_or_none()

    async def set_tag(self, lead_id: str | uuid.UUID, tag_name: str, tag_value: Optional[str] = None) -> LeadTag:
        """Cria ou atualiza uma tag (upsert por lead_id + tag_name)."""
        tag = await self.get_by_name(lead_id, tag_name)
        if tag:
            tag.tag_value = tag_value
            await self.session.commit()
            await self.session.refresh(tag)
            return tag
        return await self.add_tag(lead_id, tag_name, tag_value)

    async def add_tag(self, lead_id: str | uuid.UUID, tag_name: str, tag_value: Optional[str] = None) -> LeadTag:
        tag = LeadTag(lead_id=lead_id, tag_name=tag_name, tag_value=tag_value)
        self.session.add(tag)
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def as_dict(self, lead_id: str | uuid.UUID) -> dict[str, str]:
        """Retorna todas as tags do lead como dicionario {tag_name: tag_value}."""
        tags = await self.get_all_by_lead(lead_id)
        return {t.tag_name: (t.tag_value or "") for t in tags}
