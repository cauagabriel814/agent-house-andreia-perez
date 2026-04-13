"""
Catálogo de imóveis — busca no banco de dados com fallback para data/properties.csv.

A funcao search_properties aceita um `session` opcional:
  - Com session → consulta o PostgreSQL (tabela properties)
  - Sem session  → lê do CSV (compatibilidade com o agente legado)
"""
import csv
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

_PROPERTIES_CSV = Path(__file__).resolve().parents[2] / "data" / "properties.csv"

# Mapeamento de categoria de investimento → valor máximo (R$)
_INVESTIMENTO_VALOR_MAX: dict[str, float] = {
    "acima_2m":     float("inf"),
    "1m_2m":        2_000_000,
    "500k_1m":      1_000_000,
    "400k_500k":    500_000,
    "abaixo_400k":  400_000,
}


def _load_properties() -> list[dict]:
    """Lê o CSV e retorna lista de dicts."""
    if not _PROPERTIES_CSV.exists():
        return []
    with open(_PROPERTIES_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def _matches_bairro(prop_bairro: str, bairro_query: str) -> bool:
    """Verifica se o bairro do imóvel coincide (fuzzy por palavras significativas)."""
    if not bairro_query or bairro_query.lower() in ("", "nao informado", "nao_informado"):
        return True
    pb = prop_bairro.lower()
    bq = bairro_query.lower()
    if bq in pb or pb in bq:
        return True
    words = [w for w in bq.split() if len(w) >= 4]
    return any(w in pb for w in words)


def _matches_situacao(prop_situacao: str, situacao_query: str) -> bool:
    """Verifica se a situação do imóvel coincide com a preferência."""
    if not situacao_query or situacao_query.lower() in ("", "nao informado", "tanto_faz", "tanto faz"):
        return True
    ps = prop_situacao.lower()
    sq = situacao_query.lower()
    if "lancamento" in sq or "lançamento" in sq:
        return "lançamento" in ps or "lancamento" in ps
    if "pronto" in sq:
        return "pronto" in ps
    return True


def _prop_to_dict(prop) -> dict:
    """Converte objeto Property do ORM em dict compativel com o formato do CSV."""
    return {
        "codigo": prop.codigo or "",
        "tipo": prop.tipo or "",
        "situacao": prop.situacao or "",
        "finalidade": prop.finalidade or "",
        "bairro": prop.bairro or "",
        "endereco": prop.endereco or "",
        "suites": str(prop.suites or ""),
        "banheiros": str(prop.banheiros or ""),
        "vagas": str(prop.vagas or ""),
        "area_privativa": str(prop.area_privativa or ""),
        "area_total": str(prop.area_total or ""),
        "valor": str(prop.valor or "0"),
        "condominio": str(prop.condominio or ""),
        "iptu": str(prop.iptu or ""),
        "diferenciais": prop.diferenciais or "",
        "acabamento": prop.acabamento or "",
        "andar": str(prop.andar or ""),
        "total_andares": str(prop.total_andares or ""),
        "elevadores": str(prop.elevadores or ""),
        "unidades_andar": str(prop.unidades_andar or ""),
        "aceita_permuta": "Sim" if prop.aceita_permuta else "Não",
        "aceita_financiamento": "Sim" if prop.aceita_financiamento else "Não",
        "disponivel": "Sim" if prop.disponivel else "Não",
        "lancamento": "Sim" if prop.lancamento else "Não",
        "empreendimento": prop.empreendimento or "",
        "construtora": prop.construtora or "",
        "entrega": prop.entrega or "",
        "fotos_url": prop.fotos_url or "",
        "tour_360": prop.tour_360 or "",
        "planta_url": prop.planta_url or "",
        "video_url": prop.video_url or "",
        "descricao": prop.descricao or "",
        "observacoes": prop.observacoes or "",
        "corretor_responsavel": prop.corretor_responsavel or "",
        "tags": prop.tags or "",
    }


def _filter_csv(
    props: list[dict],
    bairro: str,
    situacao: str,
    finalidade: str,
    valor_max: float,
    tipo: str,
    lancamento: Optional[bool],
    apenas_disponiveis: bool,
) -> list[dict]:
    results = []
    for p in props:
        if apenas_disponiveis and p.get("disponivel", "").strip().lower() != "sim":
            continue
        if finalidade and p.get("finalidade", "").strip().lower() != finalidade.lower():
            continue
        if not _matches_situacao(p.get("situacao", ""), situacao):
            continue
        if lancamento is not None:
            eh_lanc = p.get("lancamento", "").strip().lower() == "sim"
            if eh_lanc != lancamento:
                continue
        if tipo and tipo.lower() not in ("", "nao informado"):
            tipo_words = [w for w in tipo.lower().split() if len(w) >= 4]
            p_tipo = p.get("tipo", "").lower()
            if tipo_words and not any(w in p_tipo for w in tipo_words):
                continue
        try:
            p_valor = float(p.get("valor", "0"))
            if p_valor > valor_max:
                continue
        except (ValueError, TypeError):
            pass
        if _matches_bairro(p.get("bairro", ""), bairro):
            results.append(p)
    return results


async def search_properties(
    bairro: str = "",
    situacao: str = "",
    finalidade: str = "Venda",
    investimento_categoria: str = "",
    tipo: str = "",
    lancamento: Optional[bool] = None,
    apenas_disponiveis: bool = True,
    session: Optional[AsyncSession] = None,
) -> list[dict]:
    """
    Busca imóveis compatíveis com o perfil do lead.

    Com `session`: consulta o banco de dados PostgreSQL.
    Sem `session`: lê do CSV (fallback para compatibilidade).

    Returns:
        Lista de dicts com imóveis compatíveis (ordenados por valor crescente)
    """
    valor_max = _INVESTIMENTO_VALOR_MAX.get(investimento_categoria, float("inf"))

    if session is not None:
        from src.services.property_service import PropertyService
        service = PropertyService(session)
        db_disponivel = True if apenas_disponiveis else None
        props_orm = await service.get_all(
            bairro=bairro,
            finalidade=finalidade,
            tipo=tipo,
            disponivel=db_disponivel,
            lancamento=lancamento,
            valor_max=valor_max if valor_max != float("inf") else None,
        )
        results = [_prop_to_dict(p) for p in props_orm]

        if situacao:
            results = [p for p in results if _matches_situacao(p.get("situacao", ""), situacao)]

        # Se nao encontrou com bairro, retorna sem filtro de bairro
        if not results and bairro:
            props_orm = await service.get_all(
                finalidade=finalidade,
                tipo=tipo,
                disponivel=db_disponivel,
                lancamento=lancamento,
                valor_max=valor_max if valor_max != float("inf") else None,
            )
            results = [_prop_to_dict(p) for p in props_orm]
            if situacao:
                results = [p for p in results if _matches_situacao(p.get("situacao", ""), situacao)]

        return results

    # --- Fallback: CSV ---
    props = _load_properties()
    results = _filter_csv(props, bairro, situacao, finalidade, valor_max, tipo, lancamento, apenas_disponiveis)

    if not results:
        results = _filter_csv(props, "", situacao, finalidade, valor_max, tipo, lancamento, apenas_disponiveis)

    try:
        results.sort(key=lambda p: float(p.get("valor", "0")))
    except (ValueError, TypeError):
        pass

    return results
