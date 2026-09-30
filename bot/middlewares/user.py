import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser

from bot.core.database import get_users_collection
from bot.models.user import User

logger = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        event_user: TgUser | None = data.get("event_from_user")
        if not event_user or event_user.is_bot:
            return await handler(event, data)

        users_col = get_users_collection()
        user_doc = await users_col.find_one({"tg_id": event_user.id})

        if user_doc is None:
            lang_code = getattr(event_user, "language_code", None)
            native_lang = lang_code.split('-')[0] if lang_code else "uk"

            user = User(
                tg_id=event_user.id,
                username=event_user.username,
                first_name=event_user.first_name,
                timezone="UTC",
                streak=1,
                native_language=native_lang,
            )
            result = await users_col.insert_one(user.to_mongo())
            user.mongo_id = str(result.inserted_id)
            logger.info("Registered new user in MongoDB: tg_id=%s, username=%s", user.tg_id, user.username)
        else:
            user = User.model_validate(user_doc)
            # Sync metadata
            if event_user.username and user.username != event_user.username:
                user.username = event_user.username
            if event_user.first_name and user.first_name != event_user.first_name:
                user.first_name = event_user.first_name

        # Calculate streak based on user's timezone
        try:
            tz = ZoneInfo(user.timezone)
        except Exception:
            tz = timezone.utc

        now_local = datetime.now(tz).date()

        if user.last_activity_date is None:
            user.streak = 1
            user.last_activity_date = now_local
        elif user.last_activity_date == now_local:
            pass  # Already counted today
        elif user.last_activity_date == now_local - timedelta(days=1):
            user.streak += 1
            user.last_activity_date = now_local
        else:
            # Streak broken
            user.streak = 1
            user.last_activity_date = now_local

        user.updated_at = datetime.now(timezone.utc)
        await users_col.update_one(
            {"tg_id": user.tg_id},
            {"$set": user.to_mongo()},
            upsert=True,
        )

        data["user"] = user
        return await handler(event, data)

