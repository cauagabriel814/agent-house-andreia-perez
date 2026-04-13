"""
auth.py — Rotas de autenticacao JWT.

POST /auth/login    → retorna access_token
POST /auth/register → cria novo usuario
  - Primeiro registro: livre (qualquer um pode criar o primeiro admin)
  - Demais registros: requerem token de admin
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import get_admin_user
from src.api.auth.jwt import create_access_token
from src.db.database import get_session
from src.db.models.user import User
from src.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "corretor"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
):
    """Autentica com email + senha e retorna JWT."""
    service = UserService(session)
    user = await service.authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha invalidos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    session: AsyncSession = Depends(get_session),
    # admin_user nao e obrigatorio — apenas verifica se ja existem users
    _: User = Depends(get_admin_user),
):
    """Cria novo usuario. Requer autenticacao de admin."""
    service = UserService(session)
    if await service.get_by_email(body.email):
        raise HTTPException(status_code=400, detail="Email ja cadastrado")
    user = await service.create(
        name=body.name,
        email=body.email,
        password=body.password,
        role=body.role,
    )
    return {"id": str(user.id), "email": user.email, "role": user.role}


@router.post("/register/first", status_code=status.HTTP_201_CREATED)
async def register_first_admin(
    body: RegisterRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Cria o primeiro admin sem autenticacao.
    Retorna 403 se ja existir qualquer usuario no banco.
    """
    service = UserService(session)
    total = await service.count()
    if total > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ja existem usuarios cadastrados. Use POST /auth/register com token de admin.",
        )
    user = await service.create(
        name=body.name,
        email=body.email,
        password=body.password,
        role="admin",
    )
    return {"id": str(user.id), "email": user.email, "role": user.role}
