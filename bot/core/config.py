from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODELS_POOL: list[str] = [
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]


class Settings(BaseSettings):
    bot_token: str = Field(default="", description="Telegram Bot Token from @BotFather")
    gemini_api_key: str = Field(default="", description="Google Gemini API Key")
    gemini_api_keys: str | list[str] = Field(
        default_factory=list,
        description="Optional list/comma-separated Gemini API keys for rotation",
    )
    gemini_model: str = Field(default="gemini-3.7-flash", description="Primary Gemini model name")
    gemini_models_pool: str | list[str] = Field(
        default_factory=lambda: list(DEFAULT_MODELS_POOL),
        description="Fallback pool of Gemini models",
    )
    mongodb_url: str = Field(
        default="mongodb://localhost:27017",
        description="MongoDB connection string (AsyncMongoClient)",
    )
    mongodb_db_name: str = Field(
        default="english_bot",
        description="MongoDB database name",
    )
    default_timezone: str = Field(default="UTC", description="Default user timezone")
    tts_engine: str = Field(default="edge", description="TTS engine: 'edge' (Edge-TTS) or 'gemini' (Gemini Neural TTS)")
    tts_voice: str = Field(default="en-US-AriaNeural", description="edge-tts voice identifier")
    gemini_tts_voice: str = Field(default="Kore", description="Gemini TTS voice preset: Kore, Puck, Fenrir, Aoede, Charon, Enceladus")
    gemini_tts_model: str = Field(default="gemini-2.5-flash-preview-tts", description="Gemini TTS model name")
    log_level: str = Field(default="INFO", description="Logging level")
    webapp_url: str = Field(default="https://wb.qper.link", description="Base URL of the WebApp / Dashboard")
    web_host: str = Field(default="0.0.0.0", description="Web server host")
    web_port: int = Field(default=8000, description="Web server port")
    jwt_secret: str = Field(default="english_learning_bot_secret_jwt_key_2026", description="Secret key for JWT auth")
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    jwt_expire_days: int = Field(default=30, description="JWT expiration in days")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("gemini_models_pool", mode="after")
    @classmethod
    def parse_models_pool(cls, v: str | list[str] | None) -> list[str]:
        if not v:
            return list(DEFAULT_MODELS_POOL)
        if isinstance(v, str):
            models = [m.strip() for m in v.split(",") if m.strip()]
            return models if models else list(DEFAULT_MODELS_POOL)
        return list(v)

    @field_validator("gemini_api_keys", mode="after")
    @classmethod
    def parse_api_keys(cls, v: str | list[str] | None) -> list[str]:
        if not v:
            return []
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return list(v)

    @property
    def all_gemini_api_keys(self) -> list[str]:
        keys = list(self.gemini_api_keys)
        if self.gemini_api_key and self.gemini_api_key not in keys:
            keys.insert(0, self.gemini_api_key)
        return keys

    @property
    def effective_models_pool(self) -> list[str]:
        models = list(self.gemini_models_pool)
        if self.gemini_model and self.gemini_model not in models:
            models.insert(0, self.gemini_model)
        elif self.gemini_model and self.gemini_model in models:
            models.remove(self.gemini_model)
            models.insert(0, self.gemini_model)
        return models


settings = Settings()

