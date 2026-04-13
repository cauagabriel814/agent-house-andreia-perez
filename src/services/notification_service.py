import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.notification import Notification


class NotificationService:
    """Gerenciamento de notificacoes para corretores."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        lead_id: str | uuid.UUID,
        notification_type: str,
        sla_hours: Optional[int] = None,
        payload: Optional[dict] = None,
        dispatch: bool = True,
    ) -> Notification:
        """
        Cria uma notificacao no banco e opcionalmente a envia para os corretores via WhatsApp.

        Args:
            dispatch: Se True, envia imediatamente via WhatsApp para os corretores configurados.
        """
        notif = Notification(
            lead_id=lead_id,
            type=notification_type,
            sla_hours=sla_hours,
            payload=payload,
        )
        self.session.add(notif)
        await self.session.commit()
        await self.session.refresh(notif)

        if dispatch:
            await self._dispatch(notif)

        return notif

    async def _dispatch(self, notification: Notification) -> None:
        """Envia a notificacao via WhatsApp para os corretores e marca como enviada."""
        from src.services.broker_notifier import BrokerNotifierService

        notifier = BrokerNotifierService()
        results = await notifier.dispatch(notification)

        any_sent = any(r.get("status") == "sent" for r in results)
        if any_sent:
            await self.mark_sent(notification)

    async def mark_sent(self, notification: Notification) -> Notification:
        notification.sent_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        await self.session.commit()
        return notification

    async def mark_acknowledged(self, notification: Notification) -> Notification:
        notification.acknowledged_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        await self.session.commit()
        return notification

    async def get_unacknowledged(self, lead_id: str | uuid.UUID) -> list[Notification]:
        result = await self.session.execute(
            select(Notification)
            .where(
                Notification.lead_id == lead_id,
                Notification.acknowledged_at.is_(None),
            )
            .order_by(Notification.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_unsent(self) -> list[Notification]:
        """Retorna todas as notificacoes ainda nao enviadas (para reprocessamento)."""
        result = await self.session.execute(
            select(Notification)
            .where(Notification.sent_at.is_(None))
            .order_by(Notification.created_at.asc())
        )
        return list(result.scalars().all())
