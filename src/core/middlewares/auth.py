from typing import Any, Awaitable, Callable, Dict

from aiogram.types import Message, TelegramObject, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from core.middlewares.base import BaseCustomMiddleware
from database.models import User
from config.settings import settings


class AuthMiddleware(BaseCustomMiddleware):
    """Middleware для аутентификации пользователей"""
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Проверяет аутентификацию пользователя и добавляет его в данные события
        :param handler: Обработчик события
        :param event: Событие
        :param data: Данные события
        :return: Результат обработки
        """
        session: AsyncSession = data["session"]
        user = await self._get_user(session, event.from_user.id)
            
        if user:
            # Проверяем и обновляем статус администратора
            is_admin = event.from_user.id in settings.admin_ids
            if user.is_admin != is_admin:
                user.is_admin = is_admin
                await session.commit()
            data["user"] = user
        else:
            # Создаем нового пользователя
            user = User(
                telegram_id=event.from_user.id,
                username=event.from_user.username,
                full_name=event.from_user.full_name,
                is_admin=event.from_user.id in settings.admin_ids  # Устанавливаем статус администратора
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            data["user"] = user

        return await handler(event, data)

    @staticmethod
    async def _get_user(session: AsyncSession, telegram_id: int) -> User | None:
        """
        Получает пользователя из базы данных
        :param session: Сессия базы данных
        :param telegram_id: Telegram ID пользователя
        :return: Объект пользователя или None
        """
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none() 