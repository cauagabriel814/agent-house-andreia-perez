import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.score import LeadScore


class ScoreService:
    """Gerenciamento de scores de leads."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest(self, lead_id: str | uuid.UUID, score_type: str) -> Optional[LeadScore]:
        """Busca o score mais recente de um lead por tipo."""
        result = await self.session.execute(
            select(LeadScore)
            .where(LeadScore.lead_id == lead_id, LeadScore.score_type == score_type)
            .order_by(LeadScore.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        lead_id: str | uuid.UUID,
        score_type: str,
        investimento_pts: int = 0,
        pagamento_pts: int = 0,
        urgencia_pts: int = 0,
        situacao_pts: int = 0,
        dados_pts: int = 0,
    ) -> LeadScore:
        """Cria ou atualiza o score de um lead."""
        total = investimento_pts + pagamento_pts + urgencia_pts + situacao_pts + dados_pts
        classification = _classify(total)

        existing = await self.get_latest(lead_id, score_type)
        if existing:
            existing.investimento_pts = investimento_pts
            existing.pagamento_pts = pagamento_pts
            existing.urgencia_pts = urgencia_pts
            existing.situacao_pts = situacao_pts
            existing.dados_pts = dados_pts
            existing.total_score = total
            existing.classification = classification
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        score = LeadScore(
            lead_id=lead_id,
            score_type=score_type,
            investimento_pts=investimento_pts,
            pagamento_pts=pagamento_pts,
            urgencia_pts=urgencia_pts,
            situacao_pts=situacao_pts,
            dados_pts=dados_pts,
            total_score=total,
            classification=classification,
        )
        self.session.add(score)
        await self.session.commit()
        await self.session.refresh(score)
        return score


def _classify(total_score: int) -> str:
    if total_score >= 80:
        return "quente"
    if total_score >= 50:
        return "morno"
    return "frio"
