import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.lead import Base


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    tipo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    situacao: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    finalidade: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bairro: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    endereco: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    suites: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    banheiros: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vagas: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    andar: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_andares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    elevadores: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unidades_andar: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    area_privativa: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    area_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    valor: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    condominio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iptu: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    diferenciais: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    acabamento: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    empreendimento: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    construtora: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    entrega: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    fotos_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tour_360: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    planta_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    descricao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    observacoes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    corretor_responsavel: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    aceita_permuta: Mapped[bool] = mapped_column(default=False)
    aceita_financiamento: Mapped[bool] = mapped_column(default=True)
    disponivel: Mapped[bool] = mapped_column(default=True, index=True)
    lancamento: Mapped[bool] = mapped_column(default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
