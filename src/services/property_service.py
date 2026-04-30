"""
Servico de imoveis — CRUD, busca, importacao e exportacao CSV.
"""
import csv
import io
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.property import Property


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in ("sim", "true", "1", "yes")


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


# Colunas na ordem certa para export/import CSV
_CSV_COLUMNS = [
    "codigo", "tipo", "situacao", "finalidade", "bairro", "endereco",
    "suites", "banheiros", "vagas", "area_privativa", "area_total",
    "valor", "condominio", "iptu", "diferenciais", "acabamento",
    "andar", "total_andares", "elevadores", "unidades_andar",
    "aceita_permuta", "aceita_financiamento", "disponivel", "lancamento",
    "mobiliado", "ocupacao", "vista", "estado_conservacao", "escritura",
    "piscina", "churrasqueira", "tipo_piso",
    "suite_master", "closet", "varanda_gourmet", "sauna", "elevador_privativo",
    "sala_estar", "sala_jantar", "lavabo", "deposito",
    "empreendimento", "construtora", "entrega",
    "fotos_url", "tour_360", "planta_url", "video_url",
    "descricao", "observacoes", "corretor_responsavel", "tags",
]


class PropertyService:
    """CRUD e operacoes CSV para imoveis."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_by_id(self, property_id: str | uuid.UUID) -> Optional[Property]:
        result = await self.session.execute(
            select(Property).where(Property.id == property_id)
        )
        return result.scalar_one_or_none()

    async def get_by_codigo(self, codigo: str) -> Optional[Property]:
        result = await self.session.execute(
            select(Property).where(Property.codigo == codigo.strip())
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        bairro: str = "",
        finalidade: str = "",
        tipo: str = "",
        disponivel: Optional[str] = None,
        lancamento: Optional[bool] = None,
        valor_max: Optional[float] = None,
    ) -> list[Property]:
        stmt = select(Property)

        if bairro:
            stmt = stmt.where(Property.bairro.ilike(f"%{bairro}%"))
        if finalidade:
            stmt = stmt.where(Property.finalidade.ilike(f"%{finalidade}%"))
        if tipo:
            stmt = stmt.where(Property.tipo.ilike(f"%{tipo}%"))
        if disponivel is not None:
            stmt = stmt.where(Property.disponivel.ilike(f"%{disponivel}%"))
        if lancamento is not None:
            stmt = stmt.where(Property.lancamento == lancamento)
        if valor_max is not None:
            stmt = stmt.where(
                (Property.valor == None) | (Property.valor <= valor_max)  # noqa: E711
            )

        stmt = stmt.order_by(Property.valor.asc().nullslast())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        from sqlalchemy import func
        result = await self.session.execute(select(func.count()).select_from(Property))
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Mutacoes
    # ------------------------------------------------------------------

    async def create(self, data: dict) -> Property:
        prop = Property(**self._prepare(data))
        self.session.add(prop)
        await self.session.commit()
        await self.session.refresh(prop)
        return prop

    async def update(self, prop: Property, data: dict) -> Property:
        for key, value in self._prepare(data).items():
            setattr(prop, key, value)
        await self.session.commit()
        await self.session.refresh(prop)
        return prop

    async def delete(self, prop: Property) -> None:
        await self.session.delete(prop)
        await self.session.commit()

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    async def export_csv(self) -> str:
        """Retorna todas as propriedades como string CSV."""
        props = await self.get_all()
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for p in props:
            row = {col: getattr(p, col, "") for col in _CSV_COLUMNS}
            # lancamento permanece booleano → Sim/Não
            row["lancamento"] = "Sim" if row["lancamento"] else "Não"
            # Campos booleanos de amenidades
            for bool_col in (
                "suite_master", "closet", "varanda_gourmet", "sauna",
                "elevador_privativo", "sala_estar", "sala_jantar", "lavabo", "deposito",
            ):
                val = row[bool_col]
                row[bool_col] = "Sim" if val else ("Não" if val is not None else "")
            writer.writerow(row)
        return output.getvalue()

    async def import_csv(self, content: str) -> dict:
        """
        Faz upsert de propriedades a partir do conteudo CSV.
        Retorna {'created': int, 'updated': int, 'errors': list[str]}.
        """
        created = updated = 0
        errors: list[str] = []

        reader = csv.DictReader(io.StringIO(content))
        for i, row in enumerate(reader, start=2):  # linha 1 = header
            codigo = row.get("codigo", "").strip()
            if not codigo:
                errors.append(f"Linha {i}: campo 'codigo' obrigatorio")
                continue
            try:
                existing = await self.get_by_codigo(codigo)
                if existing:
                    await self.update(existing, row)
                    updated += 1
                else:
                    await self.create(row)
                    created += 1
            except Exception as exc:
                errors.append(f"Linha {i} (codigo={codigo}): {exc}")

        return {"created": created, "updated": updated, "errors": errors}

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare(data: dict) -> dict:
        """Converte tipos do dict para os campos do modelo."""
        out: dict = {}
        int_fields = {
            "suites", "banheiros", "vagas", "andar", "total_andares",
            "elevadores", "unidades_andar",
        }
        float_fields = {"area_privativa", "area_total", "valor", "condominio", "iptu"}
        bool_fields = {
            "lancamento",
            "suite_master", "closet", "varanda_gourmet", "sauna",
            "elevador_privativo", "sala_estar", "sala_jantar", "lavabo", "deposito",
        }

        for key, value in data.items():
            if key not in {col for col in _CSV_COLUMNS} | {"id", "created_at", "updated_at"}:
                continue
            if key in int_fields:
                out[key] = _parse_int(value)
            elif key in float_fields:
                out[key] = _parse_float(value)
            elif key in bool_fields:
                if isinstance(value, bool):
                    out[key] = value
                else:
                    out[key] = _parse_bool(value)
            else:
                out[key] = str(value).strip() if value not in (None, "") else None

        return out
