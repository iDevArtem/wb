import asyncio
from bot.core.database import get_database, get_words_collection

async def test():
    words_col = get_words_collection()
    cursor = await words_col.aggregate([{"$limit": 1}])
    print("cursor", type(cursor))
    res = await cursor.to_list()
    print("res", res)

asyncio.run(test())
