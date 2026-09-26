import asyncio
from bot.services.gemini_service import gemini_service
from bot.core.config import settings

async def main():
    try:
        res = await gemini_service.analyze_text("house", native_lang="en", target_lang="de")
        print(res)
    except Exception as e:
        print("ERROR:", repr(e))

asyncio.run(main())
