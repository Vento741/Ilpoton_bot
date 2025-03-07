"""
Планировщик для обновления попыток слот-машины
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, case
from loguru import logger

from database.models import User
from database.base import async_session

async def reset_daily_attempts():
    """
    Сбрасывает ежедневные попытки всем пользователям,
    сохраняя при этом попытки, полученные за рефералов
    """
    try:
        async with async_session() as session:
            # Получаем всех активных пользователей с их текущими попытками и количеством рефералов
            users = await session.execute(
                select(User)
                .where(User.is_active == True)
            )
            users = users.scalars().all()

            for user in users:
                # Вычисляем количество попыток от рефералов (1 попытка за каждого реферала)
                referral_attempts = user.invited_count

                # Устанавливаем новое количество попыток:
                # 2 базовые попытки + попытки за рефералов
                user.attempts = 2 + referral_attempts

            await session.commit()
            logger.info("Ежедневные попытки в слот-машине обновлены с сохранением реферальных бонусов")
    except Exception as e:
        logger.error(f"Ошибка при обновлении попыток: {e}")

def setup_slot_machine_scheduler(scheduler: AsyncIOScheduler) -> None:
    """
    Настраивает планировщик для обновления попыток
    
    Args:
        scheduler: Планировщик APScheduler
    """
    # Добавляем задачу на сброс попыток в 00:00 каждый день
    trigger = CronTrigger(hour=0, minute=0)
    
    scheduler.add_job(
        reset_daily_attempts,
        trigger=trigger,
        id='slot_machine_reset',
        name='Reset slot machine attempts',
        replace_existing=True
    )
    
    logger.info("Планировщик для обновления попыток в слот-машине настроен") 