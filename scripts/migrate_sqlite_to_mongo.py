import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration")


def parse_datetime(dt_val: str | None) -> datetime | None:
    if not dt_val:
        return None
    try:
        dt = datetime.fromisoformat(dt_val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def migrate(
    sqlite_path: str = "english_bot.db",
    mongo_url: str = "mongodb://localhost:27017",
    db_name: str = "english_bot",
) -> None:
    if not os.path.exists(sqlite_path):
        logger.info("SQLite database %s not found. Skipping migration.", sqlite_path)
        return

    logger.info("Opening SQLite DB: %s", sqlite_path)
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    cursor = sqlite_conn.cursor()

    logger.info("Connecting to MongoDB: %s (DB: %s)", mongo_url, db_name)
    mongo_client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = mongo_client[db_name]
    users_col = db["users"]
    words_col = db["words"]

    # 1. Migrate Users
    cursor.execute("SELECT * FROM users")
    user_rows = cursor.fetchall()
    logger.info("Found %d users in SQLite.", len(user_rows))

    sqlite_user_id_to_tg_id: dict[int, int] = {}
    migrated_users = 0

    for u in user_rows:
        u_dict = dict(u)
        user_id = u_dict.get("id")
        tg_id = u_dict.get("tg_id")
        if user_id is not None and tg_id is not None:
            sqlite_user_id_to_tg_id[user_id] = tg_id

        mongo_user = {
            "tg_id": tg_id,
            "username": u_dict.get("username"),
            "first_name": u_dict.get("first_name"),
            "timezone": u_dict.get("timezone") or "UTC",
            "quiet_hours_start": u_dict.get("quiet_hours_start", 21),
            "quiet_hours_end": u_dict.get("quiet_hours_end", 10),
            "streak": u_dict.get("streak", 0),
            "last_activity_date": u_dict.get("last_activity_date"),
            "last_notified_at": parse_datetime(u_dict.get("last_notified_at")),
            "is_active": bool(u_dict.get("is_active", 1)),
            "created_at": parse_datetime(u_dict.get("created_at")) or datetime.now(timezone.utc),
            "updated_at": parse_datetime(u_dict.get("updated_at")) or datetime.now(timezone.utc),
        }
        users_col.update_one({"tg_id": tg_id}, {"$set": mongo_user}, upsert=True)
        migrated_users += 1

    logger.info("Migrated/updated %d users in MongoDB.", migrated_users)

    # 2. Migrate Words
    cursor.execute("SELECT * FROM words")
    word_rows = cursor.fetchall()
    logger.info("Found %d words in SQLite.", len(word_rows))

    migrated_words = 0
    for w in word_rows:
        w_dict = dict(w)
        old_user_id = w_dict.get("user_id")
        tg_id = sqlite_user_id_to_tg_id.get(old_user_id)
        if not tg_id:
            logger.warning("Word id=%s has unknown user_id=%s, skipping.", w_dict.get("id"), old_user_id)
            continue

        examples = []
        if w_dict.get("examples"):
            try:
                examples = json.loads(w_dict["examples"])
            except Exception:
                examples = []

        synonyms = []
        if w_dict.get("synonyms_collocations"):
            try:
                synonyms = json.loads(w_dict["synonyms_collocations"])
            except Exception:
                synonyms = []

        extra_data = {}
        if w_dict.get("extra_data"):
            try:
                extra_data = json.loads(w_dict["extra_data"])
            except Exception:
                extra_data = {}

        mongo_word = {
            "user_id": tg_id,
            "canonical_word": w_dict.get("canonical_word", ""),
            "lemma": w_dict.get("lemma", ""),
            "pos": w_dict.get("pos", ""),
            "transcription": w_dict.get("transcription", ""),
            "translation": w_dict.get("translation", ""),
            "corrected_from": w_dict.get("corrected_from"),
            "examples": examples,
            "synonyms_collocations": synonyms,
            "extra_data": extra_data,
            "repetition": w_dict.get("repetition", 0),
            "interval": w_dict.get("interval", 1),
            "ease_factor": float(w_dict.get("ease_factor", 2.5)),
            "next_review_at": parse_datetime(w_dict.get("next_review_at")) or datetime.now(timezone.utc),
            "is_archived": bool(w_dict.get("is_archived", 0)),
            "created_at": parse_datetime(w_dict.get("created_at")) or datetime.now(timezone.utc),
            "updated_at": parse_datetime(w_dict.get("updated_at")) or datetime.now(timezone.utc),
        }

        # Check existing word by user_id and canonical_word
        existing = words_col.find_one({"user_id": tg_id, "canonical_word": mongo_word["canonical_word"]})
        if existing:
            words_col.update_one({"_id": existing["_id"]}, {"$set": mongo_word})
        else:
            words_col.insert_one(mongo_word)
        migrated_words += 1

    logger.info("Migrated/updated %d words in MongoDB.", migrated_words)
    sqlite_conn.close()
    mongo_client.close()
    logger.info("Migration completed successfully!")


if __name__ == "__main__":
    candidates = [
        "data/english_bot.db",
        "/app/data/english_bot.db",
        "english_bot.db",
    ]
    if len(sys.argv) > 1:
        sqlite_path = sys.argv[1]
    elif os.getenv("SQLITE_PATH"):
        sqlite_path = os.getenv("SQLITE_PATH")
    else:
        sqlite_path = "data/english_bot.db"
        for cand in candidates:
            if os.path.exists(cand):
                sqlite_path = cand
                break

    mongo_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    db_name = os.getenv("MONGODB_DB_NAME", "english_bot")
    migrate(sqlite_path=sqlite_path, mongo_url=mongo_url, db_name=db_name)

