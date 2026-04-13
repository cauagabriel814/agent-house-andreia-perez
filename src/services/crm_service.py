"""
CRM Service - Integracao com CRM externo via REST API.

Pipeline de status mapeado do PLANNING.md:
  lead_novo → em_qualificacao → qualificado
      → oportunidade_quente | follow_up_programado | nutricao_ativa
      → visita_agendada → negociacao → convertido | perdido
"""

import uuid
from typing import Any, Optional

import httpx

from src.config.settings import settings
from src.utils.logger import logger

# Mapeamento de status internos para nomes do pipeline
CRM_PIPELINE_STAGES = {
    "lead_novo": "Lead Novo",
    "em_qualificacao": "Em Qualificacao",
    "qualificado": "Qualificado",
    "oportunidade_quente": "Oportunidade Quente",
    "follow_up_programado": "Follow-up Programado",
    "nutricao_ativa": "Nutricao Ativa",
    "visita_agendada": "Visita Agendada",
    "retorno_agendado": "Retorno Agendado",
    "negociacao": "Em Negociacao",
    "convertido": "Convertido",
    "perdido": "Perdido",
}


class CRMService:
    """Client HTTP para o CRM externo (REST API generica)."""

    def __init__(self):
        self.base_url = settings.crm_base_url.rstrip("/")
        self.api_key = settings.crm_api_key
        self.pipeline_id = settings.crm_pipeline_id
        self._enabled = bool(self.base_url and self.api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _is_enabled(self) -> bool:
        if not self._enabled:
            logger.warning("CRM nao configurado (CRM_BASE_URL ou CRM_API_KEY ausentes). Operacao ignorada.")
            return False
        return True

    async def create_opportunity(
        self,
        lead_id: str | uuid.UUID,
        phone: str,
        name: Optional[str],
        email: Optional[str],
        stage: str = "lead_novo",
        score: Optional[int] = None,
        classification: Optional[str] = None,
        tags: Optional[dict] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Cria uma oportunidade no CRM para o lead qualificado."""
        if not self._is_enabled():
            return {"status": "skipped", "reason": "crm_not_configured"}

        stage_name = CRM_PIPELINE_STAGES.get(stage, stage)
        payload: dict[str, Any] = {
            "external_id": str(lead_id),
            "phone": phone,
            "name": name or "",
            "email": email or "",
            "pipeline_id": self.pipeline_id,
            "stage": stage_name,
            "score": score,
            "classification": classification,
            "source": "whatsapp_andreia",
            "tags": tags or {},
        }
        if extra:
            payload.update(extra)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/opportunities",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                logger.info("CRM | Oportunidade criada | lead_id=%s | crm_id=%s", lead_id, data.get("id"))
                return data
        except httpx.HTTPStatusError as exc:
            logger.error("CRM | Erro HTTP ao criar oportunidade | lead_id=%s | status=%s", lead_id, exc.response.status_code)
            return {"status": "error", "code": exc.response.status_code}
        except Exception as exc:
            logger.error("CRM | Falha ao criar oportunidade | lead_id=%s | erro=%s", lead_id, exc)
            return {"status": "error", "reason": str(exc)}

    async def update_status(
        self,
        crm_id: str,
        stage: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Atualiza o estagio/status de uma oportunidade no CRM."""
        if not self._is_enabled():
            return {"status": "skipped", "reason": "crm_not_configured"}

        stage_name = CRM_PIPELINE_STAGES.get(stage, stage)
        payload: dict[str, Any] = {"stage": stage_name}
        if extra:
            payload.update(extra)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.patch(
                    f"{self.base_url}/opportunities/{crm_id}",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                logger.info("CRM | Status atualizado | crm_id=%s | stage=%s", crm_id, stage_name)
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("CRM | Erro HTTP ao atualizar status | crm_id=%s | status=%s", crm_id, exc.response.status_code)
            return {"status": "error", "code": exc.response.status_code}
        except Exception as exc:
            logger.error("CRM | Falha ao atualizar status | crm_id=%s | erro=%s", crm_id, exc)
            return {"status": "error", "reason": str(exc)}

    async def update_lead_data(
        self,
        crm_id: str,
        data: dict[str, Any],
    ) -> dict:
        """Atualiza campos do lead/oportunidade no CRM."""
        if not self._is_enabled():
            return {"status": "skipped", "reason": "crm_not_configured"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.patch(
                    f"{self.base_url}/opportunities/{crm_id}",
                    headers=self._headers(),
                    json=data,
                )
                response.raise_for_status()
                logger.info("CRM | Dados atualizados | crm_id=%s", crm_id)
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("CRM | Erro HTTP ao atualizar dados | crm_id=%s | status=%s", crm_id, exc.response.status_code)
            return {"status": "error", "code": exc.response.status_code}
        except Exception as exc:
            logger.error("CRM | Falha ao atualizar dados | crm_id=%s | erro=%s", crm_id, exc)
            return {"status": "error", "reason": str(exc)}

    async def get_opportunity_by_lead(self, lead_id: str | uuid.UUID) -> Optional[dict]:
        """Busca a oportunidade do CRM pelo ID interno do lead."""
        if not self._is_enabled():
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/opportunities",
                    headers=self._headers(),
                    params={"external_id": str(lead_id)},
                )
                response.raise_for_status()
                results = response.json()
                if isinstance(results, list) and results:
                    return results[0]
                if isinstance(results, dict) and results.get("data"):
                    return results["data"][0] if results["data"] else None
                return None
        except Exception as exc:
            logger.error("CRM | Falha ao buscar oportunidade | lead_id=%s | erro=%s", lead_id, exc)
            return None
