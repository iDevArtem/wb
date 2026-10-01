# Правила проекта (English Bot)

Этот файл содержит основные архитектурные правила и договоренности для разработки этого Telegram бота. ИИ-ассистенты должны учитывать эти правила при написании кода.

## Технический стек и особенности API
- **Библиотека**: Проект использует `aiogram` свежей версии (с поддержкой Telegram Bot API 10.1+).
- **База данных**: MongoDB (через `pymongo`). 
- **Асинхронность**: Проект полностью асинхронный (`asyncio`).

## Работа с медиа и сообщениями (Rich Messages)
- **ВАЖНО**: Telegram Bot API 10.1+ поддерживает `Rich Messages`. В этом проекте мы активно это используем для создания красивых карточек слов и квизов с аудио.
- **Никогда** не отправляйте аудио (произношение) отдельным сообщением (`answer_voice`), если оно должно быть частью карточки.
- **Всегда** используйте `InputRichMessage` с медиа-вложениями (`InputRichMessageMedia` и `InputMediaAudio`), а в `html` разметку вставляйте `<audio src="tg://audio?id=..."></audio>`.
- Для отправки используйте `bot.send_rich_message(...)` (если карточки еще нет) или `bot.edit_message_text(..., rich_message=...)` (для обновления существующего сообщения).
Пример:
```python
from aiogram.types import InputRichMessage, InputRichMessageMedia, InputMediaAudio

media = InputRichMessageMedia(
    id="audio1",
    media=InputMediaAudio(media=voice_file, title="Слово")
)
rich_msg = InputRichMessage(
    html=f"Текст карточки\n\n<audio src=\"tg://audio?id=audio1\"></audio>\n\nВведи ответ:",
    media=[media]
)
# Затем отправка или редактирование...
```

## Структура проекта
- `bot/handlers/word_input.py`: Обработка ввода новых слов (текст, голос), их анализ через нейросети и сохранение.
- `bot/handlers/quiz_fsm.py`: Вся логика интервального повторения (квизов), различные режимы (Spelling, Multiple Choice, Listening).
- `bot/handlers/settings.py`: Настройки пользователя (языки, часовой пояс, тихие часы).
- `bot/keyboards/`: Inline-клавиатуры для бота.
