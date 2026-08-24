from __future__ import annotations

from typing import Any

from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter
from eiraos.core.exceptions import EiraOSException
from eiraos.application.structured.schemas import ContentExtractionSchema


class StructuredExtractionService:
    """Application service for schema-first content extraction."""

    def __init__(self, provider: OpenAIProviderAdapter):
        self.provider = provider

    async def extract(self, text: str, model: str) -> dict[str, Any]:
        if not text.strip():
            raise EiraOSException(
                title="Invalid extraction input",
                detail="Extraction text must not be empty.",
                status_code=400,
            )

        result = await self.provider.generate_structured_output(
            messages=[{"role": "user", "content": text}],
            model=model,
            schema_name="content_extraction_v1",
            schema=ContentExtractionSchema.model_json_schema(),
        )
        validated = ContentExtractionSchema.model_validate(result)
        return {
            "schema_version": "1.0",
            "data": validated.model_dump(mode="json"),
        }
