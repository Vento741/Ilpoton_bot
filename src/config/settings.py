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
    channel_id: str = "@ILPOavtoTON"  # Добавляем ID канала

    # Настройки базы данных
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ilpoton_db"
    db_user: str = "postgres"
    db_password: str = "password"  # Переименовываем в db_password вместо db_pass

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str) -> List[int]:
        if isinstance(v, str):
            # Удаляем кавычки и разбиваем по пробелам
            v = v.strip('"').strip()
            if v.startswith("[") and v.endswith("]"):
                # Если в формате списка [id1, id2, ...]
                v = v[1:-1]
                return [int(x.strip()) for x in v.split(",")]
            return [int(x) for x in v.split()]
        return v

    @property
    def database_url(self) -> str:
        """
        Получить URL для подключения к базе данных
        """
        return (
            f"postgresql+asyncpg://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')


# Создаем экземпляр настроек
settings = Settings()