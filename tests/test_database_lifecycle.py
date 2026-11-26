from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core import database


@pytest.fixture
def mocked_db(monkeypatch):
    client = MagicMock()
    db = MagicMock()
    db.command = AsyncMock()
    client.__getitem__.return_value = db
    client.close = AsyncMock()
    words, users = AsyncMock(), AsyncMock()
    monkeypatch.setattr(database, "_mongo_client", client)
    monkeypatch.setattr(database, "_initialized_client", None)
    monkeypatch.setattr(database, "get_words_collection", lambda: words)
    monkeypatch.setattr(database, "get_users_collection", lambda: users)
    return client, db, words, users


@pytest.mark.asyncio
async def test_init_db_is_idempotent(mocked_db):
    client, db, words, users = mocked_db

    assert await database.init_db() is True
    assert await database.init_db() is False

    assert db.command.await_count == 1
    assert words.update_many.await_count == 2
    assert users.update_many.await_count == 2


@pytest.mark.asyncio
async def test_close_db_resets_initialization(mocked_db):
    client, db, words, users = mocked_db
    await database.init_db()
    await database.close_db()
    assert database._initialized_client is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("mongodb://root:s3cr3t@mongo:27017/db?authSource=admin", "mongodb://root:***@mongo:27017/db?authSource=admin"),
        ("mongodb+srv://u:p%40ss@cluster.example.net/db", "mongodb+srv://u:***@cluster.example.net/db"),
        ("mongodb://localhost:27017", "mongodb://localhost:27017"),
    ],
)
def test_mask_mongodb_url(url, expected):
    assert database.mask_mongodb_url(url) == expected


@pytest.mark.asyncio
async def test_webapp_lifespan_does_not_close_db_it_did_not_open(monkeypatch):
    from bot.web import app as web_app_module

    init = AsyncMock(return_value=False)
    close = AsyncMock()
    monkeypatch.setattr(web_app_module, "init_db", init)
    monkeypatch.setattr(web_app_module, "close_db", close)

    async with web_app_module.lifespan(web_app_module.app):
        pass

    init.assert_awaited_once()
    close.assert_not_called()


@pytest.mark.asyncio
async def test_webapp_lifespan_closes_db_it_opened(monkeypatch):
    from bot.web import app as web_app_module

    monkeypatch.setattr(web_app_module, "init_db", AsyncMock(return_value=True))
    close = AsyncMock()
    monkeypatch.setattr(web_app_module, "close_db", close)

    async with web_app_module.lifespan(web_app_module.app):
        pass

    close.assert_awaited_once()
