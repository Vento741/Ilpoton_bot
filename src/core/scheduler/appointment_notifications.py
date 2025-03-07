from datetime import datetime, timedelta
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from loguru import logger

from database.models import Appointment, User, TimeSlot
from core.bot_instance import bot
from config.settings import settings
from database.base import async_session

async def notify_admin_about_appointment() -> None:
    """
    Проверяет и отправляет уведомления о предстоящих записях
    """
    try:
        # logger.info("Запущена проверка уведомлений")
        now = datetime.now()
        hour_later = now + timedelta(hours=1)
        
        # logger.info(f"Поиск записей: текущее время {now.strftime('%d.%m.%Y %H:%M')}")
        
        # Создаем новую сессию для каждой проверки
        async with async_session() as session:
            # Получаем записи, о которых еще не уведомляли
            result = await session.execute(
                select(Appointment)
                .join(Appointment.time_slot)
                .where(
                    Appointment.status == "CONFIRMED",
                    Appointment.notified == False,
                    Appointment.time_slot.has(
                        and_(
                            TimeSlot.date > now,  # Будущие записи
                            TimeSlot.date <= hour_later  # До которых осталось не больше часа
                        )
                    )
                )
                .options(
                    selectinload(Appointment.user),
                    selectinload(Appointment.service),
                    selectinload(Appointment.time_slot)
                )
            )
            appointments = result.scalars().all()

            # logger.info(f"Найдено записей для уведомления: {len(appointments)}")
            if appointments:
                for app in appointments:
                    time_until = app.time_slot.date - now
                    minutes_until = int(time_until.total_seconds() / 60)
                    # logger.info(f"Запись #{app.id} на {app.time_slot.date.strftime('%d.%m.%Y %H:%M')} "
                    #           f"(осталось {minutes_until} минут)")

            # Отправляем уведомления для каждой записи
            for appointment in appointments:
                notifications_sent = True  # Флаг успешной отправки всех уведомлений
                
                # Текст для клиента
                client_text = (
                    "⚠️ Напоминание о записи!\n\n"
                    f"⏰ Через час, в {appointment.time_slot.date.strftime('%H:%M')}\n"
                    f"💇‍♂️ Услуга: {appointment.service.name}\n"
                    f"💰 Стоимость: {appointment.final_price}₽\n\n"
                    "🙏 Пожалуйста, приходите за 5-10 минут до начала записи\n"
                    "📍 Если вам нужно отменить запись, сделайте это как можно раньше"
                )
                
                # Текст для админа
                admin_text = (
                    "⚠️ Напоминание о предстоящей записи!\n\n"
                    f"⏰ Через час, в {appointment.time_slot.date.strftime('%H:%M')}\n"
                    f"👤 Клиент: {appointment.user.full_name}\n"
                    f"📱 Телефон: {appointment.user.phone_number or 'Не указан'}\n"
                    f"🚘 Автомобиль: {appointment.car_brand} {appointment.car_model} ({appointment.car_year})\n"
                    f"💇‍♂️ Услуга: {appointment.service.name}\n"
                    f"💰 Стоимость: {appointment.final_price}₽\n"
                )
                
                if appointment.client_comment:
                    # Заменяем обычный текст на жирный для определенных фраз
                    formatted_comment = appointment.client_comment.replace(
                        "Запрос клиента:", "<b>Запрос клиента:</b>"
                    ).replace(
                        "Дополнительный вопрос:", "<b>Дополнительный вопрос:</b>"
                    ).replace(
                        "Ответ менеджера:", "<b>Ответ менеджера:</b>"
                    )
                    admin_text += f"\n💬 Комментарий клиента: {formatted_comment}"
                if appointment.admin_response:
                    admin_text += f"\n↪️ Ответ: {appointment.admin_response}"
                if appointment.admin_comment:
                    admin_text += f"\n👨‍💼 Для админов: {appointment.admin_comment}"
                
                # Клавиатуры
                client_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="❌ Отменить запись",
                        callback_data=f"client_cancel_appointment_{appointment.id}"
                    )
                ]])
                
                admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="📋 Детали записи",
                        callback_data=f"appointment_details_{appointment.id}"
                    )
                ]])
                
                # Отправляем уведомление клиенту
                try:
                    await bot.send_message(
                        appointment.user.telegram_id,
                        client_text,
                        reply_markup=client_keyboard,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления клиенту {appointment.user.telegram_id}: {e}")
                    notifications_sent = False
                
                # Отправляем уведомления админам
                admin_notifications_sent = True
                for admin_id in settings.admin_ids:
                    try:
                        await bot.send_message(
                            admin_id,
                            admin_text,
                            reply_markup=admin_keyboard,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")
                        admin_notifications_sent = False
                
                # Обновляем флаг уведомления только если все уведомления отправлены успешно
                if notifications_sent and admin_notifications_sent:
                    appointment.notified = True
                    logger.info(f"Отправлены уведомления о записи #{appointment.id}")
                
            # Сохраняем изменения
            await session.commit()
        
    except Exception as e:
        logger.error(f"Ошибка в планировщике уведомлений: {e}", exc_info=True) 