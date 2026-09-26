from datetime import datetime, timedelta, timezone
from typing import Any
from pydantic import Field

from bot.models.base import MongoBaseModel, PyObjectId


def default_next_review() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=1)


class Word(MongoBaseModel):
    id: PyObjectId | None = Field(default=None, alias="_id")
    user_id: int
    native_language: str = "uk"
    target_language: str = "en"
    canonical_word: str
    lemma: str
    pos: str
    transcription: str
    translation: str
    corrected_from: str | None = None
    level: str | None = None
    definition: str | None = None
    grammar_notes: list[str] = Field(default_factory=list)
    # Legacy fields
    examples: list[dict[str, str]] = Field(default_factory=list)
    synonyms_collocations: list[str] = Field(default_factory=list)
    extra_data: dict[str, Any] = Field(default_factory=dict)

    # SuperMemo-2 fields
    repetition: int = 0
    interval: int = 1
    ease_factor: float = 2.5
    next_review_at: datetime = Field(default_factory=default_next_review)
    is_archived: bool = False

    def __repr__(self) -> str:
        return f"<Word id={self.id} canonical='{self.canonical_word}' user_id={self.user_id} target={self.target_language}>"

