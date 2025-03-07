from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from loguru import logger

from database.models import Appointment
from core.bot_instance import bot

router = Router()

@router.callback_query(F.data.startswith("rate_service_"))
async def handle_service_rating(callback: CallbackQuery, session: AsyncSession):
    """
    Обрабатывает оценку услуги от клиента
    """
    try:
        # Получаем ID записи и оценку из callback_data
        parts = callback.data.split("_")
        appointment_id = int(parts[2])
        rating = int(parts[3])
        
        # Получаем запись из базы данных со связанными объектами
        result = await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await callback.answer("Запись не найдена", show_alert=True)
            return
            
        # Сохраняем оценку
        appointment.rating = rating
        await session.commit()
        
        # Отправляем сообщение с благодарностью за оценку
        thank_you_text = (
            f"🙏 Спасибо за вашу оценку!\n\n"
            f"Мы очень ценим ваше мнение и постоянно работаем над улучшением качества наших услуг.\n"
            f"Будем рады видеть вас снова! 😊"
        )
        
        # Редактируем исходное сообщение
        await callback.message.edit_text(
            text=thank_you_text,
            reply_markup=None  # Убираем клавиатуру с оценками
        )
        
        # Уведомляем администратора о новой оценке
        admin_notification = (
            f"⭐ Новая оценка от клиента!\n\n"
            f"👤 Клиент: {appointment.user.full_name}\n"
            f"💇‍♂️ Услуга: {appointment.service.name}\n"
            f"📅 Дата: {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"⭐ Оценка: {rating}/5"
        )
        
        # Отправляем уведомление всем администраторам
        from config.settings import settings
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, admin_notification)
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке оценки: {e}")
        await callback.answer("Произошла ошибка при сохранении оценки", show_alert=True) 