import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.scheduled_job import ScheduledJob


class JobService:
    """Gerenciamento de scheduled jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_job(
        self,
        lead_id: str | uuid.UUID,
        job_type: str,
        scheduled_for: datetime,
        payload: Optional[dict] = None,
    ) -> ScheduledJob:
        job = ScheduledJob(
            lead_id=lead_id,
            job_type=job_type,
            scheduled_for=scheduled_for,
            payload=payload,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def schedule_after(
        self,
        lead_id: str | uuid.UUID,
        job_type: str,
        delay: timedelta,
        payload: Optional[dict] = None,
    ) -> ScheduledJob:
        """Agenda um job para executar apos um intervalo a partir de agora."""
        # scheduled_for e armazenado como TIMESTAMP WITHOUT TIME ZONE (UTC naive)
        scheduled_for = datetime.now(tz=timezone.utc).replace(tzinfo=None) + delay
        return await self.create_job(lead_id, job_type, scheduled_for, payload)

    async def get_pending_jobs(self) -> list[ScheduledJob]:
        """Busca jobs pendentes cujo horario ja passou."""
        # Compara como naive UTC pois a coluna e TIMESTAMP WITHOUT TIME ZONE
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        result = await self.session.execute(
            select(ScheduledJob)
            .where(ScheduledJob.status == "pending", ScheduledJob.scheduled_for <= now)
            .order_by(ScheduledJob.scheduled_for)
        )
        return list(result.scalars().all())

    async def get_pending_by_lead(self, lead_id: str | uuid.UUID) -> list[ScheduledJob]:
        """Retorna jobs pendentes de um lead especifico."""
        result = await self.session.execute(
            select(ScheduledJob)
            .where(ScheduledJob.lead_id == lead_id, ScheduledJob.status == "pending")
            .order_by(ScheduledJob.scheduled_for)
        )
        return list(result.scalars().all())

    async def mark_executed(self, job: ScheduledJob) -> ScheduledJob:
        job.status = "executed"
        job.executed_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        await self.session.commit()
        return job

    async def cancel_pending_by_lead(self, lead_id: str | uuid.UUID) -> int:
        """Cancela todos os jobs pendentes de um lead (ex: quando ele responde). Retorna qtd cancelada."""
        result = await self.session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.lead_id == lead_id, ScheduledJob.status == "pending")
            .values(status="cancelled")
        )
        await self.session.commit()
        return result.rowcount
