import logging
from datetime import datetime, timezone
from typing import Any, Literal
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from bot.core.config import settings
from bot.core.database import get_database, get_users_collection, get_words_collection
from bot.models.user import User
from bot.models.word import Word
from bot.web.auth import create_access_token, get_current_user, validate_telegram_init_data

logger = logging.getLogger("bot.web.routes")

router = APIRouter(prefix="/api", tags=["API"])


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(..., description="Raw Telegram.WebApp.initData string")


class AuthResponse(BaseModel):
    token: str
    user: dict[str, Any]


class StatsResponse(BaseModel):
    total_words: int
    due_words: int
    learning_words: int
    mastered_words: int
    streak: int
    interval_distribution: dict[str, int]


class WordListResponse(BaseModel):
    total: int
    words: list[dict[str, Any]]


@router.post("/auth/telegram", response_model=AuthResponse)
async def auth_telegram(req: TelegramAuthRequest) -> AuthResponse:
    """
    Authenticates user via Telegram WebApp initData HMAC-SHA256 signature.
    Upserts user profile in database and returns JWT token.
    """
    user_info = validate_telegram_init_data(req.init_data)
    tg_id = user_info.get("id")
    if not tg_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user id in initData",
        )

    db = get_database()
    now = datetime.now(timezone.utc)

    # Upsert user in database
    existing_user = await db.users.find_one({"tg_id": tg_id})
    if not existing_user:
        user_doc = {
            "tg_id": tg_id,
            "username": user_info.get("username"),
            "first_name": user_info.get("first_name", "User"),
            "timezone": settings.default_timezone,
            "quiet_hours_start": 21,
            "quiet_hours_end": 10,
            "streak": 0,
            "last_activity_date": None,
            "last_notified_at": None,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        await db.users.insert_one(user_doc)
        user_obj = User(**user_doc)
    else:
        # Update first_name/username if changed
        update_fields = {"updated_at": now}
        if user_info.get("username") and user_info.get("username") != existing_user.get("username"):
            update_fields["username"] = user_info.get("username")
        if user_info.get("first_name") and user_info.get("first_name") != existing_user.get("first_name"):
            update_fields["first_name"] = user_info.get("first_name")

        await db.users.update_one({"tg_id": tg_id}, {"$set": update_fields})
        existing_user.update(update_fields)
        user_obj = User(**existing_user)

    token = create_access_token(tg_id=tg_id, username=user_obj.username)
    return AuthResponse(
        token=token,
        user={
            "id": user_obj.id,
            "tg_id": user_obj.tg_id,
            "username": user_obj.username,
            "first_name": user_obj.first_name,
            "streak": user_obj.streak,
            "timezone": user_obj.timezone,
            "native_language": user_obj.native_language,
            "target_language": user_obj.target_language,
        },
    )


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Returns current user's profile."""
    return {
        "id": current_user.id,
        "tg_id": current_user.tg_id,
        "username": current_user.username,
        "first_name": current_user.first_name,
        "streak": current_user.streak,
        "timezone": current_user.timezone,
        "quiet_hours_start": current_user.quiet_hours_start,
        "quiet_hours_end": current_user.quiet_hours_end,
        "native_language": current_user.native_language,
        "target_language": current_user.target_language,
    }


@router.get("/stats", response_model=StatsResponse)
async def get_stats(current_user: User = Depends(get_current_user)) -> StatsResponse:
    """Returns word and learning statistics for the current user."""
    words_col = get_words_collection()
    user_id = current_user.id
    now = datetime.now(timezone.utc)

    lang_filter = {
        "native_language": current_user.native_language,
        "target_language": current_user.target_language,
    }
    
    total_words = await words_col.count_documents({"user_id": user_id, "is_pending": {"$ne": True}, **lang_filter})
    learning_words = await words_col.count_documents({"user_id": user_id, "is_archived": False, "is_pending": {"$ne": True}, **lang_filter})
    mastered_words = await words_col.count_documents({"user_id": user_id, "is_archived": True, "is_pending": {"$ne": True}, **lang_filter})
    due_words = await words_col.count_documents({
        "user_id": user_id,
        "is_archived": False,
        "is_pending": {"$ne": True},
        "next_review_at": {"$lte": now},
        **lang_filter,
    })

    return StatsResponse(
        total_words=total_words,
        due_words=due_words,
        learning_words=learning_words,
        mastered_words=mastered_words,
        streak=current_user.streak,
        interval_distribution={},
    )


@router.get("/words", response_model=WordListResponse)
async def get_words(
    q: str = Query("", description="Search substring in word or translation"),
    filter: Literal["all", "due", "learning", "mastered", "archived"] = Query(
        "all", description="Filter preset"
    ),
    pos: str = Query("", description="Filter by part of speech (noun, verb, etc.)"),
    sort: Literal["next_review", "alpha", "created_at", "interval", "repetition"] = Query(
        "next_review", description="Sort order"
    ),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> WordListResponse:
    """Returns a filtered, searched, and sorted list of words for current user."""
    db = get_database()
    user_id = current_user.id
    now = datetime.now(timezone.utc)

    query_filter: dict[str, Any] = {
        "user_id": user_id,
        "native_language": current_user.native_language,
        "target_language": current_user.target_language,
        "is_pending": {"$ne": True},
    }

    if filter == "archived":
        query_filter["is_archived"] = True
    else:
        query_filter["is_archived"] = False

        if filter == "due":
            query_filter["next_review_at"] = {"$lte": now}
        elif filter == "learning":
            query_filter["repetition"] = {"$lt": 3}
        elif filter == "mastered":
            query_filter["repetition"] = {"$gte": 3}

    if pos:
        query_filter["pos"] = {"$regex": f"^{pos}", "$options": "i"}

    if q.strip():
        search_regex = {"$regex": q.strip(), "$options": "i"}
        query_filter["$or"] = [
            {"canonical_word": search_regex},
            {"translation": search_regex},
            {"transcription": search_regex},
        ]

    # Sorting
    sort_criteria: list[tuple[str, int]] = []
    if sort == "next_review":
        sort_criteria = [("next_review_at", 1)]
    elif sort == "alpha":
        sort_criteria = [("canonical_word", 1)]
    elif sort == "created_at":
        sort_criteria = [("created_at", -1)]
    elif sort == "interval":
        sort_criteria = [("interval", -1)]
    elif sort == "repetition":
        sort_criteria = [("repetition", -1)]

    total_count = await db.words.count_documents(query_filter)
    cursor = db.words.find(query_filter).sort(sort_criteria).skip(offset).limit(limit)

    words_docs = await cursor.to_list(length=limit)

    serialized_words: list[dict[str, Any]] = []
    for doc in words_docs:
        doc_id = str(doc.get("_id"))
        serialized_words.append(
            {
                "id": doc_id,
                "canonical_word": doc.get("canonical_word", ""),
                "lemma": doc.get("lemma", ""),
                "pos": doc.get("pos", ""),
                "transcription": doc.get("transcription", ""),
                "translation": doc.get("translation", ""),
                "corrected_from": doc.get("corrected_from"),
                "examples": doc.get("examples", []),
                "synonyms_collocations": doc.get("synonyms_collocations", []),
                "extra_data": doc.get("extra_data", {}),
                "repetition": doc.get("repetition", 0),
                "interval": doc.get("interval", 1),
                "ease_factor": doc.get("ease_factor", 2.5),
                "next_review_at": (
                    doc["next_review_at"].isoformat()
                    if isinstance(doc.get("next_review_at"), datetime)
                    else str(doc.get("next_review_at") or "")
                ),
                "is_archived": doc.get("is_archived", False),
                "created_at": (
                    doc["created_at"].isoformat()
                    if isinstance(doc.get("created_at"), datetime)
                    else str(doc.get("created_at") or "")
                ),
            }
        )

    return WordListResponse(total=total_count, words=serialized_words)


@router.get("/words/{word_id}")
async def get_word_detail(
    word_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Returns full details of a specific word."""
    db = get_database()
    try:
        obj_id = ObjectId(word_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid word ID format")

    doc = await db.words.find_one({"_id": obj_id, "user_id": current_user.id})
    if not doc:
        raise HTTPException(status_code=404, detail="Word not found")

    return {
        "id": str(doc["_id"]),
        "canonical_word": doc.get("canonical_word", ""),
        "lemma": doc.get("lemma", ""),
        "pos": doc.get("pos", ""),
        "transcription": doc.get("transcription", ""),
        "translation": doc.get("translation", ""),
        "corrected_from": doc.get("corrected_from"),
        "examples": doc.get("examples", []),
        "synonyms_collocations": doc.get("synonyms_collocations", []),
        "extra_data": doc.get("extra_data", {}),
        "repetition": doc.get("repetition", 0),
        "interval": doc.get("interval", 1),
        "ease_factor": doc.get("ease_factor", 2.5),
        "next_review_at": (
            doc["next_review_at"].isoformat()
            if isinstance(doc.get("next_review_at"), datetime)
            else str(doc.get("next_review_at") or "")
        ),
        "is_archived": doc.get("is_archived", False),
        "created_at": (
            doc["created_at"].isoformat()
            if isinstance(doc.get("created_at"), datetime)
            else str(doc.get("created_at") or "")
        ),
    }


@router.get("/tts/{word}")
async def get_word_tts(word: str) -> Response:
    """Generates and streams high quality MP3 pronunciation audio using Microsoft Edge TTS."""
    clean_word = word.strip()
    if not clean_word or len(clean_word) > 100:
        raise HTTPException(status_code=400, detail="Word length invalid")

    try:
        import edge_tts

        communicate = edge_tts.Communicate(clean_word, settings.tts_voice)
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        audio_bytes = b"".join(audio_chunks)
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Content-Disposition": f'inline; filename="{clean_word}.mp3"',
            },
        )
    except Exception as exc:
        logger.error("TTS generation failed for '%s': %s", clean_word, exc)
        raise HTTPException(status_code=500, detail="TTS generation failed")
