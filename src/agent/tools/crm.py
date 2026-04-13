import uuid
from typing import Optional

from src.services.kommo_service import KommoService


async def update_crm(
    lead_id: str | uuid.UUID,
    data: dict,
    stage: Optional[str] = None,
    crm_id: Optional[str] = None,
) -> dict:
    """
    Tool: Cria ou atualiza dados no KOMMO CRM.

    Se crm_id (kommo_lead_id) for fornecido, atualiza o negocio existente.
    Caso contrario, retorna dict vazio (criacao e feita pelo greeting_node).
    """
    service = KommoService()

    if not service.is_enabled():
        return {}

    if crm_id:
        tags = data.get("tags") or {}
        contact_id = data.get("kommo_contact_id")

        if tags:
            await service.sync_tags(crm_id, contact_id, tags)

        if stage:
            stage_id = service.stage_id_for_classification(stage)
            if stage_id:
                await service.update_lead_stage(crm_id, stage_id)

        return {"kommo_lead_id": crm_id}

    return {}
