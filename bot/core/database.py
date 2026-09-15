import logging
from pymongo import ASCENDING, AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from bot.core.config import settings

logger = logging.getLogger(__name__)

_mongo_client: AsyncMongoClient | None = None


def get_mongo_client() -> AsyncMongoClient:
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = AsyncMongoClient(
            settings.mongodb_url,
            serverSelectionTimeoutMS=5000,
        )
    return _mongo_client


def get_db() -> AsyncDatabase:
    client = get_mongo_client()
    return client[settings.mongodb_db_name]


# Alias for compatibility
get_database = get_db



def get_users_collection() -> AsyncCollection:
    return get_db()["users"]


def get_words_collection() -> AsyncCollection:
    return get_db()["words"]


async def init_db() -> None:
    """Initialize MongoDB connection and create required indexes."""
    client = get_mongo_client()
    logger.info("Connecting to MongoDB at %s...", settings.mongodb_url)
    try:
        await client.admin.command("ping")
        logger.info("Connected to MongoDB successfully.")
    except Exception as e:
        logger.error("Failed to ping MongoDB: %s", e)
        raise

    users_col = get_users_collection()
    words_col = get_words_collection()

    # Create indexes on users collection
    await users_col.create_index([("tg_id", ASCENDING)], unique=True)

    # Create indexes on words collection
    await words_col.create_index([("user_id", ASCENDING), ("is_archived", ASCENDING)])
    await words_col.create_index([("user_id", ASCENDING), ("next_review_at", ASCENDING)])
    await words_col.create_index([("user_id", ASCENDING), ("canonical_word", ASCENDING)])
    await words_col.create_index([("user_id", ASCENDING), ("lemma", ASCENDING)])

    logger.info("MongoDB indexes verified and ready.")


async def close_db() -> None:
    """Close MongoDB connection."""
    global _mongo_client
    if _mongo_client is not None:
        logger.info("Closing MongoDB connection...")
        await _mongo_client.close()
        _mongo_client = None
        logger.info("MongoDB connection closed.")

