# src/handlers/client/appointments.py

from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from loguru import logger
from typing import Union, List, Optional
import re
from aiogram.exceptions import TelegramBadRequest

from database.models import User, Service, Appointment, TimeSlot, PriceRequest
from keyboards.client.client import (
    get_services_keyboard,
    get_time_slots_keyboard,
    get_time_slots_for_date_keyboard,
    get_main_keyboard
)
from src.core.utils.constants import CANCELLATION_REASONS
from states.client import AppointmentStates
from config.settings import settings
from core.utils.logger import log_error
from core.bot import bot  # Updated import path
from ..admin.appointments import send_admin_notification

router = Router()

# Добавляем класс для управления сообщениями
class MessageManager:
    """
    Класс для управления сообщениями в процессе записи
    """
    def __init__(self):
        self.messages_to_delete: List[int] = []
    
    async def add_message(self, message: Message) -> None:
        """Добавляет сообщение в список на удаление"""
        if message and message.message_id:
            self.messages_to_delete.append(message.message_id)
    
    async def delete_messages(self, chat_id: int, bot: Bot) -> None:
        """Удаляет все сохраненные сообщения"""
        for msg_id in self.messages_to_delete:
            try:
                await bot.delete_message(chat_id, msg_id)
            except TelegramBadRequest:
                continue  # Игнорируем ошибки при удалении
        self.messages_to_delete = []

@router.message(F.text == "📝 Записаться")
async def start_appointment(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    """
    Начало процесса записи
    """
    try:
        logger.info(f"Пользователь {message.from_user.id} начал процесс записи")
        
        # Проверяем наличие активных записей у пользователя
        active_appointments = await session.execute(
            select(Appointment)
            .join(User)
            .join(TimeSlot)
            .where(
                User.telegram_id == message.from_user.id,
                TimeSlot.date >= datetime.now(),
                Appointment.status.in_(["PENDING", "CONFIRMED"])
            )
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        active_appointments = active_appointments.scalars().all()
        
        if active_appointments:
            # Формируем сообщение с информацией о существующих записях
            text = "❗️ У вас уже есть активные записи:\n\n"
            for app in active_appointments:
                status_emoji = "✅" if app.status == "CONFIRMED" else "🕐"
                price_text = f"{app.final_price}₽" if app.final_price else f"от {app.service.price}₽"
                text += (
                    f"{status_emoji} Запись #{app.id}\n"
                    f"<b>📅 Дата:</b> <code>{app.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
                    f"<b>💇‍♂️ Услуга:</b> <code>{app.service.name}</code>\n"
                    f"<b>💰 Стоимость:</b> <code>{price_text}</code>\n"
                    "-------------------\n"
                )
            
            text += "\nХотите создать еще одну запись?"
            
            # Создаем клавиатуру с выбором действия
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✅ Да, создать еще запись",
                    callback_data="create_another_appointment"
                )],
                [InlineKeyboardButton(
                    text="❌ Нет, отменить",
                    callback_data="cancel_booking"
                )]
            ])
            
            await message.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        
        # Инициализируем менеджер сообщений
        msg_manager = MessageManager()
        await state.update_data(msg_manager=msg_manager)
        
        # Получаем все услуги
        services = await session.execute(
            select(Service)
            .order_by(Service.id)
        )
        services = services.scalars().all()
        
        if not services:
            await message.answer(
                "❌ К сожалению, список услуг пока пуст.\n"
                "Пожалуйста, попробуйте позже.",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Устанавливаем состояние
        await state.set_state(AppointmentStates.selecting_service)
        
        # Формируем сообщение
        welcome_text = (
            "<b>🎯 Запись на обслуживание</b>\n\n"
            "<b>Для записи пройдите следующие шаги:</b>\n"
            "1️⃣ Выберите услугу\n"
            "2️⃣ Выберите дату\n"
            "3️⃣ Выберите время\n"
            "4️⃣ Укажите информацию об автомобиле\n"
            "5️⃣ Добавьте комментарий \\(при необходимости\\)\n\n"
            "<b>Выберите услугу из списка:</b>"
        )
        
        # Создаем клавиатуру с услугами
        keyboard = []
        for service in services:
            price_text = f"от {service.price}₽"
            duration_text = f"{service.duration} мин"
            button_text = f"{service.name} • {price_text} • ⏱ От {duration_text}"
            
            keyboard.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"appointment_select_service_{service.id}"
                )
            ])
        
        # Добавляем кнопку отмены
        keyboard.append([
            InlineKeyboardButton(
                text="❌ Отменить запись",
                callback_data="cancel_booking"
            )
        ])
        
        # Отправляем сообщение и сохраняем его
        sent_message = await message.answer(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
        # Сохраняем ID сообщения для последующего удаления
        await msg_manager.add_message(message)  # Сохраняем исходное сообщение пользователя
        await msg_manager.add_message(sent_message)  # Сохраняем ответное сообщение бота
        
    except Exception as e:
        log_error(e)
        await message.answer(
            "❌ Произошла ошибка при начале записи",
            reply_markup=get_main_keyboard()
        )
        await state.clear()

@router.callback_query(F.data.startswith("client_date_page_"))
async def handle_date_pagination(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Обработчик пагинации дат
    """
    try:
        page = int(callback.data.split("_")[3])
        
        time_slots = await session.execute(
            select(TimeSlot)
            .where(TimeSlot.date >= datetime.now(), TimeSlot.is_available == True)
            .order_by(TimeSlot.date)
        )
        time_slots = time_slots.scalars().all()
        
        await callback.message.edit_text(
            "<b>Выберите удобную дату для записи 📝:</b>",
            reply_markup=get_time_slots_keyboard(time_slots, page),
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при переключении страницы",
            reply_markup=get_main_keyboard()
        )


@router.callback_query(F.data.startswith("select_date_"), AppointmentStates.selecting_date)
async def process_date_selection(callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    """
    Обработка выбора даты
    """
    try:
        # Получаем выбранную дату
        selected_date = datetime.strptime(callback.data.split("_")[2], "%d.%m.%Y")
        
        # Получаем доступные слоты на выбранную дату
        time_slots = await session.execute(
            select(TimeSlot)
            .where(
                TimeSlot.date >= selected_date,
                TimeSlot.date < selected_date + timedelta(days=1),
                TimeSlot.is_available == True
            )
            .order_by(TimeSlot.date)
        )
        time_slots = time_slots.scalars().all()
        
        if not time_slots:
            await callback.answer("❌ На эту дату нет свободных слотов")
            return
        
        # Получаем данные о выбранной услуге
        data = await state.get_data()
        service = await session.get(Service, data['service_id'])
        
        # Очищаем предыдущие сообщения
        await clear_previous_messages(state, callback.message.chat.id, bot)
        
        # Устанавливаем состояние выбора времени
        await state.set_state(AppointmentStates.selecting_time)
        
        # Форматируем сообщение
        date_str = selected_date.strftime("%d.%m.%Y")
        service_info = (
            f"<b>🔧 Услуга:</b> <code>{service.name}</code>\n"
            f"<b>📅 Выбранная дата:</b> <code>{date_str}</code>\n"
            f"<b>⏱ Длительность:</b> от <code>{service.duration} мин</code>\n\n"
            f"<b>Выберите удобное время:</b>"
        )
        
        # Создаем клавиатуру с доступными временными слотами
        keyboard = []
        for slot in time_slots:
            time_str = slot.date.strftime("%H:%M")
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🕒 {time_str}",
                    callback_data=f"select_time_{slot.id}"
                )
            ])
        
        # Добавляем кнопки навигации
        nav_row = []
        nav_row.append(
            InlineKeyboardButton(
                text="◀️ Назад к датам",
                callback_data="client_back_to_dates"
            )
        )
        nav_row.append(
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="cancel_booking"
            )
        )
        keyboard.append(nav_row)
        
        try:
            # Пытаемся удалить предыдущее сообщение
            await callback.message.delete()
        except TelegramBadRequest as e:
            # Игнорируем ошибку, если сообщение уже удалено
            if "message to delete not found" not in str(e):
                logger.error(f"Ошибка при удалении сообщения: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при удалении сообщения: {e}")
        
        try:
            # Отправляем новое сообщение
            sent_message = await callback.message.answer(
                service_info,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                parse_mode="HTML"
            )
            
            # Сохраняем ID нового сообщения
            msg_manager = data.get("msg_manager")
            if msg_manager:
                await msg_manager.add_message(sent_message)
            
            # Сохраняем выбранную дату
            await state.update_data(selected_date=selected_date.strftime("%Y-%m-%d"))
            
        except Exception as e:
            logger.error(f"Ошибка при отправке нового сообщения: {e}")
            await callback.message.answer(
                "❌ Произошла ошибка при выборе даты",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")
                ]])
            )
            await state.clear()
            
    except Exception as e:
        log_error(e)
        try:
            await callback.message.answer(
                "❌ Произошла ошибка при выборе даты",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")
                ]])
            )
        except Exception as send_error:
            logger.error(f"Ошибка при отправке сообщения об ошибке: {send_error}")
        await state.clear()


@router.callback_query(F.data == "client_back_to_dates")
async def back_to_dates(callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    """
    Возврат к выбору даты
    """
    try:
        # Получаем доступные слоты
        time_slots = await session.execute(
            select(TimeSlot)
            .where(
                TimeSlot.date >= datetime.now(),
                TimeSlot.is_available == True
            )
            .order_by(TimeSlot.date)
        )
        time_slots = time_slots.scalars().all()
        
        if not time_slots:
            # Пробуем отредактировать текущее сообщение
            try:
                await callback.message.edit_text(
                    "❌ К сожалению, нет доступных слотов для записи",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")
                    ]]),
                    parse_mode="HTML"
                )
            except TelegramBadRequest:
                # Если не удалось отредактировать, отправляем новое
                await callback.message.answer(
                    "❌ К сожалению, нет доступных слотов для записи",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")
                    ]]),
                    parse_mode="HTML"
                )
            return
        
        # Очищаем предыдущие сообщения
        await clear_previous_messages(state, callback.message.chat.id, bot)
        
        # Получаем данные о выбранной услуге
        data = await state.get_data()
        service = await session.get(Service, data['service_id'])
        
        # Устанавливаем состояние выбора даты
        await state.set_state(AppointmentStates.selecting_date)
        
        # Формируем сообщение
        service_info = (
            f"<b>🔧 Выбранная услуга:</b> <code>{service.name}</code>\n"
            f"<b>💰 Стоимость:</b> от {service.price}₽\n"
            f"<b>⏱ Длительность:</b> {service.duration} мин\n\n"
            f"<b>📅 Выберите удобную дату:</b>"
        )
        
        # Пробуем отредактировать текущее сообщение
        try:
            edited_message = await callback.message.edit_text(
                service_info,
                reply_markup=get_time_slots_keyboard(time_slots),
                parse_mode="HTML"
            )
            # Сохраняем ID отредактированного сообщения
            msg_manager = data.get("msg_manager")
            if msg_manager:
                await msg_manager.add_message(edited_message)
        except TelegramBadRequest as e:
            # Если не удалось отредактировать, отправляем новое сообщение
            if "message to edit not found" in str(e):
                new_message = await callback.message.answer(
                    service_info,
                    reply_markup=get_time_slots_keyboard(time_slots),
                    parse_mode="HTML"
                )
                # Сохраняем ID нового сообщения
                msg_manager = data.get("msg_manager")
                if msg_manager:
                    await msg_manager.add_message(new_message)
            else:
                raise
        
    except Exception as e:
        logger.error(f"Ошибка в back_to_dates: {e}", exc_info=True)
        try:
            # Пробуем отредактировать текущее сообщение
            await callback.message.edit_text(
                "❌ Произошла ошибка при возврате к выбору даты",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")
                ]]),
                parse_mode="HTML"
            )
        except TelegramBadRequest:
            # Если не удалось отредактировать, отправляем новое
            await callback.message.answer(
                "❌ Произошла ошибка при возврате к выбору даты",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")
                ]]),
                parse_mode="HTML"
            )
        await state.clear()

@router.callback_query(F.data.startswith("select_time_"), AppointmentStates.selecting_time)
async def process_time_selection(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Обработка выбора времени
    """
    try:
        time_slot_id = int(callback.data.split("_")[2])
        time_slot = await session.get(TimeSlot, time_slot_id)
        
        if not time_slot or not time_slot.is_available:
            await callback.answer("Извините, этот слот уже занят. Выберите другое время.")
            return
        
        # Получаем данные из состояния
        data = await state.get_data()
        service_id = data.get('service_id')
        from_price_request = data.get('from_price_request', False)
        
        # Получаем сервис
        service = await session.get(Service, service_id)
        if not service:
            await callback.answer("❌ Услуга не найдена")
            return
        
        await state.update_data(time_slot_id=time_slot_id)
        
        if from_price_request:
            try:
                # Логика для запроса цены
                result = await session.execute(
                    select(PriceRequest)
                    .where(PriceRequest.id == data['price_request_id'])
                    .options(selectinload(PriceRequest.user))
                )
                price_request = result.scalar_one_or_none()
                
                if price_request:
                    # Разбираем car_info на составляющие
                    car_info = price_request.car_info.split()
                    if len(car_info) >= 3:
                        car_brand = car_info[0]
                        car_year = car_info[-1]
                        car_model = " ".join(car_info[1:-1])
                        
                        # Извлекаем цену из ответа админа, если она есть
                        final_price = None
                        if price_request.admin_response:
                            price_match = re.search(r'(\d+)(?:₽)?', price_request.admin_response)
                            if price_match:
                                final_price = int(price_match.group(1))
                        
                        await state.update_data({
                            'service_id': service_id,
                            'time_slot_id': time_slot_id,
                            'car_brand': car_brand,
                            'car_model': car_model,
                            'car_year': car_year,
                            'final_price': final_price,
                            'user_id': price_request.user_id
                        })
                        
                        await create_appointment(callback.message, state, session)
                    else:
                        logger.error(f"Некорректный формат car_info: {price_request.car_info}")
                        await callback.message.edit_text(
                            "Произошла ошибка при обработке данных автомобиля",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(
                                    text="↩️ Вернуться в главное меню",
                                    callback_data="back_to_main"
                                )
                            ]])
                        )
                else:
                    await callback.answer("Запрос не найден")
                    return
            except Exception as e:
                logger.error(f"Ошибка при обработке запроса цены: {e}")
                await callback.message.edit_text(
                    "Произошла ошибка при обработке запроса",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="↩️ Вернуться в главное меню",
                            callback_data="back_to_main"
                        )
                    ]])
                )
                return
        else:
            # Переходим к вводу марки автомобиля
            await state.set_state(AppointmentStates.entering_car_brand)
            
            # Форматируем сообщение с информацией о выбранном времени и услуге
            message_text = (
                f"<b>🕒 Выбранное время:</b> <code>{time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
                f"<b>🔧 Услуга:</b> <code>{service.name}</code>\n"
                f"<b>💰 Стоимость:</b> от {service.price}₽\n"
                f"<b>⏱ Длительность:</b> {service.duration} мин.\n\n"
                f"<b>🚗 Пожалуйста, введите марку вашего автомобиля:</b>\n\n"
                f"<i>Например:</i> <b>Toyota_, BMW_, Mercedes_</b>\n"
                f"<i>А так-же можете написать марку на русском:</i> <b>Тойота, БМВ, Мерседес</b>"
            )
            
            # Создаем клавиатуру с кнопкой отмены
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отменить запись", callback_data="cancel_booking")
            ]])
            
            await callback.message.edit_text(
                message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Ошибка при выборе времени: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при выборе времени",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ Вернуться в главное меню",
                    callback_data="back_to_main"
                )
            ]])
        )

async def get_user(user_data, session: AsyncSession) -> User:
    """
    Получает или создает пользователя
    """
    user = await session.execute(
        select(User).where(User.telegram_id == user_data.id)
    )
    user = user.scalar_one_or_none()
    
    if not user:
        # Проверяем, что это не бот
        chat = await bot.get_chat(user_data.id)
        user = User(
            telegram_id=user_data.id,
            username=user_data.username,
            full_name=chat.full_name or user_data.full_name,  # Используем полное имя из чата
            is_admin=False  # Явно указываем, что это не админ
        )
        session.add(user)
        await session.flush()
    
    return user

@router.callback_query(F.data.startswith("appointment_select_service_"), AppointmentStates.selecting_service)
async def process_service_selection(callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    """
    Обработка выбора услуги
    """
    try:
        service_id = int(callback.data.split("_")[3])
        
        # Получаем выбранную услугу
        service = await session.get(Service, service_id)
        if not service:
            await callback.answer("❌ Услуга не найдена")
            return
        
        # Сохраняем ID услуги в состояние
        await state.update_data(service_id=service_id)
        
        # Получаем доступные временные слоты
        time_slots = await session.execute(
            select(TimeSlot)
            .where(
                TimeSlot.date >= datetime.now(),
                TimeSlot.is_available == True
            )
            .order_by(TimeSlot.date)
        )
        time_slots = time_slots.scalars().all()
        
        if not time_slots:
            await callback.message.edit_text(
                "❌ К сожалению, нет доступных слотов для записи",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")
                ]])
            )
            return
        
        # Очищаем предыдущие сообщения
        await clear_previous_messages(state, callback.message.chat.id, bot)
        
        # Устанавливаем состояние выбора даты
        await state.set_state(AppointmentStates.selecting_date)
        
        # Форматируем сообщение
        service_info = (
            f"<b>🔧 Выбранная услуга:</b> <code>{service.name}</code>\n"
            f"<b>💰 Стоимость:</b> от {service.price}₽\n"
            f"<b>⏱ Длительность:</b> от {service.duration} мин\n\n"
            f"<b>📅 Выберите удобную дату:</b>"
        )
        
        # Отправляем новое сообщение с клавиатурой дат
        sent_message = await callback.message.answer(
            service_info,
            reply_markup=get_time_slots_keyboard(time_slots),
            parse_mode="HTML"
        )
        
        # Сохраняем ID нового сообщения
        data = await state.get_data()
        msg_manager = data.get("msg_manager")
        if msg_manager:
            await msg_manager.add_message(sent_message)
        
        # Пытаемся удалить предыдущее сообщение
        try:
            await callback.message.delete()
        except TelegramBadRequest as e:
            if "message to delete not found" not in str(e):
                logger.error(f"Ошибка при удалении сообщения: {e}")
        
    except Exception as e:
        log_error(e)
        try:
            await callback.message.edit_text(
                "❌ Произошла ошибка при выборе услуги",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Вернуться в главное меню", callback_data="back_to_main")
                ]])
            )
        except Exception as send_error:
            logger.error(f"Ошибка при отправке сообщения об ошибке: {send_error}")


@router.message(AppointmentStates.entering_car_brand)
async def process_car_brand(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода марки автомобиля
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отменить запись", callback_data="cancel_booking")
    ]])
    
    await state.update_data(car_brand=message.text)
    await state.set_state(AppointmentStates.entering_car_model)
    await message.answer(
        "<b>🚗 Введите модель автомобиля</b> (например: <u>Camry</u>, <u>X5</u>, <u>A4</u>):",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(AppointmentStates.entering_car_model)
async def process_car_model(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода модели автомобиля
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отменить запись", callback_data="cancel_booking")
    ]])
    
    await state.update_data(car_model=message.text)
    await state.set_state(AppointmentStates.entering_car_year)
    await message.answer(
        "<b>🚗 Введите год выпуска автомобиля</b>:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(AppointmentStates.entering_car_year)
async def process_car_year(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода года выпуска
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отменить запись", callback_data="cancel_booking")
    ]])
    
    try:
        year = int(message.text)
        current_year = datetime.now().year
        
        if year < 1900 or year > current_year:
            await message.answer(
                f"<b>Пожалуйста, введите корректный год от 1900 до {current_year}</b>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        
        await state.update_data(car_year=str(year))
        await state.set_state(AppointmentStates.entering_comment)
        await message.answer(
            "<b>Добавьте комментарий к записи (например, особенности автомобиля или пожелания):\n"
            "Или нажмите /skip, чтобы пропустить</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer(
            "<b>Пожалуйста, введите год в числовом формате (например, 2020)</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )


@router.message(Command("skip"), AppointmentStates.entering_comment)
async def skip_comment(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Пропуск ввода комментария
    """
    await create_appointment(message, state, session)

@router.callback_query(F.data == "cancel_booking")
async def cancel_booking(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """
    Отмена процесса записи
    """
    try:
        # Очищаем предыдущие сообщения
        await clear_previous_messages(state, callback.message.chat.id, bot)
        
        # Пытаемся удалить текущее сообщение
        try:
            await callback.message.delete()
        except TelegramBadRequest as e:
            if "message to delete not found" not in str(e):
                logger.error(f"Ошибка при удалении сообщения: {e}")
        
        # Отправляем сообщение об отмене
        await callback.message.answer(
            "❌ Запись отменена",
            reply_markup=get_main_keyboard()
        )
        
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при отмене записи: {e}", exc_info=True)
        try:
            # Пробуем отправить новое сообщение
            await callback.message.answer(
                "❌ Запись отменена",
                reply_markup=get_main_keyboard()
            )
        except Exception as send_error:
            logger.error(f"Ошибка при отправке сообщения об отмене: {send_error}")
        
        # В любом случае очищаем состояние
        await state.clear()



@router.message(AppointmentStates.entering_comment)
async def process_comment(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка ввода комментария и создание записи
    """
    current_state = await state.get_state()
    logger.info(f"Текущее состояние: {current_state}")
    logger.info(f"Получен комментарий от пользователя {message.from_user.id}: {message.text}")
    
    # Проверяем, что сообщение не является командой
    if message.text.startswith('/'):
        logger.info("Сообщение является командой, пропускаем")
        return
        
    await state.update_data(client_comment=message.text)
    logger.info("Начинаем создание записи")
    await create_appointment(message, state, session)
    logger.info("Запись создана")


async def create_appointment(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Создание записи
    """
    try:
        data = await state.get_data()
        logger.info(f"Данные для создания записи: {data}")
        
        # Проверяем существование пользователя или создаем нового
        if data.get('from_price_request') and data.get('user_data'):
            # Если запись из запроса стоимости, используем данные пользователя из состояния
            user_result = await session.execute(
                select(User)
                .where(User.id == data['user_id'])
            )
            user = user_result.scalar_one_or_none()
            if not user:
                logger.error(f"Пользователь не найден: {data.get('user_id')}")
                raise ValueError("User not found")
        else:
            # Стандартный процесс получения пользователя
            user_result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                # Создаем нового пользователя
                user = User(
                    telegram_id=message.from_user.id,
                    username=message.from_user.username,
                    full_name=message.from_user.full_name
                )
                session.add(user)
                await session.flush()  # Чтобы получить id пользователя
        
        # Получаем временной слот и проверяем его доступность
        time_slot = await session.get(TimeSlot, data['time_slot_id'])
        if not time_slot or not time_slot.is_available:
            await message.answer(
                "<b>Извините, выбранное время уже занято. Пожалуйста, выберите другое время.</b>",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        # Получаем сервис
        service = await session.get(Service, data['service_id'])
        
        # Если запись создается из запроса стоимости, получаем информацию о запросе
        client_comment = data.get('client_comment', '')
        price_text = None
        final_price = None
        if data.get('from_price_request'):
            price_request_result = await session.execute(
                select(PriceRequest)
                .where(PriceRequest.id == data['price_request_id'])
            )
            price_request = price_request_result.scalar_one_or_none()
            if price_request:
                client_comment = (
                    f"<b>Запись создана на основе запроса расчета стоимости #{price_request.id}</b>\n"
                    f"<b>Запрос клиента:</b> <code> {price_request.car_info}</code>\n"
                    f"{f'<b>Дополнительный вопрос:</b> <code>{price_request.additional_question}</code>\n' if price_request.additional_question else ''}"
                    f"<b>Ответ менеджера:</b> <code>{price_request.admin_response}</code>\n"
                    f"{client_comment}"
                ).strip()
                
                # Извлекаем цену из ответа менеджера
                if price_request.admin_response:
                    # Сначала ищем точную цену
                    exact_price_match = re.search(r'составит (\d+)₽', price_request.admin_response)
                    if exact_price_match:
                        final_price = int(exact_price_match.group(1))
                        price_text = f"<b>{final_price}₽</b>"
                    else:
                        # Если точной цены нет, ищем минимальную цену из диапазона
                        range_price_match = re.search(r'составит от (\d+)₽', price_request.admin_response)
                        if range_price_match:
                            final_price = int(range_price_match.group(1))
                            price_text = f"от <b>{final_price}₽</b>"

        # Если цена не была установлена из ответа админа, используем стандартную логику
        if not price_text:
            final_price = service.price
            price_text = f"от {service.price}₽"
        
        # Создаем запись с учетом final_price
        appointment = Appointment(
            user_id=user.id,
            service_id=data['service_id'],
            time_slot_id=data['time_slot_id'],
            car_brand=data['car_brand'],
            car_model=data['car_model'],
            car_year=data['car_year'],
            client_comment=client_comment,
            final_price=final_price,  # Используем извлеченную или базовую цену
            status="PENDING"
        )
        
        # Помечаем слот как занятый
        time_slot.is_available = False
        
        # Помечаем следующий час как занятый
        next_hour = time_slot.date + timedelta(hours=1)
        next_slot_result = await session.execute(
            select(TimeSlot)
            .where(TimeSlot.date == next_hour)
        )
        next_slot = next_slot_result.scalar_one_or_none()
        
        if next_slot:
            next_slot.is_available = False
            logger.info("Следующий час помечен как занятый")
        else:
            # Если следующего слота нет, создаем его
            next_slot = TimeSlot(date=next_hour, is_available=False)
            session.add(next_slot)
            logger.info("Создан и помечен как занятый новый слот на следующий час")

        # Помечаем предыдущий час как занятый
        prev_hour = time_slot.date - timedelta(hours=1)
        prev_slot_result = await session.execute(
            select(TimeSlot)
            .where(TimeSlot.date == prev_hour)
        )
        prev_slot = prev_slot_result.scalar_one_or_none()
        
        if prev_slot:
            prev_slot.is_available = False
            logger.info("Предыдущий час помечен как занятый")
        else:
            # Если предыдущего слота нет, создаем его
            prev_slot = TimeSlot(date=prev_hour, is_available=False)
            session.add(prev_slot)
            logger.info("Создан и помечен как занятый новый слот на предыдущий час")
        
        session.add(appointment)
        await session.commit()
        
        # Изменяем текст сообщения клиенту
        await message.answer(
            f"<b>✅ Запись успешно создана!</b>\n\n"
            f"📅 <b>Дата и время:</b> <code>{time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
            f"🔧 <b>Услуга:</b> <code>{service.name}</code>\n"
            f"🚗 <b>Автомобиль:</b> <code>{data['car_brand']} {data['car_model']} ({data['car_year']})</code>\n"
            f"💰 <b>Стоимость:</b> <code>{price_text}</code>\n"
            f"⏱ <b>Длительность:</b> <code>{service.duration} мин.</code>\n\n"
            "<i>ℹ️ Точную стоимость работ вы получите при подтверждении записи. "
            "Если цена окажется для вас высокой или вы передумали - вы всегда можете отменить "
            "запись в личном кабинете 😊 👍</i>\n\n"
            "<b>Администратор свяжется с вами для подтверждения записи.</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        
        # Отправляем уведомление администраторам
        admin_text = (
            f"<b>🆕 Новая запись!</b>\n\n"
            f"👤 <b>Клиент:</b> <code>{user.full_name}</code>\n"
            f"📱 <b>Телефон:</b> <code>{user.phone_number or 'Не указан'}</code>\n"
            f"📅 <b>Дата:</b> <code>{time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
            f"🔧 <b>Услуга:</b> <code>{service.name}</code>\n"
            f"🚗 <b>Автомобиль:</b> <code>{data['car_brand']} {data['car_model']} ({data['car_year']})</code>\n"
            f"💰 <b>Стоимость:</b> <code>{price_text}</code>\n"
            f"💬 <b>Комментарий:</b> {client_comment or 'Нет'}"
        )
        
        # Отправляем уведомление администраторам
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    admin_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="✅ Подтвердить",
                            callback_data=f"confirm_appointment_{appointment.id}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Отменить",
                            callback_data=f"cancel_appointment_{appointment.id}"
                        )
                    ]]),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")
        
        await state.clear()
        logger.info("Состояние очищено после создания записи")
        
    except Exception as e:
        log_error(e)
        await message.answer(
            "Произошла ошибка при создании записи. Пожалуйста, попробуйте позже.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()


@router.callback_query(F.data.startswith("book_from_price_request_"))
async def book_from_price_request(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Начало процесса записи из ответа на запрос стоимости
    """
    try:
        logger.info(f"Вызван обработчик записи из запроса стоимости с данными: {callback.data}")
        
        # Разбираем callback_data
        parts = callback.data.split("_")
        # Обеспечиваем корректное извлечение service_id и price_request_id
        if len(parts) >= 4:  # book_from_price_request_{service_id}_{price_request_id}
            service_id = int(parts[-2])  # Предпоследний элемент
            price_request_id = int(parts[-1])  # Последний элемент
            
            logger.info(f"Начало записи из запроса стоимости: service_id={service_id}, price_request_id={price_request_id}")
            
            # Получаем запрос на расчет стоимости с пользователем
            result = await session.execute(
                select(PriceRequest)
                .where(PriceRequest.id == price_request_id)
                .options(
                    selectinload(PriceRequest.service),
                    selectinload(PriceRequest.user)
                )
            )
            price_request = result.scalar_one_or_none()
            
            if not price_request:
                logger.error(f"Запрос не найден: price_request_id={price_request_id}")
                await callback.answer("Запрос не найден")
                return
                
            # Сохраняем данные в состояние
            await state.update_data({
                'service_id': service_id,
                'car_info': price_request.car_info,
                'from_price_request': True,
                'price_request_id': price_request_id,
                'user_id': price_request.user_id,  # Сохраняем ID пользователя из запроса
                'user_data': {  # Сохраняем данные пользователя
                    'full_name': price_request.user.full_name,
                    'phone_number': price_request.user.phone_number,
                    'telegram_id': price_request.user.telegram_id
                }
            })
            
            # Получаем список доступных временных слотов
            time_slots = await session.execute(
                select(TimeSlot)
                .where(TimeSlot.date >= datetime.now(), TimeSlot.is_available == True)
                .order_by(TimeSlot.date)
            )
            time_slots = time_slots.scalars().all()
            
            if not time_slots:
                await callback.message.edit_text(
                    "К сожалению, в данный момент нет доступных слотов для записи. Попробуйте позже.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="↩️ Вернуться в главное меню",
                            callback_data="back_to_main"
                        )]
                    ])
                )
                return

            await state.set_state(AppointmentStates.selecting_date)
            await callback.message.edit_text(
                "*Выберите удобную дату для записи:*",
                reply_markup=get_time_slots_keyboard(time_slots),
                parse_mode="Markdown"
            )
        else:
            logger.error(f"Некорректный формат callback_data: {callback.data}")
            await callback.answer("Произошла ошибка. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка при начале записи из запроса стоимости: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при начале записи. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="↩️ Вернуться в главное меню",
                    callback_data="back_to_main"
                )]
            ])
        )

@router.callback_query(F.data == "create_another_appointment")
async def handle_create_another(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Обработчик создания еще одной записи
    """
    try:
        await callback.answer()
        
        # Инициализируем менеджер сообщений
        msg_manager = MessageManager()
        await state.update_data(msg_manager=msg_manager)
        
        # Получаем все услуги
        services = await session.execute(
            select(Service)
            .order_by(Service.id)
        )
        services = services.scalars().all()
        
        if not services:
            await callback.message.edit_text(
                "❌ К сожалению, список услуг пока пуст.\n"
                "Пожалуйста, попробуйте позже.",
                reply_markup=get_main_keyboard()
            )
            return

        # Устанавливаем состояние выбора услуги
        await state.set_state(AppointmentStates.selecting_service)
        
        # Формируем сообщение
        welcome_text = (
            "<b>🎯 Запись на обслуживание</b>\n\n"
            "<b>Для записи пройдите следующие шаги:</b>\n"
            "1️⃣ Выберите услугу\n"
            "2️⃣ Выберите дату\n"
            "3️⃣ Выберите время\n"
            "4️⃣ Укажите информацию об автомобиле\n"
            "5️⃣ Добавьте комментарий (при необходимости)\n\n"
            "<b>Выберите услугу из списка:</b>"
        )
        
        # Создаем клавиатуру с услугами
        keyboard = []
        for service in services:
            price_text = f"от {service.price}₽"
            duration_text = f"{service.duration} мин"
            button_text = f"{service.name} • {price_text} • ⏱ От {duration_text}"
            
            keyboard.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"appointment_select_service_{service.id}"
                )
            ])
        
        # Добавляем кнопку отмены
        keyboard.append([
            InlineKeyboardButton(
                text="❌ Отменить запись",
                callback_data="cancel_booking"
            )
        ])
        
        # Отправляем новое сообщение и сохраняем его
        try:
            await callback.message.delete()
        except Exception as e:
            logger.debug(f"Не удалось удалить старое сообщение: {e}")
            
        sent_message = await callback.message.answer(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
        # Сохраняем ID сообщения для последующего удаления
        await msg_manager.add_message(sent_message)
        
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "❌ Произошла ошибка при начале записи",
            reply_markup=get_main_keyboard()
        )
        await state.clear()


@router.callback_query(F.data == "cancel_specific_appointment")
async def ask_appointment_to_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запрос номера записи для отмены
    """
    await state.set_state(AppointmentStates.canceling_appointment)
    await callback.message.answer(
        "<b>Введите номер записи, которую хотите отменить</b> (только цифру).\n"
        "<i>Например: 42</i>",
        parse_mode="HTML"
    )


@router.message(AppointmentStates.canceling_appointment)
async def process_appointment_cancellation(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """
    Обработка отмены конкретной записи
    """
    try:
        appointment_id = int(message.text)
        
        # Получаем запись
        result = await session.execute(
            select(Appointment)
            .where(
                Appointment.id == appointment_id,
                Appointment.user_id == (
                    select(User.id)
                    .where(User.telegram_id == message.from_user.id)
                    .scalar_subquery()
                )
            )
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await message.answer(
                "❌ Запись не найдена или у вас нет прав для её отмены.\n"
                "Проверьте номер записи и попробуйте снова.",
                reply_markup=get_main_keyboard()
            )
            await state.clear()
            return
            
        if appointment.status == "CANCELLED":
            await message.answer(
                "❌ Эта запись уже была отменена.",
                reply_markup=get_main_keyboard()
            )
            await state.clear()
            return

        # Сохраняем ID записи в состояние
        await state.update_data(appointment_id=appointment_id)
        
        # Запрашиваем причину отмены
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменились планы",
                    callback_data=f"cancel_reason_plans_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Нашел другое место",
                    callback_data=f"cancel_reason_other_place_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не устроила цена",
                    callback_data=f"cancel_reason_price_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не могу приехать",
                    callback_data=f"cancel_reason_cant_come_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Другая причина",
                    callback_data=f"cancel_reason_custom_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Не отменять",
                    callback_data=f"dont_cancel_{appointment_id}"
                )
            ]
        ])
        
        await state.set_state(AppointmentStates.entering_cancel_reason)
        await message.answer(
            "🤔 Не могли бы вы указать причину отмены записи? Это поможет нам стать лучше.",
            reply_markup=keyboard
        )
        
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите только номер записи (цифру).\n"
            "Например: 7"
        )
    except Exception as e:
        log_error(e)
        await message.answer(
            "❌ Произошла ошибка при отмене записи. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()


@router.callback_query(F.data.startswith("cancel_reason_"))
async def handle_cancel_reason_selection(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Обработка выбора причины отмены
    """
    try:
        data = await state.get_data()
        appointment_id = data.get('appointment_id')
        
        if not appointment_id:
            await callback.answer("Ошибка: запись не найдена")
            return
            
        # Изменяем извлечение reason_type, учитывая формат "cancel_reason_cant_come_14"
        parts = callback.data.split("_")
        if len(parts) >= 4:
            # Если это формат с ID записи
            reason_type = "_".join(parts[2:-1])  # объединяем все части между "cancel_reason_" и ID
        else:
            # Если это старый формат без ID
            reason_type = parts[2]
        
        if reason_type == "custom":
            await state.set_state(AppointmentStates.entering_cancel_reason)
            await callback.message.edit_text(
                "📝 Пожалуйста, напишите причину отмены своими словами:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=f"dont_cancel_{appointment_id}"
                    )
                ]])
            )
            return
            
        # Маппинг причин отмены
        reasons = {
            "plans": "Изменились планы",
            "other_place": "Нашел другое место",
            "price": "Не устроила цена",
            "cant_come": "Не могу приехать",
            "other_service": "Нашел другой сервис",
            "custom": "Другая причина"
        }
        
        reason = reasons.get(reason_type)
        if not reason:
            logger.error(f"Неизвестный тип причины отмены: {reason_type}")
            reason = "Причина не указана"
        
        # Получаем запись
        result = await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot),
                selectinload(Appointment.user)
            )
        )
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await callback.answer("Запись не найдена")
            return
            
        # Отменяем запись
        appointment.status = "CANCELLED"
        appointment.cancellation_reason = reason
        appointment.time_slot.is_available = True
        
        # Если запись была подтверждена, освобождаем следующий час
        if appointment.confirmed_at:
            next_hour = appointment.time_slot.date + timedelta(hours=1)
            next_slot_result = await session.execute(
                select(TimeSlot).where(TimeSlot.date == next_hour)
            )
            next_slot = next_slot_result.scalar_one_or_none()
            if next_slot:
                next_slot.is_available = True
        
        await session.commit()
        
        # Отправляем подтверждение клиенту
        await callback.message.edit_text(
            f"<b>✅ Запись успешно отменена</b>\n"
            f"<b>Причина:</b> {reason}\n\n"
            f"<b>📅 Дата:</b> {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"<b>💇‍♂️ Услуга:</b> {appointment.service.name}\n\n"
            "Вы можете создать новую запись в любое удобное время.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ В главное меню", callback_data="back_to_main")
            ]]),
            parse_mode="HTML"
        )
        
        # Уведомляем администраторов
        await send_cancellation_notifications(appointment, reason)
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при обработке причины отмены: {e}", exc_info=True)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при отмене записи. Попробуйте позже.</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ В главное меню", callback_data="back_to_main")
            ]])
        )
        await state.clear()

@router.message(AppointmentStates.entering_cancel_reason)
async def handle_custom_cancel_reason(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """
    Обработка пользовательской причины отмены
    """
    try:
        data = await state.get_data()
        appointment_id = data.get('appointment_id')
        
        if not appointment_id:
            await message.answer("Произошла ошибка. Попробуйте отменить запись заново.")
            await state.clear()
            return
            
        # Получаем запись
        result = await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot),
                selectinload(Appointment.user)
            )
        )
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await message.answer("Запись не найдена")
            await state.clear()
            return
            
        # Отменяем запись
        appointment.status = "CANCELLED"
        appointment.cancellation_reason = message.text
        appointment.time_slot.is_available = True
        
        # Если запись была подтверждена, освобождаем следующий час
        if appointment.confirmed_at:
            next_hour = appointment.time_slot.date + timedelta(hours=1)
            next_slot_result = await session.execute(
                select(TimeSlot).where(TimeSlot.date == next_hour)
            )
            next_slot = next_slot_result.scalar_one_or_none()
            if next_slot:
                next_slot.is_available = True
        
        await session.commit()
        
        # Отправляем подтверждение клиенту
        await message.answer(
            f"<b>✅ Запись успешно отменена</b>\n"
            f"<b>Причина:</b> {message.text}\n\n"
            f"<b>📅 Дата:</b> {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"<b>💇‍♂️ Услуга:</b> {appointment.service.name}\n\n"
            "Вы можете создать новую запись в любое удобное время.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ В главное меню", callback_data="back_to_main")
            ]]),
            parse_mode="HTML"
        )
        
        # Уведомляем администраторов
        await send_cancellation_notifications(appointment, message.text)
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при обработке пользовательской причины: {e}", exc_info=True)
        await message.answer(
            "<b>❌ Произошла ошибка при отмене записи. Попробуйте позже.</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()

@router.callback_query(F.data.startswith("dont_cancel_"))
async def cancel_cancellation(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Отмена процесса отмены записи
    """
    try:
        # Очищаем состояние
        await state.clear()
        
        # Получаем ID записи
        appointment_id = int(callback.data.split("_")[2])
        
        # Получаем запись для отображения информации
        result = await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await callback.answer("Запись не найдена")
            return
            
        # Возвращаем пользователя к информации о записи
        status_emoji = "✅" if appointment.status == "CONFIRMED" else "🕐"
        price_text = f"{appointment.final_price}₽" if appointment.final_price else f"от {appointment.service.price}₽"
        
        text = (
            f"{status_emoji} Запись #{appointment.id}\n"
            f"📅 Дата: {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"<b>💇‍♂️ Услуга:</b> {appointment.service.name}\n"
            f"<b>💰 Стоимость:</b> {price_text}\n"
            f"<b>📊 Статус:</b> {CANCELLATION_REASONS[appointment.status]}"
        )
        
        keyboard = [
            [InlineKeyboardButton(
                text="❌ Отменить запись",
                callback_data=f"client_cancel_appointment_{appointment.id}"
            )],
            [InlineKeyboardButton(
                text="↩️ Назад",
                callback_data="back_to_profile"
            )]
        ]
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отмене отмены записи: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")

@router.callback_query(F.data.startswith("client_cancel_appointment_"))
async def start_cancel_appointment(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Начало процесса отмены записи клиентом
    """
    try:
        appointment_id = int(callback.data.split("_")[3])
        
        # Проверяем статус записи
        result = await session.execute(
            select(Appointment)
            .where(
                Appointment.id == appointment_id,
                Appointment.user_id == (
                    select(User.id)
                    .where(User.telegram_id == callback.from_user.id)
                    .scalar_subquery()
                )
            )
            .options(
                selectinload(Appointment.time_slot),
                selectinload(Appointment.service)
            )
        )
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await callback.answer("Запись не найдена", show_alert=True)
            return
            
        # Проверяем, можно ли отменить запись
        if appointment.status == "COMPLETED":
            await callback.answer(
                "❌ Невозможно отменить выполненную запись",
                show_alert=True
            )
            return
            
        if appointment.status == "CANCELLED":
            await callback.answer(
                "❌ Эта запись уже была отменена",
                show_alert=True
            )
            return
        
        await state.update_data(appointment_id=appointment_id)
        
        # Создаем клавиатуру с причинами отмены
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменились планы",
                    callback_data=f"cancel_reason_plans_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Нашел другое место",
                    callback_data=f"cancel_reason_other_place_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не устроила цена",
                    callback_data=f"cancel_reason_price_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не могу приехать",
                    callback_data=f"cancel_reason_cant_come_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Другая причина",
                    callback_data=f"cancel_reason_custom_{appointment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Не отменять",
                    callback_data=f"dont_cancel_{appointment_id}"
                )
            ]
        ])
        
        await callback.message.edit_text(
            "<b>Пожалуйста, укажите причину отмены записи:</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при начале отмены записи: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при отмене записи")

async def send_cancellation_notifications(appointment: Appointment, reason: str) -> None:
    """
    Отправляет уведомления об отмене записи клиенту и администраторам
    """
    # Уведомление клиенту
    client_text = (
        "<b>✅ Запись успешно отменена</b>\n"
        f"<b>Причина:</b> <i>{reason}</i>\n\n"
        f"<b>📅 Дата:</b> <code>{appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
        f"<b>💇‍♂️ Услуга:</b> <code>{appointment.service.name}</code>\n\n"
        "<i>Вы можете создать новую запись в любое удобное время.</i>"
    )
    
    # Уведомление администраторам
    admin_text = (
        "<b>❌ Клиент отменил запись!</b>\n\n"
        f"<b>👤 Клиент:</b> <code>{appointment.user.full_name}</code>\n"
        f"<b>📅 Дата:</b> <code>{appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
        f"<b>💇‍♂️ Услуга:</b> <code>{appointment.service.name}</code>\n"
        f"<b>❓ Причина отмены:</b> <i>{reason}</i>"
    )
    
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                admin_text,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")
            
    return client_text

# Добавляем функцию для очистки предыдущих сообщений
async def clear_previous_messages(state: FSMContext, chat_id: int, bot: Bot) -> None:
    """
    Очищает предыдущие сообщения в процессе записи
    """
    try:
        data = await state.get_data()
        msg_manager: Optional[MessageManager] = data.get("msg_manager")
        
        if msg_manager:
            await msg_manager.delete_messages(chat_id, bot)
            
    except Exception as e:
        log_error(e)
        logger.error(f"Ошибка при очистке сообщений: {e}")