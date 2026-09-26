import json
import logging
from pathlib import Path
from aiogram.filters import Filter
from aiogram.types import Message
from typing import Any, Dict

logger = logging.getLogger(__name__)

class Translator:
    def __init__(self, locales_dir: str):
        self.locales: Dict[str, Dict[str, str]] = {}
        path = Path(locales_dir)
        if path.exists():
            for file in path.glob("*.json"):
                lang = file.stem
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        self.locales[lang] = json.load(f)
                except Exception as e:
                    logger.error(f"Failed to load locale {file}: {e}")

    def get(self, lang: str, text: str) -> str:
        # Default behavior: Try target lang -> fallback to english -> fallback to raw text (Russian)
        if lang in self.locales and text in self.locales[lang]:
            return self.locales[lang][text]
        if "en" in self.locales and text in self.locales["en"]:
            return self.locales["en"][text]
        return text

translator = Translator("bot/locales")

def t(lang: str, text: str) -> str:
    return translator.get(lang, text)

class TranslatedText(Filter):
    def __init__(self, text: str):
        self.text = text
        
    async def __call__(self, message: Message, user: Any) -> bool:
        # Check against user's current language first
        if message.text == t(user.native_language, self.text):
            return True
        # Check against all other languages in case they pressed an old button
        for lang, translations in translator.locales.items():
            if message.text == translations.get(self.text):
                return True
        # Fallback check against the raw key
        return message.text == self.text
