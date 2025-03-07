from typing import List
from urllib.parse import quote_plus

from pydantic import SecretStr, field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Класс настроек проекта
    """
    # Настройки бота
    bot_token: SecretStr
    admin_ids: list[int] = Field(default_factory=list)

    # Настройки базы данных
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ilpoton_db"
    db_user: str = "postgres"
    db_pass: str = "4090345m"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str) -> List[int]:
        if isinstance(v, str):
            # Удаляем кавычки и разбиваем по пробелам
            v = v.strip('"').strip()
            return [int(x) for x in v.split()]
        return v

    @property
    def database_url(self) -> str:
        """
        Получить URL для подключения к базе данных
        """
        return (
            f"postgresql+asyncpg://{quote_plus(self.db_user)}:{quote_plus(self.db_pass)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')


# Создаем экземпляр настроек
settings = Settings()