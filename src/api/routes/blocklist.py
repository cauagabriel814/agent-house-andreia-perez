"""
blocklist.py — CRUD de numeros bloqueados.

GET    /blocklist        → lista todos (admin)
POST   /blocklist        → adiciona numero (admin)
DELETE /blocklist/{phone} → remove numero (admin)
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.runner import append_message_to_history
from src.agent.tools.uazapi import send_whatsapp_message
from src.api.auth.dependencies import get_admin_user
from src.db.database import get_session
from src.db.models.blocked_number import BlockedNumber
from src.db.models.user import User

router = APIRouter(prefix="/blocklist", tags=["blocklist"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class BlockedNumberOut(BaseModel):
    id: uuid.UUID
    phone: str
    reason: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class BlockedNumberCreate(BaseModel):
    phone: str
    reason: Optional[str] = None


class UnblockBody(BaseModel):
    message: Optional[str] = None


# ------------------------------------------------------------------
# Rotas
# ------------------------------------------------------------------

@router.get("", response_model=list[BlockedNumberOut])
async def list_blocked(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_admin_user),
):
    result = await session.execute(select(BlockedNumber).order_by(BlockedNumber.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=BlockedNumberOut, status_code=status.HTTP_201_CREATED)
async def add_blocked(
    body: BlockedNumberCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_admin_user),
):
    phone = body.phone.strip()
    existing = await session.execute(select(BlockedNumber).where(BlockedNumber.phone == phone))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Numero ja esta na blocklist")

    entry = BlockedNumber(phone=phone, reason=body.reason)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


@router.delete("/{phone}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_blocked(
    phone: str,
    body: UnblockBody = UnblockBody(),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_admin_user),
):
    result = await session.execute(select(BlockedNumber).where(BlockedNumber.phone == phone))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Numero nao encontrado na blocklist")
    await session.delete(entry)
    await session.commit()

    if body.message:
        # Envia mensagem ao lead e salva no historico como AIMessage
        await send_whatsapp_message(phone, body.message)
        await append_message_to_history(phone=phone, content=body.message, role="ai")
    else:
        # Apenas salva anotacao interna sem enviar ao WhatsApp
        await append_message_to_history(
            phone=phone,
            content=(
                "[SISTEMA] Número desbloqueado pelo operador. "
                "O lead pode enviar mensagens novamente. "
                "Histórico anterior preservado."
            ),
            role="ai",
        )
