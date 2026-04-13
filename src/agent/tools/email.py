from typing import Optional

from src.services.email_service import EmailService


async def send_email(
    to: str,
    subject: str,
    body: str,
    template: Optional[str] = None,
    template_data: Optional[dict] = None,
) -> dict:
    """
    Tool: Envia email marketing/proposta via SMTP.

    Templates disponiveis:
      - "rental_proposal": Proposta de parceria de locacao
      - "launch_material": Material de lancamento (plantas, tabela, tour virtual)
      - None: Email customizado com subject e body fornecidos
    """
    service = EmailService()

    if template == "rental_proposal":
        data = template_data or {}
        return await service.send_rental_proposal(
            to=to,
            lead_name=data.get("lead_name", ""),
            property_data=data.get("property_data"),
        )

    if template == "launch_material":
        data = template_data or {}
        return await service.send_launch_material(
            to=to,
            lead_name=data.get("lead_name", ""),
            launch_data=data.get("launch_data"),
        )

    return await service.send(to=to, subject=subject, body_html=body)
