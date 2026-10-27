"""Persistência da configuração de IA (linha única) e do consumo de tokens."""

from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.intelligence import AiSettingsModel, AiUsageModel
from app.domain.ai_settings import AiSettings, default_settings


class SqlAiRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_settings(self) -> AiSettings:
        row = await self._session.get(AiSettingsModel, 1)
        if row is None:
            return default_settings()
        return AiSettings(
            enabled=row.enabled,
            provider=row.provider,
            model=row.model,
            base_url=row.base_url,
            api_key_encrypted=row.api_key_encrypted,
            key_last4=row.key_last4,
            embeddings_provider=row.embeddings_provider,
            daily_call_limit=row.daily_call_limit,
            daily_token_limit=row.daily_token_limit,
            updated_at=row.updated_at,
            updated_by=row.updated_by,
        )

    async def save_settings(self, settings: AiSettings) -> None:
        row = await self._session.get(AiSettingsModel, 1)
        if row is None:
            row = AiSettingsModel(id=1)
            self._session.add(row)
        row.enabled = settings.enabled
        row.provider = settings.provider
        row.model = settings.model
        row.base_url = settings.base_url
        row.api_key_encrypted = settings.api_key_encrypted
        row.key_last4 = settings.key_last4
        row.embeddings_provider = settings.embeddings_provider
        row.daily_call_limit = settings.daily_call_limit
        row.daily_token_limit = settings.daily_token_limit
        row.updated_at = settings.updated_at
        row.updated_by = settings.updated_by
        await self._session.flush()

    async def add_usage(
        self,
        *,
        at: datetime,
        provider: str,
        model: str,
        feature: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        ok: bool,
        error: str | None,
    ) -> None:
        await self._session.execute(
            insert(AiUsageModel).values(
                at=at,
                provider=provider,
                model=model,
                feature=feature,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                ok=ok,
                error=error[:300] if error else None,
            )
        )

    async def usage_since(self, since: datetime) -> tuple[int, int]:
        row = (
            await self._session.execute(
                select(
                    func.count(AiUsageModel.id),
                    func.coalesce(
                        func.sum(AiUsageModel.input_tokens + AiUsageModel.output_tokens), 0
                    ),
                ).where(AiUsageModel.at >= since)
            )
        ).one()
        return int(row[0]), int(row[1])

    async def usage_by_day(self, since: datetime, tz: str) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            text(
                """
                SELECT (at AT TIME ZONE :tz)::date AS day, feature,
                       count(*) AS calls,
                       count(*) FILTER (WHERE NOT ok) AS errors,
                       sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens,
                       sum(cost_usd) AS cost_usd
                FROM ai_usage WHERE at >= :since
                GROUP BY 1, 2 ORDER BY 1 DESC, 2
                """
            ),
            {"tz": tz, "since": since},
        )
        return [
            {
                "day": r.day.isoformat(),
                "feature": r.feature,
                "calls": int(r.calls),
                "errors": int(r.errors),
                "input_tokens": int(r.input_tokens or 0),
                "output_tokens": int(r.output_tokens or 0),
                "cost_usd": round(float(r.cost_usd or 0), 6),
            }
            for r in rows
        ]
