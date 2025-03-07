from functools import wraps
from typing import Callable, Any

from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from database.models import User


def admin_only(func: Callable) -> Callable:
    """
    Декоратор для проверки прав администратора
    """
    @wraps(func)
    async def wrapper(message: Message, session: AsyncSession, *args: Any, **kwargs: Any) -> Any:
        # Проверяем, является ли пользователь администратором
        if message.from_user.id in settings.admin_ids:
            return await func(message, session, *args, **kwargs)
        
        await message.answer("У вас нет прав для выполнения этой команды.")
        return None
    
    return wrapper 