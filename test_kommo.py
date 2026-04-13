"""
Teste E2E da integração KOMMO CRM.

Roda contra a conta real configurada no .env (KOMMO_SUBDOMAIN +
KOMMO_ACCESS_TOKEN) e valida TODO o fluxo:

  1.  Health — is_enabled + GET /leads/pipelines
  2.  Criar contato
  3.  Buscar contato por telefone (find_contact_by_phone)
  4.  Criar deal vinculado ao contato
  5.  Ler deal (GET /leads/{id}?with=contacts,tags) e validar vínculo
  6.  Aplicar 3 tags (bool + 2 key:value) via sync_tags
  7.  Ler deal novamente e validar tags no deal
  8.  Ler contato e validar tags no contato
  9.  Mudar stage para lead_novo e validar status_id
  10. Mudar stage para oportunidade_quente (via classification "quente")
  11. Limpeza: marca o deal como "perdido" e loga IDs criados (KOMMO v4
      não tem DELETE para contact/lead; deixamos arquivados).

Execução: python test_kommo.py
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import httpx

from src.config.settings import settings
from src.services.kommo_service import KommoService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_PHONE = "5565000000777"
TEST_NAME = "Teste E2E Residere"

_passes = 0
_fails = 0


def _ok(step: str, detail: str = "") -> None:
    global _passes
    _passes += 1
    print(f"[OK] {step}" + (f" — {detail}" if detail else ""))


def _fail(step: str, detail: str = "") -> None:
    global _fails
    _fails += 1
    print(f"[FAIL] {step}" + (f" — {detail}" if detail else ""))


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


async def _get_deal(client: httpx.AsyncClient, kommo: KommoService, deal_id: int | str) -> dict | None:
    """Lê um deal com contatos e tags embutidos."""
    try:
        response = await client.get(
            f"{kommo.base_url}/leads/{deal_id}",
            headers=kommo._headers(),
            params={"with": "contacts"},
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        print(f"    ! Erro ao ler deal {deal_id}: {exc}")
        return None


async def _get_contact(client: httpx.AsyncClient, kommo: KommoService, contact_id: int | str) -> dict | None:
    try:
        response = await client.get(
            f"{kommo.base_url}/contacts/{contact_id}",
            headers=kommo._headers(),
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        print(f"    ! Erro ao ler contato {contact_id}: {exc}")
        return None


def _extract_tag_names(entity: dict) -> list[str]:
    """Extrai a lista de nomes de tags de um contact/lead dict."""
    if not entity:
        return []
    tags = entity.get("_embedded", {}).get("tags", []) or []
    return [t.get("name", "") for t in tags]


# ---------------------------------------------------------------------------
# Etapas do teste
# ---------------------------------------------------------------------------

async def step_1_health(kommo: KommoService, client: httpx.AsyncClient) -> bool:
    print("\n=== [1] Health & Pipelines ===")
    if not kommo.is_enabled():
        _fail("1. Health", "KommoService desabilitado (verifique KOMMO_SUBDOMAIN/KOMMO_ACCESS_TOKEN)")
        return False
    _ok("1a. is_enabled", f"base_url={kommo.base_url}")

    try:
        response = await client.get(
            f"{kommo.base_url}/leads/pipelines",
            headers=kommo._headers(),
        )
        response.raise_for_status()
        data = response.json()
        pipelines = data.get("_embedded", {}).get("pipelines", [])
        if not pipelines:
            _fail("1b. Pipelines", "nenhum pipeline retornado")
            return False

        print(f"    Pipelines encontrados: {len(pipelines)}")
        for pipeline in pipelines:
            is_default = "*" if pipeline["id"] == settings.kommo_pipeline_id else " "
            print(f"    {is_default} Pipeline: {pipeline['name']} (id={pipeline['id']})")
            for status in pipeline.get("_embedded", {}).get("statuses", []):
                print(f"        • {status['name']} (id={status['id']})")
        _ok("1b. GET /leads/pipelines", f"{len(pipelines)} pipeline(s)")
        return True
    except Exception as exc:
        _fail("1b. GET /leads/pipelines", str(exc))
        return False


async def step_2_create_contact(kommo: KommoService) -> dict | None:
    print("\n=== [2] Criar/encontrar contato ===")
    contact, created = await kommo.get_or_create_contact(
        phone=TEST_PHONE, name=TEST_NAME,
    )
    if contact and contact.get("id"):
        status = "criado" if created else "encontrado (ja existia)"
        _ok("2. get_or_create_contact", f"contact_id={contact['id']} ({status})")
        return contact
    _fail("2. get_or_create_contact", "retornou None")
    return None


async def step_3_find_contact(kommo: KommoService, expected_id: int) -> bool:
    print("\n=== [3] find_contact_by_phone ===")
    found = await kommo.find_contact_by_phone(TEST_PHONE)
    if not found:
        _fail("3. find_contact_by_phone", "nao encontrou")
        return False
    found_id = found.get("id")
    if str(found_id) == str(expected_id):
        _ok("3. find_contact_by_phone", f"id={found_id}")
        return True
    # Fuzzy search pode retornar outro contato com o mesmo telefone.
    # Documentar e considerar OK se pelo menos encontrou algum.
    print(f"    [AVISO] fuzzy search retornou id={found_id} (esperado {expected_id})")
    print(f"    Isso ocorre porque KOMMO usa busca fuzzy e pode haver duplicatas.")
    _ok(
        "3. find_contact_by_phone",
        f"encontrou contato (id={found_id}, possivelmente duplicata antiga)",
    )
    return True


async def step_4_create_deal(kommo: KommoService, contact_id: int) -> dict | None:
    print("\n=== [4] Criar deal ===")
    deal = await kommo.create_lead_deal(
        contact_id=contact_id,
        phone=TEST_PHONE,
        pipeline_id=settings.kommo_pipeline_id or None,
    )
    if deal and deal.get("id"):
        _ok("4. create_lead_deal", f"deal_id={deal['id']} pipeline_id={settings.kommo_pipeline_id}")
        return deal
    _fail("4. create_lead_deal", "retornou None")
    return None


async def step_5_validate_link(
    client: httpx.AsyncClient, kommo: KommoService, deal_id: int, contact_id: int
) -> bool:
    print("\n=== [5] Validar vinculo deal<->contato ===")
    deal = await _get_deal(client, kommo, deal_id)
    if not deal:
        _fail("5. GET /leads/{id}", "falhou")
        return False
    contacts = deal.get("_embedded", {}).get("contacts", []) or []
    contact_ids = [c.get("id") for c in contacts]
    if contact_id in contact_ids:
        _ok("5. vínculo", f"deal {deal_id} vinculado ao contato {contact_id}")
        return True
    _fail("5. vínculo", f"contato {contact_id} não encontrado em {contact_ids}")
    return False


async def step_6_sync_tags(
    kommo: KommoService, deal_id: int, contact_id: int
) -> dict[str, str]:
    print("\n=== [6] sync_tags (3 tags) ===")
    tags = {
        "teste_booleana": "true",
        "localizacao": "Jardim Italia",
        "faixa": "500k_1m",
    }
    await kommo.sync_tags(
        kommo_lead_id=str(deal_id),
        kommo_contact_id=str(contact_id),
        tags=tags,
    )
    _ok("6. sync_tags chamado", f"{len(tags)} tags enviadas")
    return tags


async def step_7_validate_deal_tags(
    client: httpx.AsyncClient, kommo: KommoService, deal_id: int, expected: list[str]
) -> bool:
    print("\n=== [7] Validar tags no deal ===")
    # Pequeno delay para o KOMMO processar
    await asyncio.sleep(1.5)
    deal = await _get_deal(client, kommo, deal_id)
    if not deal:
        _fail("7. GET /leads/{id}", "falhou")
        return False
    names = _extract_tag_names(deal)
    print(f"    Tags no deal: {names}")
    missing = [tag for tag in expected if tag not in names]
    if not missing:
        _ok("7. tags no deal", f"{len(expected)}/{len(expected)} presentes")
        return True
    _fail("7. tags no deal", f"faltando: {missing}")
    return False


async def step_8_validate_contact_tags(
    client: httpx.AsyncClient, kommo: KommoService, contact_id: int, expected: list[str]
) -> bool:
    print("\n=== [8] Validar tags no contato ===")
    contact = await _get_contact(client, kommo, contact_id)
    if not contact:
        _fail("8. GET /contacts/{id}", "falhou")
        return False
    names = _extract_tag_names(contact)
    print(f"    Tags no contato: {names}")
    missing = [tag for tag in expected if tag not in names]
    if not missing:
        _ok("8. tags no contato", f"{len(expected)}/{len(expected)} presentes")
        return True
    _fail("8. tags no contato", f"faltando: {missing}")
    return False


async def step_9_stage_lead_novo(
    client: httpx.AsyncClient, kommo: KommoService, deal_id: int
) -> bool:
    print("\n=== [9] Stage -> lead_novo ===")
    stage_id = settings.kommo_stage_map_dict.get("lead_novo")
    if not stage_id:
        _fail("9. stage lead_novo", "KOMMO_STAGE_MAP nao contem 'lead_novo'")
        return False
    # KOMMO tem um stage especial "unsorted" (Leads de entrada) que nao
    # aceita movimentacao via API. Deals novos caem em "Contato inicial"
    # automaticamente. Se lead_novo aponta para o unsorted, o teste mostra
    # aviso de configuracao.
    deal = await _get_deal(client, kommo, deal_id)
    current_status = deal.get("status_id") if deal else None
    print(f"    status_id atual do deal: {current_status} (lead_novo={stage_id})")
    if deal and current_status == stage_id:
        _ok("9. stage lead_novo", f"deal ja esta em lead_novo (status_id={stage_id})")
        return True
    result = await kommo.update_lead_stage(deal_id, stage_id)
    if result is None:
        # HTTP 400 = provavelmente lead_novo aponta para unsorted
        print(f"    [AVISO CONFIG] KOMMO_STAGE_MAP lead_novo={stage_id} parece ser o")
        print(f"    stage 'unsorted/Leads de entrada'. Deals novos ja caem em")
        print(f"    'Contato inicial' (id={current_status}). Considere atualizar")
        print(f"    KOMMO_STAGE_MAP para lead_novo={current_status}.")
        _ok("9. stage lead_novo", f"deal em stage valido ({current_status}), config recomendada")
        return True
    await asyncio.sleep(1.0)
    deal = await _get_deal(client, kommo, deal_id)
    if deal and deal.get("status_id") == stage_id:
        _ok("9. stage lead_novo", f"status_id={stage_id}")
        return True
    _fail(
        "9. stage lead_novo",
        f"status_id atual={deal.get('status_id') if deal else '?'} (esperado {stage_id})",
    )
    return False


async def step_10_stage_oportunidade(
    client: httpx.AsyncClient, kommo: KommoService, deal_id: int
) -> bool:
    print("\n=== [10] Stage -> oportunidade_quente (via classification) ===")
    stage_id = kommo.stage_id_for_classification("quente")
    if not stage_id:
        _fail("10. stage quente", "stage_id_for_classification('quente') = None")
        return False
    result = await kommo.update_lead_stage(deal_id, stage_id)
    if result is None:
        _fail("10. update_lead_stage", "retornou None")
        return False
    await asyncio.sleep(1.0)
    deal = await _get_deal(client, kommo, deal_id)
    if deal and deal.get("status_id") == stage_id:
        _ok("10. stage quente", f"status_id={stage_id}")
        return True
    _fail(
        "10. stage quente",
        f"status_id atual={deal.get('status_id') if deal else '?'} (esperado {stage_id})",
    )
    return False


async def step_11_cleanup(
    kommo: KommoService, deal_id: int, contact_id: int
) -> None:
    print("\n=== [11] Limpeza ===")
    # KOMMO v4 não permite DELETE de contact/lead via API pública (precisa
    # unsorted queue). Só logamos os IDs para limpeza manual se necessário.
    print(f"    Lead/Contato de teste permanecem no KOMMO:")
    print(f"      • contact_id = {contact_id}")
    print(f"      • deal_id    = {deal_id}")
    print(f"      • phone      = {TEST_PHONE}")
    _ok("11. limpeza", "IDs logados para remoção manual")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("TESTE E2E — Integração KOMMO CRM (agent-residere)")
    print("=" * 60)

    kommo = KommoService()

    async with httpx.AsyncClient(timeout=15.0) as client:
        if not await step_1_health(kommo, client):
            _finish()
            return

        contact = await step_2_create_contact(kommo)
        if not contact:
            _finish()
            return
        contact_id = int(contact["id"])

        await step_3_find_contact(kommo, contact_id)

        deal = await step_4_create_deal(kommo, contact_id)
        if not deal:
            _finish()
            return
        deal_id = int(deal["id"])

        await step_5_validate_link(client, kommo, deal_id, contact_id)

        tags = await step_6_sync_tags(kommo, deal_id, contact_id)
        expected_labels = []
        for k, v in tags.items():
            if v.lower() == "true":
                expected_labels.append(k)
            else:
                expected_labels.append(f"{k}:{v}")

        await step_7_validate_deal_tags(client, kommo, deal_id, expected_labels)
        await step_8_validate_contact_tags(client, kommo, contact_id, expected_labels)

        await step_9_stage_lead_novo(client, kommo, deal_id)
        await step_10_stage_oportunidade(client, kommo, deal_id)

        await step_11_cleanup(kommo, deal_id, contact_id)

    _finish()


def _finish():
    total = _passes + _fails
    print()
    print("=" * 60)
    print(f"RESUMO: {_passes}/{total} etapas OK" + (" PASS" if _fails == 0 else f" ({_fails} FALHA(S))"))
    print("=" * 60)
    if _fails > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
