from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Crypto Perpetual Futures Arbitrage Scanner"
    config_path: Path = Path("config/config.example.yaml")
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    # TODO: Load .env and config.yaml values when settings persistence is added.
    return Settings()
