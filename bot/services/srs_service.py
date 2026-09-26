from bot.core.i18n import t
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
    def normalize_text(text: str) -> str:
        """
        Normalize input text by:
        - Converting to lowercase
        - Stripping leading and trailing whitespace
        - Stripping common punctuation marks
        - Removing leading grammatical articles ('a', 'an', 'the')
        - Removing leading infinitive particle 'to' for verbs
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
        for article in ("a ", "an ", "the "):
            if cleaned.startswith(article):
                cleaned = cleaned[len(article):].strip()
                break

        # Strip leading infinitive particle 'to '
        if cleaned.startswith("to "):
            cleaned = cleaned[3:].strip()

        return cleaned

    @classmethod
    def is_answer_correct(
        cls,
        user_input: str,
        canonical_word: str,
        lemma: str,
        translation: str | None = None,
        allow_translation: bool = False,
    ) -> bool:
        """
        Check if user's answer matches canonical word, lemma, or translation.
        """
        norm_user = cls.normalize_text(user_input)
        if not norm_user:
            return False

        norm_canonical = cls.normalize_text(canonical_word)
        norm_lemma = cls.normalize_text(lemma)

        if norm_user == norm_canonical or norm_user == norm_lemma:
            return True

        if allow_translation and translation:
            # Check against comma-separated translations
            translations = [cls.normalize_text(t) for t in re.split(r"[,;/]", translation)]
            if norm_user in translations or cls.normalize_text(translation) == norm_user:
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
            en_text = example.get("en", "")
            if pattern.search(en_text):
                masked_en = pattern.sub(blank, en_text)
                ru_text = example.get("ru", "")
                if ru_text:
                    return f"«{masked_en}»\n<i>({ru_text})</i>"
                return f"«{masked_en}»"

        # Fallback if no matching example contains the exact word boundary
        if examples and examples[0].get("en"):
            first_ex = examples[0]["en"]
            first_ru = examples[0].get("ru", "")
            # Sub string case-insensitively
            masked_en = re.sub(
                re.escape(canonical_word),
                blank,
                first_ex,
                flags=re.IGNORECASE,
            )
            if ru_text := first_ru:
                return f"«{masked_en}»\n<i>({ru_text})</i>"
            return f"«{masked_en}»"

        return f"{t(lang, 'Контекст:')} <i>{canonical_word[0]}... ({lemma})</i>"
