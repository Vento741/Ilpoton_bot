from datetime import datetime, timedelta
from typing import Tuple, List
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from loguru import logger

from database.models import TimeSlot, Appointment
from core.bot_instance import bot

async def get_time_slots_view(date: datetime, session: AsyncSession) -> Tuple[str, List[List[InlineKeyboardButton]]]:
    """
    Получает представление временных слотов на дату
    Returns: (message_text, keyboard_buttons)
    """
    date_str = date.strftime('%d.%m.%Y')
    time_slots = await session.execute(
        select(TimeSlot)
        .where(
            TimeSlot.date >= date.replace(hour=0, minute=0),
            TimeSlot.date <= date.replace(hour=23, minute=59)
        )
        .order_by(TimeSlot.date)
    )
    time_slots = time_slots.scalars().all()
    
    # Получаем записи для этих слотов, исключая отмененные
    appointments = await session.execute(
        select(Appointment)
        .join(TimeSlot)
        .where(
            TimeSlot.date >= date.replace(hour=0, minute=0),
            TimeSlot.date <= date.replace(hour=23, minute=59),
            Appointment.status.in_(["PENDING", "CONFIRMED"])  # Исключаем CANCELLED
        )
        .options(
            selectinload(Appointment.user),
            selectinload(Appointment.service)
        )
    )
    appointments = appointments.scalars().all()
    
    # Создаем словарь для хранения информации о занятых часах
    occupied_slots = {}
    
    for app in appointments:
        slot_time = app.time_slot.date
        time_str = slot_time.strftime('%H:%M')
        occupied_slots[time_str] = {
            'appointment': app,
            'is_main': True
        }
        
        # Если запись подтверждена, добавляем следующий и предыдущий час
        if app.status == "CONFIRMED":
            # Следующий час
            next_hour = (slot_time + timedelta(hours=1))
            if next_hour.date() == slot_time.date():
                next_hour_str = next_hour.strftime('%H:%M')
                occupied_slots[next_hour_str] = {
                    'appointment': app,
                    'is_main': False
                }
            
            # Предыдущий час
            prev_hour = (slot_time - timedelta(hours=1))
            if prev_hour.date() == slot_time.date():
                prev_hour_str = prev_hour.strftime('%H:%M')
                occupied_slots[prev_hour_str] = {
                    'appointment': app,
                    'is_main': False
                }
    
    # Создаем клавиатуру
    keyboard = []
    
    # Добавляем кнопку для добавления слота на эту дату
    keyboard.append([InlineKeyboardButton(
        text="➕ Добавить слот на эту дату",
        callback_data=f"add_slot_to_date_{date_str}"
    )])
    
    # Формируем текст сообщения
    text = f"📅 Временные слоты на {date_str}:\n\n"
    
    # Добавляем информацию о каждом слоте
    for slot in time_slots:
        time_str = slot.date.strftime('%H:%M')
        slot_info = occupied_slots.get(time_str)
        
        if slot_info:
            app = slot_info['appointment']
            is_main = slot_info['is_main']
            status_emoji = "🕐" if app.status == "PENDING" else "🚗"
            
            if is_main:
                # Основной слот с записью
                text += (
                    f"\n{time_str} {status_emoji}\n"
                    f"👤 {app.user.full_name}\n"
                    f"💇‍♂️ {app.service.name}\n"
                )
                if app.final_price:
                    text += f"💰 {app.final_price}₽\n"
                else:
                    text += f"💰 от {app.service.price}₽\n"
                text += "-------------------\n"

                # Проверяем, есть ли следующий час
                next_hour = (app.time_slot.date + timedelta(hours=1)).strftime('%H:%M')
                if app.status == "CONFIRMED" and next_hour in occupied_slots:
                    # Объединяем текущий и следующий час в одну кнопку
                    keyboard.append([
                        InlineKeyboardButton(
                            text=f"{time_str}-{next_hour} {status_emoji} 🫵",
                            callback_data=f"view_appointment_{app.id}"
                        ),
                        InlineKeyboardButton(
                            text="🗑",
                            callback_data=f"cancel_appointment_{app.id}"
                        )
                    ])
                else:
                    # Если нет следующего часа или запись не подтверждена
                    keyboard.append([
                        InlineKeyboardButton(
                            text=f"{time_str} {status_emoji}",
                            callback_data=f"view_appointment_{app.id}"
                        ),
                        InlineKeyboardButton(
                            text="🗑",
                            callback_data=f"cancel_appointment_{app.id}"
                        )
                    ])
            elif not is_main:
                # Для неосновных слотов (предыдущий и следующий час) не создаем кнопки
                continue
        else:
            # Проверяем, не попадает ли этот слот в занятый диапазон
            is_occupied = False
            slot_datetime = slot.date
            
            for app in appointments:
                if app.status == "CONFIRMED":
                    # Проверяем, не попадает ли слот в диапазон час до и час после записи
                    appointment_time = app.time_slot.date
                    if (appointment_time - timedelta(hours=1) <= slot_datetime <= appointment_time + timedelta(hours=1)):
                        is_occupied = True
                        break
            
            if not is_occupied:
                # Если слот свободен
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"{time_str} ✅",
                        callback_data=f"select_time_slot_{slot.id}"
                    ),
                    InlineKeyboardButton(
                        text="🗑",
                        callback_data=f"delete_slot_{slot.id}"
                    )
                ])
    
    # Добавляем кнопку "Назад"
    keyboard.append([InlineKeyboardButton(
        text="↩️ Назад к датам",
        callback_data="manage_schedule"
    )])
    
    return text, keyboard

async def cancel_appointment(
    appointment: Appointment,
    reason: str,
    session: AsyncSession,
    notify_client: bool = True
) -> None:
    """
    Отменяет запись и выполняет все необходимые действия
    """
    try:
        # Сохраняем time_slot_id перед изменениями
        time_slot = appointment.time_slot
        
        # Обновляем статус записи
        appointment.status = "CANCELLED"
        appointment.cancellation_reason = reason
        
        # Освобождаем текущий слот
        if time_slot:
            time_slot.is_available = True
            
            # Если запись была подтверждена, освобождаем следующий час
            if appointment.confirmed_at:
                next_hour = time_slot.date + timedelta(hours=1)
                next_slot_result = await session.execute(
                    select(TimeSlot).where(TimeSlot.date == next_hour)
                )
                next_slot = next_slot_result.scalar_one_or_none()
                if next_slot:
                    next_slot.is_available = True
        
        await session.commit()
        
        if notify_client and appointment.user and appointment.user.telegram_id:
            try:
                # Отправляем уведомление клиенту без проверки на бота
                await bot.send_message(
                    appointment.user.telegram_id,
                    f"❌ Ваша запись отменена администратором:\n\n"
                    f"📅 Дата: {time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
                    f"💇‍♂️ Услуга: {appointment.service.name}\n"
                    f"❓ Причина: {reason}\n\n"
                    "Вы можете выбрать другое время для записи."
                )
                logger.info(f"Уведомление об отмене успешно отправлено клиенту {appointment.user.telegram_id}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления клиенту: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка при отмене записи: {e}", exc_info=True)
        await session.rollback()
        raise

async def check_and_clear_states(state: FSMContext) -> None:
    """
    Проверяет текущее состояние и очищает его при необходимости
    """
    current_state = await state.get_state()
    if current_state:
        logger.warning(f"Обнаружено активное состояние {current_state}, очищаем")
        await state.clear()

async def send_completion_message(appointment: Appointment) -> None:
    """
    Отправляет благодарственное сообщение клиенту после завершения записи
    """
    try:
        # Создаем клавиатуру для оценки
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1⭐", callback_data=f"rate_service_{appointment.id}_1"),
                InlineKeyboardButton(text="2⭐", callback_data=f"rate_service_{appointment.id}_2"),
                InlineKeyboardButton(text="3⭐", callback_data=f"rate_service_{appointment.id}_3"),
                InlineKeyboardButton(text="4⭐", callback_data=f"rate_service_{appointment.id}_4"),
                InlineKeyboardButton(text="5⭐", callback_data=f"rate_service_{appointment.id}_5")
            ]
        ])

        # Формируем текст сообщения
        message_text = (
            f"✨ Спасибо, что воспользовались нашими услугами!\n\n"
            f"📅 Дата: {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"💇‍♂️ Услуга: {appointment.service.name}\n"
            f"💰 Стоимость: {appointment.final_price or appointment.service.price}₽\n\n"
            f"🌟 Пожалуйста, оцените качество нашей работы:"
        )

        # Отправляем сообщение клиенту
        await bot.send_message(
            chat_id=appointment.user.telegram_id,
            text=message_text,
            reply_markup=keyboard
        )
        
        logger.info(f"Отправлено благодарственное сообщение клиенту (ID: {appointment.user.telegram_id})")
    except Exception as e:
        logger.error(f"Ошибка при отправке благодарственного сообщения: {e}")

async def update_completed_appointments(session: AsyncSession) -> None:
    """
    Обновляет статусы записей на COMPLETED для прошедших подтвержденных записей
    """
    try:
        # Получаем текущее время
        current_time = datetime.now()
        # logger.debug(f"Проверка завершенных записей. Текущее время: {current_time}")
        
        result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                Appointment.status == "CONFIRMED",
                TimeSlot.date < current_time  # Проверяем записи, время которых уже прошло
            )
            .options(
                selectinload(Appointment.time_slot),
                selectinload(Appointment.service),
                selectinload(Appointment.user)
            )
        )
        appointments = result.scalars().all()

        # Обновляем статусы
        updated_count = 0
        for appointment in appointments:
            # Проверяем, прошло ли время записи с учетом длительности услуги
            appointment_time = appointment.time_slot.date
            appointment_end_time = appointment_time + timedelta(minutes=appointment.service.duration)
            
            # logger.debug(f"Проверка записи #{appointment.id}:")
            # logger.debug(f"Время записи: {appointment_time}")
            # logger.debug(f"Время окончания: {appointment_end_time}")
            # logger.debug(f"Текущее время: {current_time}")
            
            # Проверяем, прошло ли время окончания записи
            if current_time > appointment_end_time:
                # Обновляем статус
                appointment.status = "COMPLETED"
                updated_count += 1
                # logger.info(f"Обновлен статус записи #{appointment.id} на COMPLETED (время записи: {appointment_time}, окончание: {appointment_end_time})")
                
                # Отправляем благодарственное сообщение
                await send_completion_message(appointment)

        if updated_count > 0:
            await session.commit()
            logger.info(f"Обновлено {updated_count} записей на статус COMPLETED")
        else:
            logger.debug("Нет записей для обновления статуса")
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении статусов записей: {e}")
        await session.rollback() 