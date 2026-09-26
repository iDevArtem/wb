from datetime import date, datetime
from pydantic import Field

from bot.models.base import MongoBaseModel, PyObjectId


class User(MongoBaseModel):
    mongo_id: PyObjectId | None = Field(default=None, alias="_id")
    tg_id: int
    username: str | None = None
    first_name: str | None = None
    timezone: str = "UTC"
    quiet_hours_start: int = 21
    quiet_hours_end: int = 10
    streak: int = 0
    last_activity_date: date | None = None
    last_notified_at: datetime | None = None
    is_active: bool = True
    native_language: str = "uk"
    target_language: str = "en"

    @property
    def id(self) -> int:
        """Compatibility property: user's unique identity is tg_id."""
        return self.tg_id

    def __repr__(self) -> str:
        return f"<User tg_id={self.tg_id} username={self.username} native={self.native_language} target={self.target_language}>"

