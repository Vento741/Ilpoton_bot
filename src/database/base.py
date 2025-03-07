# src/database/base.py

from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import MetaData, BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .imports import settings

# Создаем движок базы данных
engine = create_async_engine(
    settings.database_url,
    echo=False,  # Для отладки установите True
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)

# Создаем фабрику сессий
async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Базовый класс для всех моделей
class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s"
    })

    # Общие поля для всех моделей
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


# Функция для получения сессии БД
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Создает и возвращает асинхронную сессию БД
    """
    async with async_session() as session:
        yield session 