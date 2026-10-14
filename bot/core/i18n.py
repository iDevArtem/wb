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


def wrap_spoiler(text: str, hide: bool = True) -> str:
    """Wrap text in Telegram spoiler tag if hide is True."""
    return f"<tg-spoiler>{text}</tg-spoiler>" if hide else text


POS_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "noun": {
        "ru": "существительное",
        "uk": "іменник",
        "en": "noun",
        "es": "sustantivo",
        "de": "Substantiv",
        "fr": "nom",
        "it": "sostantivo",
        "pl": "rzeczownik",
    },
    "verb": {
        "ru": "глагол",
        "uk": "дієслово",
        "en": "verb",
        "es": "verbo",
        "de": "Verb",
        "fr": "verbe",
        "it": "verbo",
        "pl": "czasownik",
    },
    "phrasal verb": {
        "ru": "фразовый глагол",
        "uk": "фразове дієслово",
        "en": "phrasal verb",
        "es": "verbo compuesto",
        "de": "Phrasales Verb",
        "fr": "verbe à particule",
        "it": "verbo frasale",
        "pl": "czasownik frazowy",
    },
    "adjective": {
        "ru": "прилагательное",
        "uk": "прикметник",
        "en": "adjective",
        "es": "adjetivo",
        "de": "Adjektiv",
        "fr": "adjectif",
        "it": "aggettivo",
        "pl": "przymiotnik",
    },
    "adverb": {
        "ru": "наречие",
        "uk": "прислівник",
        "en": "adverb",
        "es": "adverbio",
        "de": "Adverb",
        "fr": "adverbe",
        "it": "avverbio",
        "pl": "przysłówek",
    },
    "pronoun": {
        "ru": "местоимение",
        "uk": "займенник",
        "en": "pronoun",
        "es": "pronombre",
        "de": "Pronomen",
        "fr": "pronom",
        "it": "pronome",
        "pl": "zaimek",
    },
    "preposition": {
        "ru": "предлог",
        "uk": "прийменник",
        "en": "preposition",
        "es": "preposición",
        "de": "Präposition",
        "fr": "préposition",
        "it": "preposizione",
        "pl": "przyimek",
    },
    "conjunction": {
        "ru": "союз",
        "uk": "сполучник",
        "en": "conjunction",
        "es": "conjunción",
        "de": "Konjunktion",
        "fr": "conjonction",
        "it": "congiunzione",
        "pl": "spójnik",
    },
    "interjection": {
        "ru": "междометие",
        "uk": "вигук",
        "en": "interjection",
        "es": "interjección",
        "de": "Interjektion",
        "fr": "interjection",
        "it": "interiezione",
        "pl": "wykrzyknik",
    },
    "numeral": {
        "ru": "числительное",
        "uk": "числівник",
        "en": "numeral",
        "es": "numeral",
        "de": "Zahlwort",
        "fr": "numéral",
        "it": "numerale",
        "pl": "liczebnik",
    },
    "particle": {
        "ru": "частица",
        "uk": "частка",
        "en": "particle",
        "es": "partícula",
        "de": "Partikel",
        "fr": "particule",
        "it": "particella",
        "pl": "partykuła",
    },
    "determiner": {
        "ru": "детерминатив",
        "uk": "детермінатив",
        "en": "determiner",
        "es": "determinante",
        "de": "Determinator",
        "fr": "déterminant",
        "it": "determinante",
        "pl": "określnik",
    },
    "article": {
        "ru": "артикль",
        "uk": "артикль",
        "en": "article",
        "es": "artículo",
        "de": "Artikel",
        "fr": "article",
        "it": "articolo",
        "pl": "rodzajnik",
    },
    "phrase": {
        "ru": "фраза",
        "uk": "фраза",
        "en": "phrase",
        "es": "frase",
        "de": "Phrase",
        "fr": "phrase",
        "it": "frase",
        "pl": "fraza",
    },
    "idiom": {
        "ru": "идиома",
        "uk": "ідіома",
        "en": "idiom",
        "es": "modismo",
        "de": "Redewendung",
        "fr": "idiome",
        "it": "idioma",
        "pl": "idiom",
    },
}


def get_pos_translation(pos: str | None, lang: str) -> str | None:
    """Return localized part of speech if standard mapping exists."""
    if not pos:
        return None
    cleaned = pos.strip().lower()
    mapping = POS_TRANSLATIONS.get(cleaned)
    if mapping:
        return mapping.get(lang) or mapping.get("ru") or mapping.get("en")
    return None

