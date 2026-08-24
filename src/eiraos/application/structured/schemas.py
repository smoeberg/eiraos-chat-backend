from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


CONTENT_EXTRACTION_SCHEMA_VERSION = "1.0"


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=100)


class ContentExtractionSchema(BaseModel):
    """Canonical structured-output contract for F1 content extraction."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=2000)
    content_type: Literal["article", "brief", "transcript", "note", "other"]
    language: str = Field(min_length=2, max_length=20)
    key_points: list[str] = Field(min_length=1, max_length=10)
    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=25)

    @field_validator("key_points")
    @classmethod
    def validate_key_points(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("key_points must not contain empty values")
        if len({item.casefold() for item in cleaned}) != len(cleaned):
            raise ValueError("key_points must not contain duplicates")
        return cleaned

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return value.strip().lower()
