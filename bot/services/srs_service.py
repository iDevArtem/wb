from bot.core.i18n import t, wrap_spoiler
import re
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class SRSResult:
    repetition: int
    interval: int
    ease_factor: float
    next_review_at: datetime


LANGUAGE_ARTICLES: dict[str, tuple[str, ...]] = {
    "en": ("a ", "an ", "the "),
    "de": ("der ", "die ", "das ", "ein ", "eine ", "einen ", "einem ", "einer ", "eines "),
    "es": ("el ", "la ", "los ", "las ", "un ", "una ", "unos ", "unas "),
    "fr": ("le ", "la ", "les ", "un ", "une ", "des ", "l'", "d'"),
    "it": ("il ", "lo ", "la ", "i ", "gli ", "le ", "un ", "uno ", "una ", "un'", "l'"),
    "pt": ("o ", "a ", "os ", "as ", "um ", "uma ", "uns ", "umas "),
}

LANGUAGE_INFINITIVES: dict[str, tuple[str, ...]] = {
    "en": ("to ",),
    "de": ("zu ",),
}


class SRSService:
    @staticmethod
    def calculate_sm2(
        repetition: int,
        interval: int,
        ease_factor: float,
        is_success: bool,
        now: datetime | None = None,
    ) -> SRSResult:
        """
        Calculate next review parameters based on the SuperMemo-2 (SM-2) algorithm.

        Upon success:
          repetition += 1
          interval = 1 (step 1), interval = 6 (step 2), interval = round(interval * ease_factor) (step 3+)
          ease_factor remains or adjusts (minimum 1.3)

        Upon failure:
          repetition = 0
          interval = 1
          ease_factor = max(1.3, ease_factor - 0.2)
        """
        current_time = now if now is not None else datetime.now(timezone.utc)

        if is_success:
            new_repetition = repetition + 1
            if new_repetition == 1:
                new_interval = 1
            elif new_repetition == 2:
                new_interval = 6
            else:
                new_interval = max(1, round(interval * ease_factor))
            new_ease_factor = max(1.3, ease_factor)
        else:
            new_repetition = 0
            new_interval = 1
            new_ease_factor = max(1.3, round(ease_factor - 0.2, 4))

        next_review_at = current_time + timedelta(days=new_interval)

        return SRSResult(
            repetition=new_repetition,
            interval=new_interval,
            ease_factor=new_ease_factor,
            next_review_at=next_review_at,
        )

    @staticmethod
    def normalize_text(text: str, target_lang: str | None = None) -> str:
        """
        Normalize input text by:
        - Converting to lowercase
        - Stripping leading and trailing whitespace
        - Stripping common punctuation marks
        - Removing leading grammatical articles according to target language
        - Removing leading infinitive particles (e.g. 'to ' in English, 'zu ' in German)
        - Collapsing extra internal spaces
        """
        if not text:
            return ""

        # Lowercase and strip
        cleaned = text.strip().lower()

        # Remove surrounding punctuation
        cleaned = re.sub(r"^[\s\"'«»“”„.,!?;:()\[\]{}]+|[\s\"'«»“”„.,!?;:()\[\]{}]+$", "", cleaned)

        # Remove internal punctuation except apostrophes and hyphens
        # but replace characters like dots, commas, exclamation marks with spaces
        cleaned = re.sub(r"[,!?;:()\[\]{}]", " ", cleaned)

        # Collapse whitespace
        cleaned = " ".join(cleaned.split())

        # Strip leading articles
        lang_key = target_lang.lower().split("-")[0] if target_lang else "en"
        articles = LANGUAGE_ARTICLES.get(lang_key, LANGUAGE_ARTICLES["en"])
        for article in articles:
            if cleaned.startswith(article):
                cleaned = cleaned[len(article):].strip()
                break

        # Strip leading infinitive particle
        infinitives = LANGUAGE_INFINITIVES.get(lang_key, LANGUAGE_INFINITIVES.get("en", ()))
        for inf in infinitives:
            if cleaned.startswith(inf):
                cleaned = cleaned[len(inf):].strip()
                break

        return cleaned

    @classmethod
    def is_answer_correct(
        cls,
        user_input: str,
        canonical_word: str,
        lemma: str,
        translation: str | None = None,
        allow_translation: bool = False,
        only_translation: bool = False,
        target_lang: str | None = None,
        native_lang: str | None = None,
    ) -> bool:
        """
        Check if user's answer matches canonical word, lemma, or translation.
        If only_translation=True, only matches against native translation.
        """
        norm_user_target = cls.normalize_text(user_input, target_lang=target_lang)
        if not norm_user_target:
            return False

        if not only_translation:
            norm_canonical = cls.normalize_text(canonical_word, target_lang=target_lang)
            norm_lemma = cls.normalize_text(lemma, target_lang=target_lang)

            if norm_user_target == norm_canonical or norm_user_target == norm_lemma:
                return True

        if (allow_translation or only_translation) and translation:
            norm_user_native = cls.normalize_text(user_input, target_lang=native_lang)
            # Check against comma-separated translations
            translations = [cls.normalize_text(t, target_lang=native_lang) for t in re.split(r"[,;/]", translation)]
            if norm_user_native in translations or cls.normalize_text(translation, target_lang=native_lang) == norm_user_native:
                return True

        return False

    @classmethod
    def get_attempt_1_hint(cls, word: str, lang: str = "en") -> str:
        """
        Hint 1: First letter and blanks (e.g., 'h _ _ _ o [5 letters]').
        For multi-word expressions, format each word.
        """
        words = word.strip().split()
        hint_parts = []
        total_letters = sum(len(w) for w in words)

        for w in words:
            if len(w) <= 1:
                hint_parts.append(w)
            elif len(w) == 2:
                hint_parts.append(f"{w[0]} _")
            else:
                # Show first and last letter with underscores in between
                middle_blanks = " ".join(["_"] * (len(w) - 2))
                hint_parts.append(f"{w[0]} {middle_blanks} {w[-1]}")

        masked_str = "   ".join(hint_parts)
        return f"<code>{masked_str}</code> [{total_letters} {t(lang, 'букв')}]"

    @classmethod
    def get_attempt_2_hint(
        cls,
        canonical_word: str,
        lemma: str,
        examples: list[dict[str, str]],
        lang: str = "en",
        hide_translations: bool = True,
    ) -> str:
        """
        Hint 2: Example sentence with the target word replaced by '___'.
        """
        blank = "<b>___</b>"
        pattern = re.compile(
            rf"\b({re.escape(canonical_word)}|{re.escape(lemma)})\b",
            re.IGNORECASE,
        )

        for example in examples:
            target_text = example.get("target") or example.get("en", "")
            if pattern.search(target_text):
                masked_target = pattern.sub(blank, target_text)
                native_text = example.get("native") or example.get("ru", "")
                if native_text:
                    wrapped_native = wrap_spoiler(native_text, hide_translations)
                    return f"«{masked_target}»\n<i>({wrapped_native})</i>"
                return f"«{masked_target}»"

        # Fallback if no matching example contains the exact word boundary
        if examples:
            first_target = examples[0].get("target") or examples[0].get("en", "")
            if first_target:
                first_native = examples[0].get("native") or examples[0].get("ru", "")
                # Sub string case-insensitively
                masked_target = re.sub(
                    re.escape(canonical_word),
                    blank,
                    first_target,
                    flags=re.IGNORECASE,
                )
                if first_native:
                    wrapped_native = wrap_spoiler(first_native, hide_translations)
                    return f"«{masked_target}»\n<i>({wrapped_native})</i>"
                return f"«{masked_target}»"

        return f"{t(lang, 'Контекст:')} <i>{canonical_word[0]}... ({lemma})</i>"

    @classmethod
    def get_listening_attempt_2_hint(
        cls,
        canonical_word: str,
        translation: str,
        examples: list[dict[str, str]],
        lang: str = "ru",
        hide_translations: bool = True,
    ) -> str:
        """
        Hint 2 for listening mode:
        Shows the target language context sentence (with the spoken word in bold)
        and masks the native translation in the native sentence with '___'.
        """
        primary_translation = re.split(r"[,;/]", translation)[0].strip()
        blank = "<b>___</b>"

        for example in examples:
            target_text = example.get("target") or example.get("en", "")
            native_text = example.get("native") or example.get("ru", "")
            if target_text and native_text and primary_translation.lower() in native_text.lower():
                highlighted_target = re.sub(
                    rf"\b({re.escape(canonical_word)})\b",
                    r"<b>\1</b>",
                    target_text,
                    flags=re.IGNORECASE,
                )
                masked_native = re.sub(
                    re.escape(primary_translation),
                    blank,
                    native_text,
                    flags=re.IGNORECASE,
                )
                wrapped_native = wrap_spoiler(masked_native, hide_translations)
                return f"«{highlighted_target}»\n<i>({wrapped_native})</i>"

        if examples:
            first_target = examples[0].get("target") or examples[0].get("en", "")
            if first_target:
                highlighted_target = re.sub(
                    rf"\b({re.escape(canonical_word)})\b",
                    r"<b>\1</b>",
                    first_target,
                    flags=re.IGNORECASE,
                )
                return f"«{highlighted_target}»"

        masked_transl = cls.get_attempt_1_hint(primary_translation, lang)
        return f"{t(lang, 'Контекст:')} {masked_transl}"

