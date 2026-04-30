"""
properties_admin.py — CRUD de imoveis + importacao/exportacao CSV.

GET    /admin/properties                  → lista com filtros
GET    /admin/properties/export/csv       → download CSV
POST   /admin/properties/import/csv       → upload CSV (upsert)
GET    /admin/properties/by-code/{codigo} → busca por codigo
GET    /admin/properties/{id}             → busca por id
POST   /admin/properties                  → cria imovel
PUT    /admin/properties/{id}             → atualiza imovel
DELETE /admin/properties/{id}             → deleta imovel
"""

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

# ------------------------------------------------------------------
# Tipos enumerados (valores fixos aceitos pela API)
# ------------------------------------------------------------------

TipoImovel = Literal[
    "Apartamento", "Casa", "Cobertura", "Duplex", "Triplex",
    "Loft", "Studio", "Casa em Condomínio", "Sobrado",
    "Terreno", "Loja", "Sala Comercial", "Galpão",
]
Situacao = Literal["Pronto para Morar", "Lançamento", "Em Construção", "Na Planta"]
Finalidade = Literal["Venda", "Locação", "Venda e Locação"]
Acabamento = Literal["Padrão", "Alto Padrão", "Luxo", "Ultra Luxo"]
AceitaPermuta = Literal["Sim", "Não", "A Avaliar"]
AceitaFinanciamento = Literal["Sim", "Não", "Apenas Caixa", "Todos os Bancos"]
Disponivel = Literal["Sim", "Não", "Reservado", "Em Negociação"]
Mobiliado = Literal["Sim", "Não", "Semi-mobiliado", "Sob Consulta"]
Ocupacao = Literal["Vago", "Ocupado", "Ocupado pelo Proprietário", "Alugado"]
Vista = Literal["Mar", "Cidade", "Montanha", "Parque", "Lago", "Rua", "Interna", "Panorâmica"]
EstadoConservacao = Literal["Novo", "Excelente", "Bom", "Regular", "Precisa Reforma"]
Escritura = Literal["Sim", "Não", "Em Processo"]
Piscina = Literal["Sim", "Não", "Coletiva"]
Churrasqueira = Literal["Sim", "Não", "Coletiva"]
TipoPiso = Literal[
    "Porcelanato", "Mármore", "Granito", "Madeira",
    "Laminado", "Vinílico", "Carpete", "Cerâmica", "Misto",
]

from src.api.auth.dependencies import get_current_user
from src.db.database import get_session
from src.db.models.user import User
from src.services.property_service import PropertyService

router = APIRouter(prefix="/admin/properties", tags=["properties"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class PropertyOut(BaseModel):
    id: uuid.UUID
    codigo: str
    tipo: Optional[str] = None
    situacao: Optional[str] = None
    finalidade: Optional[str] = None
    bairro: Optional[str] = None
    endereco: Optional[str] = None
    suites: Optional[int] = None
    banheiros: Optional[int] = None
    vagas: Optional[int] = None
    area_privativa: Optional[float] = None
    area_total: Optional[float] = None
    valor: Optional[float] = None
    condominio: Optional[float] = None
    iptu: Optional[float] = None
    diferenciais: Optional[str] = None
    acabamento: Optional[str] = None
    andar: Optional[int] = None
    total_andares: Optional[int] = None
    elevadores: Optional[int] = None
    unidades_andar: Optional[int] = None
    aceita_permuta: Optional[str] = None
    aceita_financiamento: Optional[str] = None
    disponivel: Optional[str] = None
    lancamento: bool = False
    empreendimento: Optional[str] = None
    construtora: Optional[str] = None
    entrega: Optional[str] = None
    fotos_url: Optional[str] = None
    tour_360: Optional[str] = None
    planta_url: Optional[str] = None
    video_url: Optional[str] = None
    descricao: Optional[str] = None
    observacoes: Optional[str] = None
    corretor_responsavel: Optional[str] = None
    tags: Optional[str] = None
    mobiliado: Optional[str] = None
    ocupacao: Optional[str] = None
    vista: Optional[str] = None
    estado_conservacao: Optional[str] = None
    escritura: Optional[str] = None
    piscina: Optional[str] = None
    churrasqueira: Optional[str] = None
    tipo_piso: Optional[str] = None
    suite_master: Optional[bool] = None
    closet: Optional[bool] = None
    varanda_gourmet: Optional[bool] = None
    sauna: Optional[bool] = None
    elevador_privativo: Optional[bool] = None
    sala_estar: Optional[bool] = None
    sala_jantar: Optional[bool] = None
    lavabo: Optional[bool] = None
    deposito: Optional[bool] = None

    model_config = {"from_attributes": True}


class PropertyCreate(BaseModel):
    codigo: str
    tipo: Optional[TipoImovel] = None
    situacao: Optional[Situacao] = None
    finalidade: Optional[Finalidade] = None
    bairro: Optional[str] = None
    endereco: Optional[str] = None
    suites: Optional[int] = None
    banheiros: Optional[int] = None
    vagas: Optional[int] = None
    area_privativa: Optional[float] = None
    area_total: Optional[float] = None
    valor: Optional[float] = None
    condominio: Optional[float] = None
    iptu: Optional[float] = None
    diferenciais: Optional[str] = None
    acabamento: Optional[Acabamento] = None
    andar: Optional[int] = None
    total_andares: Optional[int] = None
    elevadores: Optional[int] = None
    unidades_andar: Optional[int] = None
    aceita_permuta: Optional[AceitaPermuta] = None
    aceita_financiamento: Optional[AceitaFinanciamento] = None
    disponivel: Optional[Disponivel] = None
    lancamento: bool = False
    empreendimento: Optional[str] = None
    construtora: Optional[str] = None
    entrega: Optional[str] = None
    fotos_url: Optional[str] = None
    tour_360: Optional[str] = None
    planta_url: Optional[str] = None
    video_url: Optional[str] = None
    descricao: Optional[str] = None
    observacoes: Optional[str] = None
    corretor_responsavel: Optional[str] = None
    tags: Optional[str] = None
    mobiliado: Optional[Mobiliado] = None
    ocupacao: Optional[Ocupacao] = None
    vista: Optional[Vista] = None
    estado_conservacao: Optional[EstadoConservacao] = None
    escritura: Optional[Escritura] = None
    piscina: Optional[Piscina] = None
    churrasqueira: Optional[Churrasqueira] = None
    tipo_piso: Optional[TipoPiso] = None
    suite_master: Optional[bool] = None
    closet: Optional[bool] = None
    varanda_gourmet: Optional[bool] = None
    sauna: Optional[bool] = None
    elevador_privativo: Optional[bool] = None
    sala_estar: Optional[bool] = None
    sala_jantar: Optional[bool] = None
    lavabo: Optional[bool] = None
    deposito: Optional[bool] = None


class PropertyUpdate(BaseModel):
    tipo: Optional[TipoImovel] = None
    situacao: Optional[Situacao] = None
    finalidade: Optional[Finalidade] = None
    bairro: Optional[str] = None
    endereco: Optional[str] = None
    suites: Optional[int] = None
    banheiros: Optional[int] = None
    vagas: Optional[int] = None
    area_privativa: Optional[float] = None
    area_total: Optional[float] = None
    valor: Optional[float] = None
    condominio: Optional[float] = None
    iptu: Optional[float] = None
    diferenciais: Optional[str] = None
    acabamento: Optional[Acabamento] = None
    andar: Optional[int] = None
    total_andares: Optional[int] = None
    elevadores: Optional[int] = None
    unidades_andar: Optional[int] = None
    aceita_permuta: Optional[AceitaPermuta] = None
    aceita_financiamento: Optional[AceitaFinanciamento] = None
    disponivel: Optional[Disponivel] = None
    lancamento: Optional[bool] = None
    empreendimento: Optional[str] = None
    construtora: Optional[str] = None
    entrega: Optional[str] = None
    fotos_url: Optional[str] = None
    tour_360: Optional[str] = None
    planta_url: Optional[str] = None
    video_url: Optional[str] = None
    descricao: Optional[str] = None
    observacoes: Optional[str] = None
    corretor_responsavel: Optional[str] = None
    tags: Optional[str] = None
    mobiliado: Optional[Mobiliado] = None
    ocupacao: Optional[Ocupacao] = None
    vista: Optional[Vista] = None
    estado_conservacao: Optional[EstadoConservacao] = None
    escritura: Optional[Escritura] = None
    piscina: Optional[Piscina] = None
    churrasqueira: Optional[Churrasqueira] = None
    tipo_piso: Optional[TipoPiso] = None
    suite_master: Optional[bool] = None
    closet: Optional[bool] = None
    varanda_gourmet: Optional[bool] = None
    sauna: Optional[bool] = None
    elevador_privativo: Optional[bool] = None
    sala_estar: Optional[bool] = None
    sala_jantar: Optional[bool] = None
    lavabo: Optional[bool] = None
    deposito: Optional[bool] = None


# ------------------------------------------------------------------
# Rotas — ordem importa: rotas estaticas antes de {id}
# ------------------------------------------------------------------

@router.get("/export/csv")
async def export_csv(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Exporta todas as propriedades como arquivo CSV para download."""
    service = PropertyService(session)
    content = await service.export_csv()

    def _iter():
        yield content

    return StreamingResponse(
        _iter(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=properties.csv"},
    )


@router.post("/import/csv", status_code=status.HTTP_200_OK)
async def import_csv(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """
    Importa propriedades a partir de um arquivo CSV.
    Faz upsert pelo campo 'codigo'. Retorna contagem de criados/atualizados/erros.
    """
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    service = PropertyService(session)
    result = await service.import_csv(content)
    return result


@router.get("/by-code/{codigo}", response_model=PropertyOut)
async def get_by_code(
    codigo: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    service = PropertyService(session)
    prop = await service.get_by_codigo(codigo)
    if not prop:
        raise HTTPException(status_code=404, detail="Imovel nao encontrado")
    return prop


@router.get("", response_model=list[PropertyOut])
async def list_properties(
    bairro: str = Query("", description="Filtro por bairro (parcial)"),
    finalidade: str = Query("", description="Venda ou Locacao"),
    tipo: str = Query("", description="Tipo do imovel (parcial)"),
    disponivel: Optional[str] = Query(None, description="Filtrar por disponibilidade (Sim, Não, Reservado, Em Negociação)"),
    lancamento: Optional[bool] = Query(None, description="Filtrar lancamentos"),
    valor_max: Optional[float] = Query(None, description="Valor maximo"),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    service = PropertyService(session)
    return await service.get_all(
        bairro=bairro,
        finalidade=finalidade,
        tipo=tipo,
        disponivel=disponivel,
        lancamento=lancamento,
        valor_max=valor_max,
    )


@router.get("/{property_id}", response_model=PropertyOut)
async def get_property(
    property_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    service = PropertyService(session)
    prop = await service.get_by_id(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Imovel nao encontrado")
    return prop


@router.post("", response_model=PropertyOut, status_code=status.HTTP_201_CREATED)
async def create_property(
    body: PropertyCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    service = PropertyService(session)
    if await service.get_by_codigo(body.codigo):
        raise HTTPException(status_code=400, detail="Codigo ja cadastrado")
    return await service.create(body.model_dump())


@router.put("/{property_id}", response_model=PropertyOut)
async def update_property(
    property_id: uuid.UUID,
    body: PropertyUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    service = PropertyService(session)
    prop = await service.get_by_id(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Imovel nao encontrado")
    return await service.update(prop, body.model_dump(exclude_none=True))


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property(
    property_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    service = PropertyService(session)
    prop = await service.get_by_id(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Imovel nao encontrado")
    await service.delete(prop)
