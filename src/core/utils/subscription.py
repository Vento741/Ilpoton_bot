"""
Модуль для проверки подписки пользователя на канал
"""

from aiogram import Bot
from loguru import logger
from typing import Union
import traceback
from aiogram.enums.chat_member_status import ChatMemberStatus

# ID канала для проверки подписки
CHANNEL_ID = "@ILPOavtoTON"  # Замените на ваш канал

async def is_subscribed(user_id: int, bot: Bot) -> bool:
    """
    Проверяет, подписан ли пользователь на канал
    
    Args:
        user_id: Telegram ID пользователя
        bot: Экземпляр бота
        
    Returns:
        bool: True, если пользователь подписан на канал
    """
    try:
        logger.info(f"Проверка подписки пользователя {user_id} на канал {CHANNEL_ID}")
        
        # Получаем информацию о подписке пользователя на канал
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        
        logger.info(f"Статус подписки пользователя {user_id}: {member.status}")
        
        # Проверяем статус подписки (используем правильные константы из aiogram3)
        result = member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
        logger.info(f"Результат проверки подписки для пользователя {user_id}: {result}")
        
        return result
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки пользователя {user_id}: {e}")
        logger.error(traceback.format_exc())
        # В случае ошибки считаем, что пользователь не подписан
        return False
        
async def get_channel_info(bot: Bot) -> Union[str, None]:
    """
    Получает информацию о канале
    
    Args:
        bot: Экземпляр бота
        
    Returns:
        str: Название канала или None в случае ошибки
    """
    try:
        chat = await bot.get_chat(chat_id=CHANNEL_ID)
        return chat.title
    except Exception as e:
        logger.error(f"Ошибка при получении информации о канале: {e}")
        return None 