from datetime import date, datetime, timezone
from typing import Annotated, Any
from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_object_id(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, ObjectId):
        return str(v)
    return str(v)


PyObjectId = Annotated[str, BeforeValidator(validate_object_id)]


def _sanitize_for_mongo(val: Any) -> Any:
    if isinstance(val, date) and not isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, dict):
        return {k: _sanitize_for_mongo(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_sanitize_for_mongo(v) for v in val]
    return val


class MongoBaseModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def to_mongo(self, exclude_none: bool = False) -> dict[str, Any]:
        data = self.model_dump(by_alias=True, exclude_none=exclude_none)
        if "_id" in data:
            if data["_id"] is None:
                data.pop("_id")
            elif isinstance(data["_id"], str) and ObjectId.is_valid(data["_id"]):
                data["_id"] = ObjectId(data["_id"])
        return _sanitize_for_mongo(data)


