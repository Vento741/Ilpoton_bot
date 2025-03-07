"""
Модуль для работы с реферальной системой
Предоставляет функции для генерации и обработки реферальных ссылок
"""

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from typing import Optional, Tuple
from loguru import logger
from aiogram.enums.parse_mode import ParseMode

from database.models import User

async def generate_referral_link(user_id: int, bot: Bot) -> str:
    """
    Генерирует реферальную ссылку для пользователя
    
    Args:
        user_id: Telegram ID пользователя
        bot: Экземпляр бота
        
    Returns:
        str: Реферальная ссылка
    """
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    return f"https://t.me/{bot_username}?start=ref_{user_id}"

async def process_referral(
    user_id: int, 
    referrer_telegram_id: Optional[int], 
    session: AsyncSession,
    bot: Optional[Bot] = None
) -> Tuple[bool, Optional[int]]:
    """
    Обрабатывает реферальную связь между пользователями
    
    Args:
        user_id: Telegram ID нового пользователя
        referrer_telegram_id: Telegram ID пригласившего пользователя
        session: Сессия базы данных
        bot: Экземпляр бота для отправки уведомлений
        
    Returns:
        Tuple[bool, Optional[int]]: Успешность обработки и ID пригласившего в БД
    """
    if not referrer_telegram_id or user_id == referrer_telegram_id:
        return False, None
    
    try:
        # Находим пользователя-реферера в БД
        result = await session.execute(
            select(User).where(User.telegram_id == referrer_telegram_id)
        )
        referrer = result.scalar_one_or_none()
        
        if not referrer:
            logger.warning(f"Реферер {referrer_telegram_id} не найден в базе")
            return False, None
        
        # Проверяем, не установлен ли уже реферер у пользователя
        user_result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            logger.warning(f"Пользователь {user_id} не найден в базе")
            return False, None
            
        if user.referrer_id:
            logger.info(f"Пользователь {user_id} уже имеет реферера {user.referrer_id}")
            return False, None
        
        # Сохраняем ID для проверки
        referrer_id = referrer.id
        
        # Устанавливаем связь и увеличиваем счетчик приглашенных
        # Используем прямой SQL-запрос для обновления данных
        try:
            # Устанавливаем реферера для пользователя
            await session.execute(
                update(User)
                .where(User.telegram_id == user_id)
                .values(referrer_id=referrer_id)
            )
            
            # Увеличиваем счетчик приглашенных и добавляем 2 попытки для реферера
            await session.execute(
                update(User)
                .where(User.id == referrer_id)
                .values(
                    invited_count=User.invited_count + 1,
                    attempts=User.attempts + 2
                )
            )
            
            # Сохраняем изменения
            await session.commit()
            
            # Получаем обновленные данные реферера
            updated_referrer = await session.execute(
                select(User).where(User.id == referrer_id)
            )
            referrer = updated_referrer.scalar_one_or_none()
            
            if referrer:
                logger.info(f"Реферальная связь установлена: {user_id} <- {referrer_telegram_id}")
                logger.info(f"Пользователю {referrer_telegram_id} начислены 2 попытки, текущее кол-во: {referrer.attempts}")
            else:
                logger.error("Не удалось получить обновленные данные реферера")
                
        except Exception as e:
            logger.error(f"Ошибка при обновлении данных: {e}")
            await session.rollback()
            return False, None
        
        # Отправляем уведомление пригласившему, если есть экземпляр бота
        if bot:
            # Получаем информацию о приглашенном пользователе
            new_user_info = await bot.get_chat(user_id)
            
            # Формируем сообщение с уведомлением
            notification_text = (
                f"<b>🎉 Поздравляем! Вы пригласили нового пользователя!</b>\n\n"
                f"👤 Имя: {new_user_info.full_name}\n"
                f"🆔 ID: {user_id}\n\n"
                f"<i>Вам начислены 2 дополнительные попытки в слот-машине.</i>\n"
                f"Текущее количество попыток: <b>{referrer.attempts}</b>"
            )
            
            try:
                # Отправляем уведомление пригласившему
                await bot.send_message(
                    chat_id=referrer_telegram_id,
                    text=notification_text,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Отправлено уведомление пользователю {referrer_telegram_id} о приглашенном {user_id}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о реферале: {e}")
        
        return True, referrer.id
        
    except Exception as e:
        logger.error(f"Ошибка при обработке реферальной связи: {e}")
        await session.rollback()
        return False, None
        
async def get_referral_stats(user_id: int, session: AsyncSession) -> Tuple[int, int]:
    """
    Получает статистику рефералов пользователя
    
    Args:
        user_id: Telegram ID пользователя
        session: Сессия базы данных
        
    Returns:
        Tuple[int, int]: Количество приглашенных и попыток
    """
    try:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return 0, 0
            
        return user.invited_count, user.attempts
    except Exception as e:
        logger.error(f"Ошибка при получении статистики рефералов: {e}")
        return 0, 0 