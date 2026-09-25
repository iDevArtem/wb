from datetime import date, datetime, timezone
from bson import ObjectId
from bot.models.base import MongoBaseModel, PyObjectId, utc_now
from bot.models.user import User
from bot.models.word import Word, default_next_review
from bot.handlers.word_input import _word_query_by_id


def test_user_model():
    user = User(
        tg_id=12345678,
        username="john_doe",
        first_name="John",
        timezone="Europe/Kyiv",
        last_activity_date=date(2026, 9, 15),
    )
    assert user.id == 12345678
    assert user.tg_id == 12345678
    assert user.username == "john_doe"

    mongo_doc = user.to_mongo()
    assert mongo_doc["tg_id"] == 12345678
    assert mongo_doc["last_activity_date"] == "2026-09-15"
    assert "_id" not in mongo_doc  # Newly created, no id set yet


def test_user_from_mongo():
    oid = ObjectId()
    doc = {
        "_id": oid,
        "tg_id": 987654321,
        "username": "alice",
        "timezone": "UTC",
        "streak": 5,
        "last_activity_date": "2026-09-15",
    }
    user = User.model_validate(doc)
    assert user.id == 987654321
    assert user.mongo_id == str(oid)
    assert user.last_activity_date == date(2026, 9, 15)
    assert user.streak == 5


def test_word_model():
    word = Word(
        user_id=12345678,
        canonical_word="inspire",
        lemma="inspire",
        pos="verb",
        transcription="/ɪnˈspaɪər/",
        translation="вдохновлять",
    )
    assert word.user_id == 12345678
    assert word.canonical_word == "inspire"
    assert word.interval == 1
    assert word.repetition == 0
    assert word.ease_factor == 2.5
    assert not word.is_archived

    mongo_doc = word.to_mongo()
    assert mongo_doc["user_id"] == 12345678
    assert "_id" not in mongo_doc


def test_word_from_mongo():
    oid = ObjectId()
    doc = {
        "_id": oid,
        "user_id": 12345678,
        "canonical_word": "inspire",
        "lemma": "inspire",
        "pos": "verb",
        "transcription": "/ɪnˈspaɪər/",
        "translation": "вдохновлять",
        "examples": [{"en": "She inspires me.", "ru": "Она вдохновляет меня."}],
        "repetition": 2,
        "interval": 6,
    }
    word = Word.model_validate(doc)
    assert word.id == str(oid)
    assert len(word.examples) == 1
    assert word.examples[0]["en"] == "She inspires me."
    assert word.interval == 6


def test_word_query_by_id():
    user = User(tg_id=12345, native_language="ru", target_language="en")
    oid = ObjectId()
    q1 = _word_query_by_id(str(oid), user)
    assert q1["user_id"] == 12345
    assert q1["target_language"] == "en"
    assert q1["native_language"] == "ru"
    assert q1["_id"] == oid

    q2 = _word_query_by_id("non_object_id_string", user)
    assert q2["user_id"] == 12345
    assert q2["target_language"] == "en"
    assert q2["native_language"] == "ru"
    assert q2["_id"] == "non_object_id_string"
