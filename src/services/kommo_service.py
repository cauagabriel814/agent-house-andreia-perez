"""
kommo_service.py - Integração com KOMMO CRM (amoCRM) via API REST v4.

Autenticação: long-lived access token gerado nas integrações do KOMMO.
Base URL: https://{subdomain}.kommo.com/api/v4

Fluxo de sincronização:
  1. greeting_node → get_or_create_contact + create_lead_deal → salva IDs
  2. Cada etapa de nó → sync_tags (1 chamada por step, sync em lote)
  3. Score calculado (launch/investor) → update_lead_stage

Conversão de tags internas para labels KOMMO:
  - Booleanas ("true") → label simples: "proprietario_venda"
  - Com valor          → "key:value":   "localizacao:Jardim Italia"
"""

import json
import re
from typing import Any, Optional

import httpx

from src.config.settings import settings
from src.utils.logger import logger


def _only_digits(s: str) -> str:
    """Remove tudo exceto digitos de uma string."""
    return re.sub(r"\D", "", s or "")


def _tags_to_kommo_labels(tags: dict[str, str]) -> list[dict]:
    """
    Converte o dict interno de tags para o formato de labels do KOMMO.

    Regras:
      - valor "true"  → {"name": "tag_key"}
      - valor "false" → ignorado (não envia label negativa)
      - outros        → {"name": "tag_key:tag_value"}
    """
    labels = []
    for key, value in tags.items():
        if not key or value is None:
            continue
        if str(value).lower() == "false":
            continue
        if str(value).lower() == "true":
            labels.append({"name": key})
        else:
            # Truncar valor longo para evitar labels gigantes
            val_str = str(value)[:80]
            labels.append({"name": f"{key}:{val_str}"})
    return labels


class KommoService:
    """Cliente KOMMO API v4 para criação/atualização de contatos, negócios e tags."""

    def __init__(self):
        subdomain = settings.kommo_subdomain.strip()
        self.base_url = f"https://{subdomain}.kommo.com/api/v4" if subdomain else ""
        self.access_token = settings.kommo_access_token.strip()
        self._enabled = bool(self.base_url and self.access_token)

    def is_enabled(self) -> bool:
        if not self._enabled:
            logger.debug("KOMMO | Integração desabilitada (KOMMO_SUBDOMAIN ou KOMMO_ACCESS_TOKEN ausentes).")
            return False
        return True

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Contatos
    # ------------------------------------------------------------------

    async def find_contact_by_phone(self, phone: str) -> Optional[dict]:
        """
        Busca contato pelo número de telefone.

        A API KOMMO usa busca fuzzy (``query``), por isso validamos que o
        contato retornado realmente possui o campo PHONE com os mesmos
        dígitos. Retorna None se não encontrar ou se não houver match exato.
        """
        if not self.is_enabled():
            return None
        phone_digits = _only_digits(phone)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/contacts",
                    headers=self._headers(),
                    params={"query": phone, "limit": 10},
                )
                if response.status_code == 204:
                    return None
                response.raise_for_status()
                data = response.json()
                embedded = data.get("_embedded", {})
                contacts = embedded.get("contacts", [])
                if not contacts:
                    return None

                # Validar PHONE field de cada candidato
                for contact in contacts:
                    for field in contact.get("custom_fields_values") or []:
                        if field.get("field_code") == "PHONE":
                            for val in field.get("values") or []:
                                if _only_digits(val.get("value", "")) == phone_digits:
                                    return contact

                # Fuzzy match sem correspondência exata de PHONE
                logger.debug(
                    "KOMMO | find_contact_by_phone | fuzzy retornou %d contato(s) "
                    "mas nenhum com PHONE=%s exato",
                    len(contacts),
                    phone,
                )
                return None
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KOMMO | Erro ao buscar contato | phone=%s | status=%s",
                phone,
                exc.response.status_code,
            )
            return None
        except Exception as exc:
            logger.error("KOMMO | Falha ao buscar contato | phone=%s | erro=%s", phone, exc)
            return None

    async def create_contact(
        self,
        phone: str,
        name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[dict]:
        """Cria um novo contato no KOMMO com telefone, nome e email."""
        if not self.is_enabled():
            return None

        custom_fields: list[dict] = [
            {
                "field_code": "PHONE",
                "values": [{"value": phone, "enum_code": "WORK"}],
            }
        ]
        if email:
            custom_fields.append(
                {
                    "field_code": "EMAIL",
                    "values": [{"value": email, "enum_code": "WORK"}],
                }
            )

        payload = [
            {
                "name": name or phone,
                "custom_fields_values": custom_fields,
            }
        ]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/contacts",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                contacts = data.get("_embedded", {}).get("contacts", [])
                if contacts:
                    contact = contacts[0]
                    logger.info(
                        "KOMMO | Contato criado | id=%s | phone=%s",
                        contact.get("id"),
                        phone,
                    )
                    return contact
                return None
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KOMMO | Erro ao criar contato | phone=%s | status=%s | body=%s",
                phone,
                exc.response.status_code,
                exc.response.text[:200],
            )
            return None
        except Exception as exc:
            logger.error("KOMMO | Falha ao criar contato | phone=%s | erro=%s", phone, exc)
            return None

    async def update_contact(
        self,
        contact_id: str | int,
        name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[dict]:
        """Atualiza nome e/ou email de um contato existente."""
        if not self.is_enabled():
            return None

        payload: dict[str, Any] = {}
        if name:
            payload["name"] = name
        if email:
            payload["custom_fields_values"] = [
                {
                    "field_code": "EMAIL",
                    "values": [{"value": email, "enum_code": "WORK"}],
                }
            ]

        if not payload:
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.patch(
                    f"{self.base_url}/contacts/{contact_id}",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                logger.info("KOMMO | Contato atualizado | id=%s", contact_id)
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KOMMO | Erro ao atualizar contato | id=%s | status=%s",
                contact_id,
                exc.response.status_code,
            )
            return None
        except Exception as exc:
            logger.error("KOMMO | Falha ao atualizar contato | id=%s | erro=%s", contact_id, exc)
            return None

    async def get_or_create_contact(
        self,
        phone: str,
        name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> tuple[Optional[dict], bool]:
        """
        Busca contato pelo telefone ou cria novo.
        Retorna (contact_dict, created: bool). contact_dict pode ser None em caso de erro.
        """
        existing = await self.find_contact_by_phone(phone)
        if existing:
            # Atualiza nome/email se foram fornecidos
            if name or email:
                await self.update_contact(existing["id"], name=name, email=email)
            return existing, False
        contact = await self.create_contact(phone, name=name, email=email)
        return contact, True

    # ------------------------------------------------------------------
    # Negócios (Leads/Deals)
    # ------------------------------------------------------------------

    async def create_lead_deal(
        self,
        contact_id: str | int,
        phone: str,
        pipeline_id: Optional[int] = None,
        status_id: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Cria um negócio (deal) no KOMMO vinculado ao contato.
        Retorna o dict do negócio criado ou None em caso de erro.
        """
        if not self.is_enabled():
            return None

        pipeline_id = pipeline_id or settings.kommo_pipeline_id or None
        payload: dict[str, Any] = {
            "name": f"Lead WhatsApp {phone}",
            "_embedded": {
                "contacts": [{"id": int(contact_id)}],
            },
        }
        if pipeline_id:
            payload["pipeline_id"] = pipeline_id
        if status_id:
            payload["status_id"] = status_id

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/leads",
                    headers=self._headers(),
                    json=[payload],
                )
                response.raise_for_status()
                data = response.json()
                leads = data.get("_embedded", {}).get("leads", [])
                if leads:
                    deal = leads[0]
                    logger.info(
                        "KOMMO | Negócio criado | id=%s | contact_id=%s | phone=%s",
                        deal.get("id"),
                        contact_id,
                        phone,
                    )
                    return deal
                return None
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KOMMO | Erro ao criar negócio | phone=%s | status=%s | body=%s",
                phone,
                exc.response.status_code,
                exc.response.text[:200],
            )
            return None
        except Exception as exc:
            logger.error("KOMMO | Falha ao criar negócio | phone=%s | erro=%s", phone, exc)
            return None

    async def update_lead_stage(
        self,
        kommo_lead_id: str | int,
        status_id: int,
    ) -> Optional[dict]:
        """Atualiza o estágio (status) de um negócio no pipeline do KOMMO."""
        if not self.is_enabled():
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload: dict[str, Any] = {"status_id": status_id}
                if settings.kommo_pipeline_id:
                    payload["pipeline_id"] = settings.kommo_pipeline_id
                response = await client.patch(
                    f"{self.base_url}/leads/{kommo_lead_id}",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                logger.info(
                    "KOMMO | Stage atualizado | lead_id=%s | status_id=%s",
                    kommo_lead_id,
                    status_id,
                )
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KOMMO | Erro ao atualizar stage | lead_id=%s | status=%s",
                kommo_lead_id,
                exc.response.status_code,
            )
            return None
        except Exception as exc:
            logger.error(
                "KOMMO | Falha ao atualizar stage | lead_id=%s | erro=%s",
                kommo_lead_id,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    async def add_tags_to_lead(
        self,
        kommo_lead_id: str | int,
        tag_labels: list[dict],
    ) -> bool:
        """
        Adiciona/substitui tags de um negócio. tag_labels = [{"name": "..."}].
        Usa PATCH /leads com _embedded.tags.
        """
        if not self.is_enabled() or not tag_labels:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.patch(
                    f"{self.base_url}/leads",
                    headers=self._headers(),
                    json=[
                        {
                            "id": int(kommo_lead_id),
                            "_embedded": {"tags": tag_labels},
                        }
                    ],
                )
                response.raise_for_status()
                return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KOMMO | Erro ao adicionar tags ao negócio | lead_id=%s | status=%s",
                kommo_lead_id,
                exc.response.status_code,
            )
            return False
        except Exception as exc:
            logger.error(
                "KOMMO | Falha ao adicionar tags ao negócio | lead_id=%s | erro=%s",
                kommo_lead_id,
                exc,
            )
            return False

    async def add_tags_to_contact(
        self,
        kommo_contact_id: str | int,
        tag_labels: list[dict],
    ) -> bool:
        """
        Adiciona/substitui tags de um contato. tag_labels = [{"name": "..."}].
        Usa PATCH /contacts com _embedded.tags.
        """
        if not self.is_enabled() or not tag_labels:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.patch(
                    f"{self.base_url}/contacts",
                    headers=self._headers(),
                    json=[
                        {
                            "id": int(kommo_contact_id),
                            "_embedded": {"tags": tag_labels},
                        }
                    ],
                )
                response.raise_for_status()
                return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KOMMO | Erro ao adicionar tags ao contato | contact_id=%s | status=%s",
                kommo_contact_id,
                exc.response.status_code,
            )
            return False
        except Exception as exc:
            logger.error(
                "KOMMO | Falha ao adicionar tags ao contato | contact_id=%s | erro=%s",
                kommo_contact_id,
                exc,
            )
            return False

    async def sync_tags(
        self,
        kommo_lead_id: Optional[str | int],
        kommo_contact_id: Optional[str | int],
        tags: dict[str, str],
    ) -> None:
        """
        Sincroniza o dict de tags internas para o KOMMO (negócio + contato).

        Converte tags key-value para labels KOMMO e envia em lote.
        Falhas são silenciosas (apenas logadas) para não bloquear o fluxo.
        """
        if not self.is_enabled() or not tags:
            return

        tag_labels = _tags_to_kommo_labels(tags)
        if not tag_labels:
            return

        logger.info(
            "KOMMO | Sincronizando %d tags | lead_id=%s | contact_id=%s",
            len(tag_labels),
            kommo_lead_id,
            kommo_contact_id,
        )

        if kommo_lead_id:
            await self.add_tags_to_lead(kommo_lead_id, tag_labels)
        if kommo_contact_id:
            await self.add_tags_to_contact(kommo_contact_id, tag_labels)

    async def add_note_to_lead(self, kommo_lead_id: str | int, text: str) -> bool:
        """Adiciona uma nota (common note) ao negócio no KOMMO."""
        if not self.is_enabled() or not kommo_lead_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/leads/{kommo_lead_id}/notes",
                    headers=self._headers(),
                    json=[{"note_type": "common", "params": {"text": text}}],
                )
                response.raise_for_status()
                logger.info("KOMMO | Nota adicionada | lead_id=%s", kommo_lead_id)
                return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KOMMO | Erro ao adicionar nota | lead_id=%s | status=%s",
                kommo_lead_id,
                exc.response.status_code,
            )
            return False
        except Exception as exc:
            logger.error("KOMMO | Falha ao adicionar nota | lead_id=%s | erro=%s", kommo_lead_id, exc)
            return False

    def stage_id_for_classification(self, classification: str) -> Optional[int]:
        """
        Retorna o ID do estagio KOMMO para a classificacao do lead.

        Aceita tanto classificacoes (quente/morno/frio) quanto chaves diretas
        do stage map (visita_agendada, convertido, em_qualificacao, etc.).

        Mapeamento de classificacoes:
          quente -> oportunidade_quente
          morno  -> follow_up_programado
          frio   -> nutricao_ativa
        """
        stage_map = settings.kommo_stage_map_dict
        mapping = {
            "quente": "oportunidade_quente",
            "morno": "follow_up_programado",
            "frio": "nutricao_ativa",
        }
        stage_key = mapping.get(classification, classification)
        return stage_map.get(stage_key)
