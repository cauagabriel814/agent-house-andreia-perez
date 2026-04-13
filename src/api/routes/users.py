"""
users.py — CRUD completo de usuarios.

GET    /users        → lista todos (admin)
GET    /users/me     → usuario atual
GET    /users/{id}   → busca por id (admin ou proprio)
POST   /users        → cria usuario (admin)
PUT    /users/{id}   → atualiza (admin ou proprio)
DELETE /users/{id}   → deleta (admin)
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import get_admin_user, get_current_user
from src.db.database import get_session
from src.db.models.user import User
from src.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class UserOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "corretor"


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


# ------------------------------------------------------------------
# Rotas
# ------------------------------------------------------------------

@router.get("", response_model=list[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_admin_user),
):
    service = UserService(session)
    return await service.get_all()


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado")
    service = UserService(session)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    return user


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_admin_user),
):
    service = UserService(session)
    if await service.get_by_email(body.email):
        raise HTTPException(status_code=400, detail="Email ja cadastrado")
    return await service.create(
        name=body.name,
        email=body.email,
        password=body.password,
        role=body.role,
    )


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado")

    service = UserService(session)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")

    # Somente admin pode alterar role
    updates = body.model_dump(exclude_none=True)
    if "role" in updates and current_user.role != "admin":
        updates.pop("role")

    return await service.update(user, **updates)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_admin_user),
):
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Nao e possivel deletar o proprio usuario")
    service = UserService(session)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    await service.delete(user)
