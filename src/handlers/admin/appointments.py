# src/handlers/admin/appointments.py

from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from loguru import logger
import re

from config.settings import settings
from core.utils import NOT_ADMIN_MESSAGE
from database.models import Appointment, TimeSlot
from keyboards.admin.admin import get_admin_inline_keyboard
from states.admin import AdminAppointmentStates
from core.utils.logger import log_error
from core.bot import bot 
from core.utils.time_slots import get_time_slots_view, cancel_appointment, check_and_clear_states

# Словарь для перевода статусов
STATUS_TRANSLATIONS = {
    "PENDING": "Ожидает подтверждения",
    "CONFIRMED": "Подтвержден",
    "COMPLETED": "Исполнен",
    "CANCELLED": "Отменен"
}

# Определяем префиксы для пропуска
skip_callbacks = [
    # Контент - новости
    "content_add_news_",
    "content_delete_news_",
    "content_news_",
    "content_manage_news",
    "content_manage_broadcasts",
    "content_back_to_content",
    "manage_content",
    "edit_news_start_",
    "edit_news_text_",
    "edit_news_photo_",
    "edit_news_title_",
    
    # Контент - рассылки
    "content_manage_broadcasts",
    
    # Общие контент-операции
    "content_back_to_content",
    "manage_content",
    
    # Расписание
    "manage_schedule",
    "view_date_",
    "add_slot_",
    "select_time_",
    "delete_slot_",
    "auto_create_",
    "date_page_",
    "add_appointment_comment_",
    
    # Запросы на расчет стоимости
    "manage_price_requests",
    "respond_price_",
    "template_",
    "archive_price_",
    "edit_price_",
    "price_request_",
    "confirm_archive_",
    "filter_pending_",
    "filter_answered_",
    "archived_price_",
    
    # Услуги
    "add_service",
    "edit_service_",
    "delete_service_",
    "view_service_",
    "edit_field_",
    "manage_services",
    "view_archived_services",
    "process_edit_service_photo",

    # Рассылки
    "broadcast_",  # Общий префикс для всех операций с рассылками
    "broadcast_add",
    "broadcast_view_",
    "broadcast_send_",
    "broadcast_edit_",
    "broadcast_delete_",
    "broadcast_confirm_",
    "broadcast_back_to_content",
    "broadcast_back_to_broadcasts",
    "broadcast_audience_all",
    "broadcast_audience_active",
    "broadcast_cancel",
    
    # Команды
    "cmd_",
    "help_",
    "settings_",
    
    # Базовые операции
    "base_",
    "back_to_admin",
    "exit_admin_panel",
    
    # Слот-машина
    "admin_slot_machine_menu",
    "admin_slot_view_prize_",
    "admin_slot_confirm_",
    "admin_slot_reject_",
    "admin_slot_reject_reason_",
    "admin_slot_stats",
    "admin_slot_prizes_page_",
    "admin_slot_archive_",
    "admin_slot_confirmed_prizes_",
    "admin_slot_used_prizes_",
    "admin_slot_rejected_prizes_",
    "admin_slot_mark_used_",
    "admin_slot_prize_stats"
]

APPOINTMENT_PREFIXES = [
    "view_cancelled_appointments",
    "view_cancelled_appointments_page_",
    "view_all_confirmed",
    "view_new_appointments",
    "view_week_appointments",
    "appointment_details_",
    "confirm_appointment_",
    "cancel_appointment_",
    "add_appointment_comment_",
    "filter_pending",
    "filter_confirmed",
    "refresh_week_appointments"
]

router = Router(name='admin_appointments')
# Добавляем фильтр для админских ID
router.message.filter(F.from_user.id.in_(settings.admin_ids))
router.callback_query.filter(F.from_user.id.in_(settings.admin_ids))

def admin_filter(message: Message | CallbackQuery) -> bool:
    """
    Фильтр для проверки прав администратора
    """
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id
    return user_id in settings.admin_ids

# Регистрируем обработчики состояний в основном роутере
@router.message(AdminAppointmentStates.setting_appointment_price)
async def process_appointment_price(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """
    Обработка установки точной стоимости записи
    """
    logger.info("=================== НАЧАЛО process_appointment_price ===================")
    logger.info(f"User ID: {message.from_user.id}")
    logger.info(f"Текст сообщения: {message.text}")
    
    try:
        # Проверяем, не отмена ли это
        if message.text.lower() in ["отмена", "cancel", "отменить"]:
            logger.info("Пользователь отменил установку цены")
            await message.answer("Установка цены отменена. Возвращаемся к списку записей.")
            await state.clear()
            
            # Возвращаемся к списку записей
            keyboard = get_admin_inline_keyboard()
            await message.answer("Панель управления записями:", reply_markup=keyboard)
            return
            
        # Получаем цену из сообщения
        try:
            # Находим первую последовательность цифр в сообщении
            price_match = re.search(r'\d+', message.text)
            if not price_match:
                logger.warning("Цифры не найдены в сообщении")
                
                # Создаем клавиатуру с возможностью отмены
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ Отмена", callback_data="manage_appointments")]
                ])
                
                await message.answer(
                    "<b>❌ Ошибка!</b>\n\n"
                    "Пожалуйста, введите цену в виде целого числа (например, <code>5000</code>) "
                    "или нажмите <i>отмена</i>:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
                
            price = int(price_match.group())
            logger.info(f"Извлечена цена из сообщения: {message.text} -> {price}")
            
            if price <= 0:
                logger.warning("Цена меньше или равна нулю")
                
                # Создаем клавиатуру с возможностью отмены
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ Отмена", callback_data="manage_appointments")]
                ])
                
                await message.answer(
                    "<b>❌ Ошибка!</b>\n\n"
                    "Цена должна быть <u>положительным числом</u>. "
                    "Попробуйте еще раз или нажмите <i>отмена</i>:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
        except ValueError:
            logger.warning(f"Не удалось преобразовать '{message.text}' в число")
            
            # Создаем клавиатуру с возможностью отмены
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Отмена", callback_data="manage_appointments")]
            ])
            
            await message.answer(
                "<b>❌ Ошибка!</b>\n\n"
                "Пожалуйста, введите цену в виде целого числа (например, <code>5000</code>) "
                "или нажмите <i>отмена</i>:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return

        # Получаем ID записи из состояния
        data = await state.get_data()
        appointment_id = data.get('appointment_id')
        logger.info(f"ID записи из состояния: {appointment_id}")
        
        if not appointment_id:
            logger.error("ID записи не найден в состоянии")
            await message.answer(
                "<b>❌ Системная ошибка</b>\n\n"
                "Произошла ошибка. Начните процесс подтверждения заново.",
                parse_mode="HTML"
            )
            await state.clear()
            return

        # Получаем запись
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
        logger.info(f"Получена запись: {appointment}")

        if not appointment:
            logger.error(f"Запись с ID {appointment_id} не найдена")
            await message.answer(
                "<b>❌ Ошибка!</b>\n\n"
                "Запись не найдена в базе данных",
                parse_mode="HTML"
            )
            await state.clear()
            return

        # Проверяем, создана ли запись на основе запроса расчета стоимости
        is_from_price_request = False
        if appointment.client_comment and "Запись создана на основе запроса расчета стоимости" in appointment.client_comment:
            is_from_price_request = True
            logger.info(f"Запись #{appointment_id} создана на основе запроса расчета стоимости")

        # Обновляем запись
        appointment.status = "CONFIRMED"
        appointment.confirmed_at = datetime.now()
        appointment.final_price = price
        logger.info(f"Обновляем запись: статус={appointment.status}, цена={price}")
        
        # Занимаем следующий час
        next_hour = appointment.time_slot.date + timedelta(hours=1)
        logger.info(f"Ищем следующий слот на {next_hour}")
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
        
        # Добавлен код для блокировки предыдущего часа
        prev_hour = appointment.time_slot.date - timedelta(hours=1)
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
        
        await session.commit()
        logger.info("Изменения сохранены в базе данных")
        
        # Формируем детальное уведомление для клиента
        client_message = (
            "<b>✅ Ваша запись подтверждена!</b>\n\n"
            f"<b>📅 Дата:</b> <code>{appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
            f"<b>💇‍♂️ Услуга:</b> <i>{appointment.service.name}</i>\n"
            f"<b>⏱ Длительность: от </b> <code>{appointment.service.duration}</code> мин.\n"
            f"<b>💰 Стоимость:</b> <code>{price}₽</code>\n"
        )

        # Добавляем комментарий клиента и ответ администратора, если они есть
        # Для записей из запроса расчета стоимости не добавляем эту информацию
        if appointment.client_comment and not is_from_price_request:
            client_message += f"\n<b>💬 Ваш комментарий:</b> <i>{appointment.client_comment}</i>\n"
            if appointment.admin_response:
                client_message += f"<b>↪️ Ответ:</b> <i>{appointment.admin_response}</i>\n"

        client_message += (
            "\n<b>ℹ️ Важная информация:</b>\n"
            "• Пожалуйста, приходите за 5-10 минут до начала записи\n"
            "• Если вам нужно время подумать или стоимость кажется высокой, "
            "вы всегда можете отменить запись, нажав кнопку ниже (или через личный кабинет)\n\n"
            "<b>Ждем вас! 🤗</b>"
        )

        # Создаем клавиатуру с кнопкой отмены
        client_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ Отменить запись",
                callback_data=f"client_cancel_appointment_{appointment.id}"
            )]
        ])
        
        # Отправляем уведомление клиенту
        try:
            await bot.send_message(
                appointment.user.telegram_id,
                client_message,
                reply_markup=client_keyboard,
                parse_mode="HTML"
            )
            logger.info(f"Уведомление о подтверждении отправлено клиенту {appointment.user.full_name}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления клиенту: {e}")
            await message.answer(
                "<b>⚠️ Внимание!</b>\n\n"
                "Запись подтверждена, но не удалось отправить уведомление клиенту",
                parse_mode="HTML"
            )
            await state.clear()
            return

        # Очищаем состояние перед отправкой финального сообщения
        logger.info("Очищаем состояние после установки цены")
        await state.clear()
        
        # Отправляем подтверждение админу и предлагаем вернуться к управлению записями
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Вернуться к управлению записями", callback_data="manage_appointments")]
        ])
        
        await message.answer(
            "<b>✅ Успешно!</b>\n\n"
            "Запись подтверждена и клиент уведомлен",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        logger.info("Отправлено подтверждение администратору")
        
    except Exception as e:
        logger.error(f"Ошибка в process_appointment_price: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при установке цены")
        await state.clear()
    finally:
        logger.info("=================== КОНЕЦ process_appointment_price ===================\n")

def is_appointment_callback(callback: CallbackQuery) -> bool:
    """
    Проверяет, относится ли callback к управлению записями
    """
    return any(callback.data.startswith(prefix) for prefix in APPOINTMENT_PREFIXES)

@router.message(AdminAppointmentStates.adding_appointment_comment)
async def process_admin_comment(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка комментария администратора
    """
    logger.info("=== Сработал обработчик process_admin_comment ===")
    logger.info(f"Текст сообщения: {message.text}")
    
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        appointment_id = data.get('appointment_id')
        logger.info(f"ID записи из состояния: {appointment_id}")
        
        if not appointment_id:
            logger.error("ID записи не найден в состоянии")
            await message.answer("Произошла ошибка. Начните процесс добавления комментария заново.")
            await state.clear()
            return
            
        # Получаем запись с предзагрузкой связанных данных
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
        logger.info(f"Получена запись: {appointment}")
        
        if not appointment:
            logger.error(f"Запись с ID {appointment_id} не найдена")
            await message.answer("Запись не найдена")
            await state.clear()
            return
        
        # Обновляем комментарий
        appointment.admin_comment = message.text
        logger.info(f"Обновляем комментарий записи: {message.text}")
        await session.commit()
        logger.info("Комментарий сохранен в базе данных")
        
        # Отправляем подтверждение
        await message.answer(
            f"<b>✅ Комментарий добавлен к записи #{appointment_id}:</b>\n"
            f"<i>💬 {message.text}</i>",
            parse_mode="HTML"
        )
        
        # Очищаем состояние
        await state.clear()
        logger.info("Состояние очищено")
        
        # Возвращаемся к меню управления записями
        keyboard = [
            [InlineKeyboardButton(
                text="🆕 Новые заявки",
                callback_data="view_new_appointments"
            )],
            [InlineKeyboardButton(
                text="📅 Заявки на неделю",
                callback_data="view_week_appointments"
            )],
            [InlineKeyboardButton(
                text="📋 Все подтвержденные заявки",
                callback_data="view_all_confirmed"
            )],
            [InlineKeyboardButton(
                text="↩️ Назад",
                callback_data="back_to_admin"
            )]
        ]
        
        await message.answer(
            "<b>📝 Управление записями</b>\n\n"
            "<i>Выберите категорию записей для просмотра:</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в process_admin_comment: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при добавлении комментария")
        await state.clear()
    finally:
        logger.info("=== Конец обработчика process_admin_comment ===\n")

@router.message(Command("appointments"))
async def cmd_appointments(message: Message, session: AsyncSession) -> None:
    """
    Показывает меню управления записями
    """
    if not admin_filter(message):
        await message.answer(NOT_ADMIN_MESSAGE)
        return
        
    try:
        # Создаем клавиатуру с категориями
        keyboard = [
            [InlineKeyboardButton(
                text="🆕 Новые заявки",
                callback_data="view_new_appointments"
            )],
            [InlineKeyboardButton(
                text="📅 Заявки на неделю",
                callback_data="view_week_appointments"
            )],
            [InlineKeyboardButton(
                text="📋 Все подтвержденные заявки",
                callback_data="view_all_confirmed"
            )],
            [InlineKeyboardButton(
                text="↩️ Назад",
                callback_data="back_to_admin"
            )]
        ]
        
        await message.answer(
            "<b>📝 Управление записями</b>\n\n"
            "<i>Выберите категорию записей для просмотра:</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await message.answer(
            "Произошла ошибка при загрузке записей",
            reply_markup=get_admin_inline_keyboard()
        )

# Добавляем функцию для создания уведомления администратору
async def send_admin_notification(bot, admin_id: int, appointment) -> None:
    """
    Отправляет уведомление администратору о новой записи с кнопкой просмотра
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🆕 Посмотреть новые заявки",
            callback_data="view_new_appointments"
        )]
    ])
    
    notification_text = (
        "<b>🔔 Новая запись!</b>\n\n"
        f"<b>👤 Клиент:</b> <code>{appointment.user.full_name}</code>\n"
        f"<b>📅 Дата и время:</b> <code>{appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
        f"<b>💇‍♂️ Услуга:</b> <code>{appointment.service.name}</code>\n"
        f"<b>🚗 Автомобиль:</b> <code>{appointment.car_brand} {appointment.car_model} ({appointment.car_year})</code>\n"
        f"<b>💬 Комментарий:</b> <code>{appointment.client_comment or 'Нет'}</code>"
    )
    
    try:
        await bot.send_message(
            admin_id,
            notification_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления администратору: {e}")

@router.callback_query(F.data.startswith("confirm_appointment_"))
async def confirm_appointment(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Подтверждение записи с дополнительными проверками и уведомлениями
    """
    try:
        # Сразу отвечаем на callback
        await callback.answer()
        
        # Проверяем состояние перед установкой нового
        old_state = await state.get_state()
        old_data = await state.get_data()
        logger.info(f"Старое состояние: {old_state}")
        logger.info(f"Старые данные: {old_data}")
        
        # Очищаем старое состояние если есть
        if old_state:
            await state.clear()
        
        appointment_id = int(callback.data.split("_")[2])
        logger.info(f"ID записи: {appointment_id}")
        
        # Получаем запись с предзагрузкой связанных данных
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
            await callback.answer("Запись не найдена")
            return
        
        # Проверяем, не устарела ли запись
        if appointment.time_slot.date < datetime.now():
            await callback.answer("❌ Невозможно подтвердить прошедшую запись")
            return
        
        # Проверяем, не подтверждена ли уже запись
        if appointment.status == "CONFIRMED":
            await callback.answer("❌ Запись уже подтверждена")
            return
        
        # Проверяем, не отменена ли запись
        if appointment.status == "CANCELLED":
            await callback.answer("❌ Невозможно подтвердить отмененную запись")
            return
        
        # Проверяем, нет ли других подтвержденных записей на это время
        overlapping_result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                TimeSlot.date == appointment.time_slot.date,
                Appointment.status == "CONFIRMED",
                Appointment.id != appointment_id
            )
        )
        if overlapping_result.scalar_one_or_none():
            await callback.answer("❌ На это время уже есть подтвержденная запись")
            return
        
        # Определяем предварительную стоимость
        preliminary_price = appointment.service.price
        
        # Проверяем, есть ли окончательная цена из запроса расчета стоимости
        if appointment.final_price:
            preliminary_price = appointment.final_price
        # Если комментарий содержит ответ менеджера с ценой, извлекаем цену
        elif appointment.client_comment and "Ответ менеджера:" in appointment.client_comment:
            # Ищем строку с ответом менеджера и пытаемся извлечь цену
            for line in appointment.client_comment.split('\n'):
                if "Ответ менеджера:" in line:
                    # Сначала ищем точную цену в формате "составит X₽"
                    exact_price_match = re.search(r'составит (\d+)₽', line)
                    if exact_price_match:
                        preliminary_price = int(exact_price_match.group(1))
                        break
                    # Если точной цены нет, ищем минимальную цену из диапазона "от X₽ до Y₽"
                    range_price_match = re.search(r'составит от (\d+)₽', line)
                    if range_price_match:
                        preliminary_price = int(range_price_match.group(1))
                        break
        
        # Проверяем, создана ли запись на основе запроса расчета стоимости
        is_from_price_request = False
        if appointment.client_comment and "Запись создана на основе запроса расчета стоимости" in appointment.client_comment:
            is_from_price_request = True
            logger.info(f"Запись #{appointment_id} создана на основе запроса расчета стоимости")
        
        # В первую очередь запрашиваем цену, если запись из запроса расчета стоимости
        if is_from_price_request:
            # Сразу переходим к установке цены
            await callback.message.edit_text(
                f"<b>💰 Установите точную стоимость для записи #{appointment.id}:</b>\n\n"
                f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
                f"<b>📱 Телефон:</b> {appointment.user.phone_number or 'Не указан'}\n"
                f"<b>📅 Дата:</b> {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
                f"<b>💇‍♂️ Услуга:</b> {appointment.service.name}\n"
                f"<b>🚗 Автомобиль:</b> {appointment.car_brand} {appointment.car_model} ({appointment.car_year})\n"
                f"<b>💬 Комментарий:</b> {appointment.client_comment or 'Нет'}\n\n"
                f"<b>Предварительная стоимость:</b> {preliminary_price}₽\n\n"
                "Введите точную стоимость в рублях:",
                reply_markup=None,
                parse_mode="HTML"
            )
            
            await state.set_state(AdminAppointmentStates.setting_appointment_price)
            await state.update_data(appointment_id=appointment_id)
            return
        
        # Если есть комментарий клиента и это НЕ запрос расчета стоимости,
        # запрашиваем ответ администратора с вариантами ответов
        if appointment.client_comment:
            # Создаем клавиатуру с быстрыми ответами
            keyboard_buttons = [
                [
                    InlineKeyboardButton(
                        text="👍 Принято",
                        callback_data=f"quick_response_{appointment_id}_accepted"
                    ),
                    InlineKeyboardButton(
                        text="✅ Всё хорошо",
                        callback_data=f"quick_response_{appointment_id}_ok"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⌛ Скоро свяжемся",
                        callback_data=f"quick_response_{appointment_id}_contact_soon"
                    ),
                    InlineKeyboardButton(
                        text="📞 Позвоним",
                        callback_data=f"quick_response_{appointment_id}_will_call"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💰 Сразу к цене",
                        callback_data=f"quick_response_{appointment_id}_skip_to_price"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✏️ Свой ответ",
                        callback_data=f"quick_response_{appointment_id}_custom"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ Отмена",
                        callback_data="manage_appointments"
                    )
                ]
            ]
            
            # Формируем текст сообщения
            message_text = f"<b>💬 Ответьте на комментарий клиента для записи #{appointment.id}:</b>\n\n"
            message_text += f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            message_text += f"<b>💭 Комментарий клиента:</b> {appointment.client_comment}\n\n"
            
            # Если у записи уже есть сохраненный ответ администратора, показываем его
            if appointment.admin_response:
                message_text += f"<b>⚠️ Предыдущий ответ:</b> {appointment.admin_response}\n\n"
                
                # Добавляем кнопку для использования предыдущего ответа
                keyboard_buttons.insert(3, [
                    InlineKeyboardButton(
                        text="♻️ Использовать предыдущий ответ",
                        callback_data=f"quick_response_{appointment_id}_use_previous"
                    )
                ])
            
            message_text += "<b>Выберите быстрый ответ или введите свой:</b>"
            
            quick_replies_keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await callback.message.edit_text(
                message_text,
                reply_markup=quick_replies_keyboard,
                parse_mode="HTML"
            )
            await state.set_state(AdminAppointmentStates.setting_admin_response)
            await state.update_data(appointment_id=appointment_id)
            return
            
        # Если нет комментария клиента, сразу переходим к установке цены
        await callback.message.edit_text(
            f"<b>💰 Установите точную стоимость для записи <code>#{appointment.id}</code>:</b>\n\n"
            f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            f"<b>📱 Телефон:</b> <code>{appointment.user.phone_number or 'Не указан'}</code>\n"
            f"<b>📅 Дата:</b> <code>{appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
            f"<b>💇‍♂️ Услуга:</b> <code>{appointment.service.name}</code>\n"
            f"<b>🚗 Автомобиль:</b> <code>{appointment.car_brand} {appointment.car_model} ({appointment.car_year})</code>\n"
            f"<b>💬 Комментарий:</b> <i>{appointment.client_comment or 'Нет'}</i>\n\n"
            f"<b>Предварительная стоимость:</b> <code>{preliminary_price}₽</code>\n\n"
            "<b>Введите точную стоимость в рублях:</b>",
            reply_markup=None,
            parse_mode="HTML"
        )
        
        await state.set_state(AdminAppointmentStates.setting_appointment_price)
        await state.update_data(appointment_id=appointment_id)
        
        return

    except Exception as e:
        logger.error(f"Ошибка в confirm_appointment: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при подтверждении записи")
        await callback.message.edit_text(
            "Произошла ошибка при подтверждении записи",
            reply_markup=get_admin_inline_keyboard()
        )

@router.message(AdminAppointmentStates.setting_admin_response)
async def process_admin_response(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка ответа администратора на комментарий клиента
    """
    logger.info("=== Начало process_admin_response ===")
    try:
        # Проверяем, не отмена ли это
        if message.text.lower() in ["отмена", "cancel", "отменить"]:
            logger.info("Пользователь отменил ввод ответа")
            await message.answer("Ввод ответа отменен. Возвращаемся к списку записей.")
            await state.clear()
            
            # Возвращаемся к списку записей
            keyboard = get_admin_inline_keyboard()
            await message.answer("Панель управления записями:", reply_markup=keyboard)
            return
            
        # Получаем данные из состояния
        data = await state.get_data()
        appointment_id = data.get('appointment_id')
        logger.info(f"ID записи из состояния: {appointment_id}")
        
        if not appointment_id:
            logger.error("ID записи не найден в состоянии")
            await message.answer("Произошла ошибка. Начните процесс подтверждения заново.")
            await state.clear()
            return
            
        # Получаем запись с предзагрузкой связанных данных
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
        logger.info(f"Получена запись: {appointment}")
        
        if not appointment:
            logger.error(f"Запись с ID {appointment_id} не найдена")
            await message.answer("Запись не найдена")
            await state.clear()
            return
        
        # Сохраняем ответ администратора
        appointment.admin_response = message.text
        logger.info(f"Сохраняем ответ администратора: {message.text}")
        await session.commit()
        logger.info("Ответ администратора сохранен в базе данных")
        
        # Определяем предварительную стоимость
        preliminary_price = appointment.service.price
        
        # Проверяем, есть ли окончательная цена из запроса расчета стоимости
        if appointment.final_price:
            preliminary_price = appointment.final_price
        # Если комментарий содержит ответ менеджера с ценой, извлекаем цену
        elif appointment.client_comment and "Ответ менеджера:" in appointment.client_comment:
            # Ищем строку с ответом менеджера и пытаемся извлечь цену
            for line in appointment.client_comment.split('\n'):
                if "Ответ менеджера:" in line:
                    # Сначала ищем точную цену в формате "составит X₽"
                    exact_price_match = re.search(r'составит (\d+)₽', line)
                    if exact_price_match:
                        preliminary_price = int(exact_price_match.group(1))
                        break
                    # Если точной цены нет, ищем минимальную цену из диапазона "от X₽ до Y₽"
                    range_price_match = re.search(r'составит от (\d+)₽', line)
                    if range_price_match:
                        preliminary_price = int(range_price_match.group(1))
                        break
        
        # Создаем клавиатуру с возможностью отмены
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Отмена", callback_data="manage_appointments")]
        ])
        
        # Переходим к установке цены
        await message.answer(
            f"<b>💰 Установите точную стоимость для записи <code>#{appointment.id}</code>:</b>\n\n"
            f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            f"<b>📱 Телефон:</b> <code>{appointment.user.phone_number or 'Не указан'}</code>\n"
            f"<b>📅 Дата:</b> <code>{appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
            f"<b>💇‍♂️ Услуга:</b> <code>{appointment.service.name}</code>\n"
            f"<b>🚗 Автомобиль:</b> <code>{appointment.car_brand} {appointment.car_model} ({appointment.car_year})</code>\n"
            f"<b>💬 Комментарий клиента:</b> <i>{appointment.client_comment}</i>\n"
            f"<b>↪️ Ваш ответ:</b> {appointment.admin_response}\n\n"
            f"<b>Предварительная стоимость:</b> <code>{preliminary_price}₽</code>\n\n"
            "Введите точную стоимость в рублях или нажмите отмена:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Устанавливаем новое состояние
        await state.set_state(AdminAppointmentStates.setting_appointment_price)
        await state.update_data(appointment_id=appointment_id)
        logger.info("Переход к установке цены выполнен")
        
    except Exception as e:
        logger.error(f"Ошибка в process_admin_response: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при сохранении ответа")
        await state.clear()
    finally:
        logger.info("=== Конец process_admin_response ===\n")

@router.callback_query(F.data.startswith("cancel_appointment_"))
async def cancel_appointment_handler(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Отмена записи
    """
    try:
        # Сразу отвечаем на callback
        await callback.answer()
        
        # Проверяем и очищаем состояния
        await check_and_clear_states(state)
        
        appointment_id = int(callback.data.split("_")[2])
        logger.info(f"Отмена записи {appointment_id}")
        
        # Получаем запись с предзагрузкой связанных данных
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
            logger.error(f"Запись {appointment_id} не найдена")
            await callback.answer("Запись не найдена!")
            return

        # Сохраняем ID записи в состояние
        await state.update_data(appointment_id=appointment_id)
        await state.set_state(AdminAppointmentStates.cancelling_appointment)

        # Создаем клавиатуру для отмены
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ Отменить без комментария",
                callback_data=f"cancel_without_comment_{appointment_id}"
            )],
            [InlineKeyboardButton(
                text="↩️ Назад",
                callback_data="manage_appointments"
            )]
        ])

        # Формируем сообщение с информацией о записи
        message_text = (
            f"<b>❌ Отмена записи <code>#{appointment.id}</code>:</b>\n\n"
            f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            f"<b>📱 Телефон:</b> <code>{appointment.user.phone_number or 'Не указан'}</code>\n"
            f"<b>📅 Дата:</b> <code>{appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
            f"<b>💇‍♂️ Услуга:</b> <code>{appointment.service.name}</code>\n"
            f"<b>🚗 Автомобиль:</b> <code>{appointment.car_brand} {appointment.car_model} ({appointment.car_year})</code>\n"
            f"<b>💰 Стоимость:</b> <code>{appointment.service.price}₽</code>\n\n"
            "Введите причину отмены записи или нажмите кнопку для отмены без комментария:"
        )

        await callback.message.edit_text(
            message_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отмене записи: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при отмене записи")
        await callback.message.edit_text(
            "Произошла ошибка при отмене записи",
            reply_markup=get_admin_inline_keyboard()
        )

@router.message(AdminAppointmentStates.cancelling_appointment)
async def process_cancel_reason(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка причины отмены записи
    """
    try:
        data = await state.get_data()
        appointment_id = data.get('appointment_id')
        
        if not appointment_id:
            await message.answer("Произошла ошибка. Начните процесс отмены заново.")
            await state.clear()
            return

        # Получаем запись
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
            await message.answer("Запись не найдена")
            await state.clear()
            return

        # Отменяем запись
        await cancel_appointment(appointment, message.text, session)
        
        # Очищаем состояние
        await state.clear()
        
        # Возвращаемся к просмотру слотов на дату
        text, keyboard = await get_time_slots_view(appointment.time_slot.date, session)
        
        # Отправляем сообщение об успешной отмене
        await message.answer(
            "<b>✅ Запись</b> <code>#{}</code> <b>отменена</b>\n"
            "<b>Причина:</b> <i>{}</i>".format(appointment_id, message.text),
            parse_mode="HTML"
        )
        
        # Показываем обновленное расписание
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке причины отмены: {e}", exc_info=True)
        await message.answer("Произошла ошибка при отмене записи")
        await state.clear()

@router.callback_query(F.data.startswith("cancel_without_comment_"))
async def cancel_without_comment(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Отмена записи без комментария
    """
    try:
        appointment_id = int(callback.data.split("_")[3])
        
        # Получаем запись
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
            await callback.answer("Запись не найдена")
            return
        
        # Отменяем запись
        await cancel_appointment(appointment, "Отмена без комментария", session)
        
        # Очищаем состояние
        await state.clear()
        
        await callback.answer("✅ Запись отменена!")
        
        # Возвращаемся к списку записей
        await view_new_appointments(callback, session)
        
    except Exception as e:
        logger.error(f"Ошибка при отмене записи без комментария: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при отмене записи")
        await callback.message.edit_text(
            "Произошла ошибка при отмене записи",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "manage_appointments")
async def manage_appointments(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Управление записями: разделение на категории
    """
    try:
        # Сразу отвечаем на callback
        await callback.answer()
        
        logger.info(f"Администратор {callback.from_user.id} открыл управление записями")
        
        # Получаем статистику по активным записям (будущие даты)
        active_result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(TimeSlot.date >= datetime.now())
        )
        active_appointments = active_result.scalars().all()
        
        # Получаем статистику по выполненным записям (прошлые даты)
        completed_result = await session.execute(
            select(Appointment)
            .where(Appointment.status == "COMPLETED")
        )
        completed_appointments = completed_result.scalars().all()
        
        # Получаем статистику по отмененным записям (все даты)
        cancelled_result = await session.execute(
            select(Appointment)
            .where(Appointment.status == "CANCELLED")
        )
        cancelled_appointments = cancelled_result.scalars().all()
        
        # Подсчитываем количество записей по статусам
        stats = {
            "PENDING": 0,
            "CONFIRMED": 0,
            "CANCELLED": len(cancelled_appointments),
            "COMPLETED": len(completed_appointments)
        }
        
        # Считаем только активные записи для PENDING и CONFIRMED
        for app in active_appointments:
            if app.status in ["PENDING", "CONFIRMED"]:
                stats[app.status] += 1
        
        keyboard = [
            [InlineKeyboardButton(
                text="📝 Редактировать запись",
                callback_data="edit_appointment"
            )],
            [InlineKeyboardButton(
                text=f"🆕 Новые заявки ({stats['PENDING']})",
                callback_data="view_new_appointments"
            )],
            [InlineKeyboardButton(
                text=f"📅 Заявки на неделю ({stats['PENDING'] + stats['CONFIRMED']})",
                callback_data="view_week_appointments"
            )],
            [InlineKeyboardButton(
                text=f"✅ Подтвержденные ({stats['CONFIRMED']})",
                callback_data="view_all_confirmed"
            )],
            [InlineKeyboardButton(
                text=f"❌ Отмененные ({stats['CANCELLED']})",
                callback_data="view_cancelled_appointments"
            )],
            [InlineKeyboardButton(
                text=f"🏁 Выполненные ({stats['COMPLETED']})",
                callback_data="view_completed_orders"
            )],
            [InlineKeyboardButton(
                text="↩️ Назад",
                callback_data="back_to_admin"
            )]
        ]
        
        text = (
            "<b>📝 Управление записями</b>\n\n"
            f"🆕 <i>Новых:</i> <b>{stats['PENDING']}</b>\n"
            f"✅ <i>Подтверждено:</i> <b>{stats['CONFIRMED']}</b>\n" 
            f"❌ <i>Отменено:</i> <b>{stats['CANCELLED']}</b>\n"
            f"🏁 <i>Выполнено:</i> <b>{stats['COMPLETED']}</b>\n\n"
            "<i>Выберите категорию записей для просмотра:</i>"
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке записей",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "edit_appointment")
async def start_edit_appointment(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начало процесса редактирования записи
    """
    try:
        await callback.answer()
        await state.set_state(AdminAppointmentStates.entering_appointment_id)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="manage_appointments")]
        ])
        
        await callback.message.edit_text(
            "📝 Редактирование записи\n\n"
            "Введите ID записи, которую хотите отредактировать:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при начале редактирования записи: {e}")
        await callback.message.edit_text(
            "Произошла ошибка при начале редактирования записи",
            reply_markup=get_admin_inline_keyboard()
        )

@router.message(AdminAppointmentStates.entering_appointment_id)
async def process_appointment_id(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка введенного ID записи
    """
    try:
        appointment_id = int(message.text)
        
        # Получаем запись из базы данных с загрузкой связанных данных
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
            await message.answer(
                "❌ Запись с указанным ID не найдена.\n"
                "Попробуйте еще раз или вернитесь назад.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="manage_appointments")]
                ])
            )
            return
        
        # Сохраняем ID записи в состоянии
        await state.update_data(appointment_id=appointment_id)
        await state.set_state(AdminAppointmentStates.editing_appointment)
        
        # Формируем текст с информацией о записи
        car_info = f"{appointment.car_brand} {appointment.car_model} ({appointment.car_year})" if appointment.car_brand else "Не указано"
        
        appointment_info = (
            f"<b>📋 Информация о записи #{appointment_id}:</b>\n\n"
            f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            f"<b>📱 Телефон:</b> {appointment.user.phone_number or 'Не указан'}\n"
            f"<b>🚗 Автомобиль:</b> {car_info}\n"
            f"<b>💰 Цена:</b> {appointment.final_price if appointment.final_price else 'Не указана'}₽\n"
            f"<b>💬 Комментарий клиента:</b> {appointment.client_comment if appointment.client_comment else 'Нет'}\n"
            f"<b>📝 Комментарий администратора:</b> {appointment.admin_comment if appointment.admin_comment else 'Нет'}\n"
            f"<b>📅 Дата:</b> {appointment.time_slot.date.strftime('%d.%m.%Y')}\n"
            f"<b>⏰ Время:</b> {appointment.time_slot.date.strftime('%H:%M')}\n"
            f"<b>📊 Статус:</b> {STATUS_TRANSLATIONS.get(appointment.status, appointment.status)}"
        )
        
        # Клавиатура для выбора поля для редактирования
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚗 Марка автомобиля", callback_data="edit_field_car_brand")],
            [InlineKeyboardButton(text="🚙 Модель автомобиля", callback_data="edit_field_car_model")],
            [InlineKeyboardButton(text="📅 Год выпуска", callback_data="edit_field_car_year")],
            [InlineKeyboardButton(text="💰 Цена", callback_data="edit_field_price")],
            [InlineKeyboardButton(text="💬 Комментарий клиента", callback_data="edit_field_client_comment")],
            [InlineKeyboardButton(text="📝 Комментарий администратора", callback_data="edit_field_admin_comment")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="manage_appointments")]
        ])
        
        await message.answer(
            appointment_info,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректный номер записи (только цифры).\n"
            "Попробуйте еще раз или вернитесь назад.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="manage_appointments")]
            ])
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке ID записи: {e}")
        await message.answer(
            "Произошла ошибка при обработке ID записи",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("edit_field_"))
async def edit_appointment_field(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка выбора поля для редактирования
    """
    try:
        field = callback.data.replace("edit_field_", "")
        await state.update_data(editing_field=field)
        await state.set_state(AdminAppointmentStates.editing_appointment_field)
        
        field_names = {
            "car_brand": "марку автомобиля",
            "car_model": "модель автомобиля",
            "car_year": "год выпуска",
            "price": "цену",
            "client_comment": "комментарий клиента",
            "admin_comment": "комментарий администратора"
        }
        
        await callback.message.edit_text(
            f"📝 Введите новое значение для поля '{field_names[field]}':",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="edit_appointment")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Ошибка при выборе поля для редактирования: {e}")
        await callback.message.edit_text(
            "Произошла ошибка при выборе поля для редактирования",
            reply_markup=get_admin_inline_keyboard()
        )

@router.message(AdminAppointmentStates.editing_appointment_field)
async def save_edited_field(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Сохранение отредактированного значения поля
    """
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        appointment_id = data.get("appointment_id")
        field = data.get("editing_field")
        
        # Получаем запись из базы данных
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
            await message.answer("❌ Запись не найдена")
            await state.clear()
            return
        
        # Обновляем соответствующее поле
        if field == "car_brand":
            appointment.car_brand = message.text
        elif field == "car_model":
            appointment.car_model = message.text
        elif field == "car_year":
            if not message.text.isdigit() or len(message.text) != 4:
                await message.answer(
                    "❌ Пожалуйста, введите корректный год (4 цифры).\n"
                    "Попробуйте еще раз или вернитесь назад.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="edit_appointment")]
                    ])
                )
                return
            appointment.car_year = message.text
        elif field == "price":
            try:
                appointment.final_price = int(message.text)
            except ValueError:
                await message.answer(
                    "❌ Пожалуйста, введите корректную цену (целое число).\n"
                    "Попробуйте еще раз или вернитесь назад.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="edit_appointment")]
                    ])
                )
                return
        elif field == "client_comment":
            appointment.client_comment = message.text
        elif field == "admin_comment":
            appointment.admin_comment = message.text
        
        # Сохраняем изменения
        await session.commit()
        
        # Формируем обновленную информацию о записи
        car_info = f"{appointment.car_brand} {appointment.car_model} ({appointment.car_year})" if appointment.car_brand else "Не указано"
        
        updated_info = (
            "<b>✅ Информация успешно обновлена!</b>\n\n"
            f"<b>📋 Текущая информация о записи #{appointment_id}:</b>\n\n"
            f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            f"<b>📱 Телефон:</b> {appointment.user.phone_number or 'Не указан'}\n" 
            f"<b>🚗 Автомобиль:</b> {car_info}\n"
            f"<b>💰 Цена:</b> {appointment.final_price if appointment.final_price else 'Не указана'}₽\n"
            f"<b>💬 Комментарий клиента:</b> {appointment.client_comment if appointment.client_comment else 'Нет'}\n"
            f"<b>📝 Комментарий администратора:</b> {appointment.admin_comment if appointment.admin_comment else 'Нет'}\n"
            f"<b>📅 Дата:</b> {appointment.time_slot.date.strftime('%d.%m.%Y')}\n"
            f"<b>⏰ Время:</b> {appointment.time_slot.date.strftime('%H:%M')}\n"
            f"<b>📊 Статус:</b> {STATUS_TRANSLATIONS.get(appointment.status, appointment.status)}"
        )
        
        await message.answer(
            updated_info,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Продолжить редактирование", callback_data="edit_appointment")],
                [InlineKeyboardButton(text="◀️ Вернуться к управлению", callback_data="manage_appointments")]
            ])
        )
        
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении отредактированного поля: {e}")
        await message.answer(
            "Произошла ошибка при сохранении изменений",
            reply_markup=get_admin_inline_keyboard()
        )
        await state.clear()

@router.callback_query(F.data == "view_completed_orders")
async def view_completed_orders(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Просмотр выполненных заказов с группировкой по месяцам
    """
    try:
        await callback.answer()
        
        # Получаем все выполненные записи
        result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(Appointment.status == "COMPLETED")
            .order_by(TimeSlot.date.desc())
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointments = result.scalars().all()
        
        if not appointments:
            keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="manage_appointments")]]
            await callback.message.edit_text(
                "🔍 Выполненных заказов пока нет",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            return
        
        # Группируем записи по месяцам
        grouped = {}
        total_revenue = 0
        
        for app in appointments:
            month_str = app.time_slot.date.strftime('%B %Y')  # Например, "February 2025"
            if month_str not in grouped:
                grouped[month_str] = {
                    'appointments': [],
                    'revenue': 0,
                    'count': 0
                }
            grouped[month_str]['appointments'].append(app)
            grouped[month_str]['revenue'] += app.final_price or app.service.price
            grouped[month_str]['count'] += 1
            total_revenue += app.final_price or app.service.price
        
        text = f"✅ Выполненные заказы\n💰 Общая выручка: {total_revenue}₽\n\n"
        keyboard = []
        
        # Показываем статистику по месяцам
        for month, data in grouped.items():
            text += (
                f"<b>📅 {month}:</b>\n"
                f"<i>📊 Количество:</i> <b>{data['count']}</b>\n"
                f"<i>💰 Выручка:</i> <b>{data['revenue']}₽</b>\n"
                "<i>-------------------</i>\n"
            )
            
            # Добавляем кнопку для просмотра деталей месяца
            keyboard.append([
                InlineKeyboardButton(
                    text=f"📋 {month} ({data['count']} заказов)",
                    callback_data=f"view_month_details_{month.replace(' ', '_')}"
                )
            ])
        
        # Добавляем кнопку возврата
        keyboard.append([
            InlineKeyboardButton(text="↩️ Назад", callback_data="manage_appointments")
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре выполненных заказов: {e}", exc_info=True)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка!</b>\n\n"
            "Произошла ошибка при загрузке выполненных заказов",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("view_month_details_"))
async def view_month_details(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Просмотр деталей выполненных заказов за конкретный месяц
    """
    try:
        await callback.answer()
        
        # Получаем месяц и год из callback data
        month_year = callback.data.split("_", 3)[3].replace("_", " ")
        month_date = datetime.strptime(month_year, "%B %Y")
        next_month = (month_date.replace(day=1) + timedelta(days=32)).replace(day=1)
        
        # Получаем все выполненные записи за указанный месяц
        result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                Appointment.status == "COMPLETED",
                TimeSlot.date >= month_date.replace(day=1),
                TimeSlot.date < next_month
            )
            .order_by(TimeSlot.date)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointments = result.scalars().all()
        
        # Подсчитываем статистику
        total_revenue = sum(app.final_price or app.service.price for app in appointments)
        
        text = (
            f"<b>📅 Статистика за {month_year}</b>\n"
            f"<i>📊 Всего заказов:</i> <b>{len(appointments)}</b>\n"
            f"<i>💰 Общая выручка:</i> <b>{total_revenue}₽</b>\n\n"
            "<b>📋 Список заказов:</b>\n\n"
        )
        
        keyboard = []
        
        # Группируем по дням для компактности
        grouped_by_day = {}
        for app in appointments:
            day_str = app.time_slot.date.strftime('%d.%m.%Y')
            if day_str not in grouped_by_day:
                grouped_by_day[day_str] = []
            grouped_by_day[day_str].append(app)
        
        for day, day_appointments in grouped_by_day.items():
            text += f"<b>📅 {day}:</b>\n"
            day_revenue = 0
            
            for app in day_appointments:
                price = app.final_price or app.service.price
                day_revenue += price
                # Добавляем отображение оценки, если она есть
                rating_display = f" ⭐ {app.rating}/5" if app.rating else ""
                text += (
                    f"• <i>{app.time_slot.date.strftime('%H:%M')}</i> "
                    f"<b>#{app.id}</b> <i>{app.service.name}</i> • <b>{price}₽</b>{rating_display}\n"
                )
            
            text += f"<i>💰 Выручка за день:</i> <b>{day_revenue}₽</b>\n\n"
        
        # Добавляем кнопку возврата
        keyboard.append([
            InlineKeyboardButton(text="↩️ Назад к статистике", callback_data="view_completed_orders")
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре деталей месяца: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке деталей",
            reply_markup=get_admin_inline_keyboard()
        )

def group_appointments_by_date(appointments):
    """
    Группировка записей по датам
    """
    grouped = {}
    for app in appointments:
        date_str = app.time_slot.date.strftime('%d.%m.%Y')
        if date_str not in grouped:
            grouped[date_str] = []
        grouped[date_str].append(app)
    return grouped

@router.callback_query(F.data == "view_new_appointments")
async def view_new_appointments(callback: CallbackQuery, session: AsyncSession, page: int = 1) -> None:
    """
    Просмотр новых (ожидающих подтверждения) записей
    """
    try:
        logger.info("=== Сработал обработчик view_new_appointments ===")
        # Сразу отвечаем на callback
        await callback.answer()
        
        # Получаем все новые записи с подробным логированием
        logger.info("Выполняем запрос к БД для получения записей...")
        
        # Получаем все записи для проверки
        check_query = select(Appointment)
        check_result = await session.execute(check_query)
        all_appointments = check_result.scalars().all()
        logger.info(f"Всего записей в таблице Appointment: {len(all_appointments)}")
        
        # Проверяем статусы всех записей
        statuses = {}
        for app in all_appointments:
            if app.status not in statuses:
                statuses[app.status] = 0
            statuses[app.status] += 1
        logger.info(f"Распределение записей по статусам: {statuses}")
        
        # Теперь выполним основной запрос для получения только новых записей
        current_datetime = datetime.now()
        query = (
            select(Appointment)
            .join(TimeSlot)
            .where(
                TimeSlot.date >= current_datetime,
                Appointment.status == "PENDING"  # Только ожидающие подтверждения
            )
            .order_by(TimeSlot.date)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        logger.info(f"SQL Query: {query}")
        
        result = await session.execute(query)
        appointments = result.scalars().all()
        logger.info(f"Получено новых записей из БД: {len(appointments)}")

        if not appointments:
            logger.info("Новые записи не найдены, отправляем сообщение об отсутствии записей")
            keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="manage_appointments")]]
            await callback.message.edit_text(
                "🔍 Новых заявок пока нет",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            return
        
        # Группируем записи по датам
        logger.info("Начинаем группировку записей по датам")
        grouped_appointments = {}
        for app in appointments:
            date_str = app.time_slot.date.strftime('%d.%m.%Y')
            if date_str not in grouped_appointments:
                grouped_appointments[date_str] = []
            grouped_appointments[date_str].append(app)
        logger.info(f"Сгруппировано по датам: {len(grouped_appointments)} дат")
        
        dates = list(grouped_appointments.keys())
        
        # Пагинация дат
        DATES_PER_PAGE = 6
        total_pages = (len(dates) + DATES_PER_PAGE - 1) // DATES_PER_PAGE
        start_idx = (page - 1) * DATES_PER_PAGE
        end_idx = start_idx + DATES_PER_PAGE
        current_dates = dates[start_idx:end_idx]
        
        text = "<b>🆕 Новые заявки:</b>\n\n"
        keyboard = []
        
        for date in current_dates:
            text += f"\n📅 <b>{date}</b> • <code>#{', #'.join(str(app.id) for app in grouped_appointments[date])}</code>\n\n"
            
            for app in grouped_appointments[date]:
                # Определяем цену для отображения
                price_text = f"<code>{app.final_price}₽</code>" if app.final_price else f"от <code>{app.service.price}₽</code>"
                
                text += (
                    f"<b>ЗАПИСЬ #{app.id}</b>\n"
                    f"Клиент: <code>{app.user.full_name}</code>\n"
                    f"Телефон: <code>{app.user.phone_number or '—'}</code>\n"
                    f"Время: <code>{app.time_slot.date.strftime('%H:%M')}</code>\n"
                    f"Услуга: <code>{app.service.name}</code>\n"
                    f"Автомобиль: <code>{app.car_brand} {app.car_model} ({app.car_year})</code>\n"
                    f"Стоимость: {price_text}\n"
                    f"Статус: <code>{STATUS_TRANSLATIONS[app.status]}</code>\n"
                )
                
                if app.client_comment:
                    text += f"Комментарий клиента: <code>{app.client_comment}</code>\n"
                if app.admin_response:
                    text += f"Ответ администратора: <code>{app.admin_response}</code>\n"
                if app.admin_comment:
                    text += f"Комментарий для админов: <code>{app.admin_comment}</code>\n"
                
                text += "\n"
            
                # Кнопки действий для каждой записи
                keyboard.extend([
                    [
                        InlineKeyboardButton(
                            text=f"✅ Подтвердить #{app.id}",
                            callback_data=f"confirm_appointment_{app.id}"
                        ),
                        InlineKeyboardButton(
                            text=f"❌ Отменить #{app.id}",
                            callback_data=f"cancel_appointment_{app.id}"
                        )
                    ],
                    [InlineKeyboardButton(
                        text=f"💬 Комментарий #{app.id}",
                        callback_data=f"add_appointment_comment_{app.id}"
                    )]
                ])
            text += "━━━━━━━━━━━━━━━━━━━━\n"
        
        # Добавляем кнопки пагинации
        pagination_buttons = []
        if page > 1:
            pagination_buttons.append(InlineKeyboardButton(
                text="⬅️",
                callback_data=f"new_appointments_page_{page-1}"
            ))
        if page < total_pages:
            pagination_buttons.append(InlineKeyboardButton(
                text="➡️",
                callback_data=f"new_appointments_page_{page+1}"
            ))
        if pagination_buttons:
            keyboard.append(pagination_buttons)
        
        # Кнопка возврата
        keyboard.append([InlineKeyboardButton(
            text="↩️ Назад",
            callback_data="manage_appointments"
        )])
        
        logger.info("Отправляем сообщение с записями")
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        logger.info("=== Запись отправлена ===")
    except Exception as e:
        logger.error(f"Ошибка в view_new_appointments: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке новых заявок",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("new_appointments_page_"))
async def handle_new_appointments_pagination(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Обработка пагинации для новых записей
    """
    try:
        # Сразу отвечаем на callback
        await callback.answer()
        
        page = int(callback.data.split("_")[-1])
        await view_new_appointments(callback, session, page)
    except ValueError as e:
        logger.error(f"Ошибка при получении номера страницы: {e}")
        await callback.answer("Произошла ошибка при навигации", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка в handle_new_appointments_pagination: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке записей",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "view_week_appointments")
async def view_week_appointments(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает записи на ближайшую неделю
    """
    try:
        logger.info("=== Сработал обработчик view_week_appointments ===")
        
        # Получаем текущее время
        now = datetime.now()
        week_later = now + timedelta(days=7)
        
        # Получаем записи на ближайшую неделю
        result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                TimeSlot.date >= now,
                TimeSlot.date <= week_later,
                Appointment.status.in_(["PENDING", "CONFIRMED"])  # Только ожидающие и подтвержденные
            )
            .order_by(TimeSlot.date)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointments = result.scalars().all()
        
        if not appointments:
            keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="manage_appointments")]]
            await callback.message.edit_text(
                f"<b>🔍 На ближайшую неделю записей нет</b>\n\n"
                f"<b>🔄 Обновлено:</b> <code>{now.strftime('%H:%M:%S')}</code>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                parse_mode="HTML"
            )
            return
        
        # Группируем записи по датам
        grouped = {}
        total_pending = 0
        total_confirmed = 0
        
        for app in appointments:
            date_str = app.time_slot.date.strftime('%d.%m.%Y')
            if date_str not in grouped:
                grouped[date_str] = []
            grouped[date_str].append(app)
            
            if app.status == "PENDING":
                total_pending += 1
            else:
                total_confirmed += 1
        
        # Формируем текст с общей статистикой и временем обновления
        text = (
            "<b>📅 Записи на ближайшую неделю:</b>\n"
            f"<i>🕐 Ожидают подтверждения:</i> <b>{total_pending}</b>\n"
            f"<i>✅ Подтверждено:</i> <b>{total_confirmed}</b>\n"
            f"<i>📊 Всего записей:</i> <b>{len(appointments)}</b>\n"
            f"<i>🔄 Обновлено:</i> <b>{now.strftime('%H:%M:%S')}</b>\n\n"
        )
        
        keyboard = []
        
        # Создаем кнопки для каждой записи, сгруппированные по датам
        for date_str, date_appointments in grouped.items():
            # Добавляем заголовок даты
            text += f"\n<b>📅 {date_str}:</b>\n"
            
            # Сортируем записи по времени
            date_appointments.sort(key=lambda x: x.time_slot.date)
            
            for app in date_appointments:
                status_emoji = "✅" if app.status == "CONFIRMED" else "🕐"
                time_str = app.time_slot.date.strftime('%H:%M')
                price_text = f"{app.final_price}₽" if app.final_price else f"от {app.service.price}₽"
                
                # Добавляем информацию о записи в текст
                text += (
                    f"<b>#{app.id}</b> <i>{time_str}</i> {status_emoji}\n"
                    f"<i>👤</i> <b>{app.user.full_name}</b>\n"
                    f"<i>💇‍♂️</i> <b>{app.service.name}</b>\n"
                    f"<i>💰</i> <b>{price_text}</b>\n\n"
                )
                
                # Создаем кнопку для записи
                button_text = f"#{app.id} {time_str} {status_emoji} {app.user.full_name}"
                keyboard.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"appointment_details_{app.id}"
                )])
        
        # Добавляем кнопки управления
        control_buttons = [
            [
                InlineKeyboardButton(text="🕐 Ожидающие", callback_data="filter_pending"),
                InlineKeyboardButton(text="✅ Подтвержденные", callback_data="filter_confirmed")
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_week_appointments"),
                InlineKeyboardButton(text="↩️ Назад", callback_data="manage_appointments")
            ]
        ]
        keyboard.extend(control_buttons)
        
        # Отправляем сообщение
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в view_week_appointments: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке записей на неделю",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("appointment_details_"))
async def view_appointment_details(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Просмотр деталей записи
    """
    try:
        appointment_id = int(callback.data.split("_")[2])
        
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
            await callback.answer("Запись не найдена")
            return
        
        # Определяем источник для кнопки "Назад"
        source = "view_week_appointments"
        if "Подтвержденные записи" in callback.message.text:
            source = "view_all_confirmed"
        elif "Новые заявки" in callback.message.text:
            source = "view_new_appointments"
        
        # Формируем детальную информацию о записи
        status_emoji = "✅" if appointment.status == "CONFIRMED" else "🕐"
        price_text = f"{appointment.final_price}₽" if appointment.final_price else f"от {appointment.service.price}₽"
        
        text = (
            f"<b>{status_emoji} Запись #{appointment.id}</b>\n\n"
            f"<b>⏰ Время:</b> {appointment.time_slot.date.strftime('%H:%M')}\n"
            f"<b>📅 Дата:</b> {appointment.time_slot.date.strftime('%d.%m.%Y')}\n"
            f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            f"<b>📱 Телефон:</b> {appointment.user.phone_number or '<i>Нет телефона</i>'}\n"
            f"<b>🚘 Автомобиль:</b> {appointment.car_brand} {appointment.car_model} ({appointment.car_year})\n"
            f"<b>💇‍♂️ Услуга:</b> {appointment.service.name}\n"
            f"<b>💰 Стоимость:</b> {price_text}\n"
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
            text += f"<b>💬 Комментарий клиента:</b>\n{formatted_comment}\n"
        if appointment.admin_response:
            text += f"<b>↪️ Ответ администратора:</b>\n<i>{appointment.admin_response}</i>\n"
        if appointment.admin_comment:
            text += f"<b>👨‍💼 Для администраторов:</b>\n<i>{appointment.admin_comment}</i>\n"
        
        # Создаем клавиатуру действий
        keyboard = []
        
        # Добавляем кнопку подтверждения только для неподтвержденных записей
        if appointment.status != "CONFIRMED":
            keyboard.append([
                    InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_appointment_{appointment.id}"
                )
            ])
        
        keyboard.extend([
            [
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"cancel_appointment_{appointment.id}"
                ),
                InlineKeyboardButton(
                    text="💬 Комментарий",
                    callback_data=f"add_appointment_comment_{appointment.id}"
                )
            ],
            [InlineKeyboardButton(
                text="↩️ Назад к списку",
                callback_data=source
            )]
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре деталей записи: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при загрузке информации")

@router.callback_query(F.data.startswith("view_all_confirmed"))
async def view_all_confirmed(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Просмотр всех подтвержденных записей
    """
    try:
        logger.info("=== Сработал обработчик view_all_confirmed ===")
        await callback.answer()
        
        # Получаем номер страницы из callback_data
        page = 1
        if "_page_" in callback.data:
            page = int(callback.data.split("_")[-1])
        
        ITEMS_PER_PAGE = 5  # Количество записей на странице
        
        # Получаем все подтвержденные записи
        result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                TimeSlot.date >= datetime.now(),
                Appointment.status == "CONFIRMED"
            )
            .order_by(TimeSlot.date)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        all_appointments = result.scalars().all()
        
        if not all_appointments:
            keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="manage_appointments")]]
            await callback.message.edit_text(
                "🔍 Подтвержденных записей пока нет",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            return
        
        # Подсчитываем общую выручку
        total_revenue = sum(app.final_price or app.service.price for app in all_appointments)
        total_pages = (len(all_appointments) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        
        # Получаем записи для текущей страницы
        start_idx = (page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        current_appointments = all_appointments[start_idx:end_idx]
        
        text = (
            f"<b>✅ Подтвержденные записи</b> (стр. {page}/{total_pages})\n"
            f"<i>📊 Всего записей:</i> <b>{len(all_appointments)}</b>\n"
            f"<i>💰 Общая сумма:</i> <b>{total_revenue}₽</b>\n\n"
        )
        
        keyboard = []
        
        # Группируем записи по датам для текущей страницы
        for app in current_appointments:
            date_str = app.time_slot.date.strftime('%d.%m.%Y')
            time_str = app.time_slot.date.strftime('%H:%M')
            price_text = f"{app.final_price}₽" if app.final_price else f"от {app.service.price}₽"
            
            text += (
                f"<b>🔸 #{app.id}</b> <i>{date_str} {time_str}</i>\n"
                f"<b>👤 {app.user.full_name}</b>\n"
                f"<i>💇‍♂️ {app.service.name}</i> • <b>{price_text}</b>\n"
                "──────────────\n"
            )
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"#{app.id} {time_str} ✅ Подробнее",
                    callback_data=f"appointment_details_{app.id}"
                )
            ])
        
        # Добавляем кнопки пагинации
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(
                text="◀️",
                callback_data=f"view_all_confirmed_page_{page-1}"
            ))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(
                text="▶️",
                callback_data=f"view_all_confirmed_page_{page+1}"
            ))
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        # Добавляем кнопки управления
        keyboard.append([
            InlineKeyboardButton(text="🔄 Обновить", callback_data="view_all_confirmed"),
            InlineKeyboardButton(text="↩️ Назад", callback_data="manage_appointments")
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в view_all_confirmed: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке подтвержденных записей",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("view_cancelled_appointments"), is_appointment_callback)
async def view_cancelled_appointments(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        await callback.answer()
        
        # Получаем номер страницы из callback_data
        page = 1
        if "_page_" in callback.data:
            page = int(callback.data.split("_")[-1])
        
        ITEMS_PER_PAGE = 5
        
        # Получаем все отмененные записи
        result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(Appointment.status == "CANCELLED")
            .order_by(TimeSlot.date.desc())  # Сортируем по убыванию даты
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        all_appointments = result.scalars().all()
        
        if not all_appointments:
            keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="manage_appointments")]]
            await callback.message.edit_text(
                "🔍 Отмененных записей пока нет",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            return
        
        total_pages = (len(all_appointments) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        
        # Получаем записи для текущей страницы
        start_idx = (page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        current_appointments = all_appointments[start_idx:end_idx]
        
        text = (
            f"<b>❌ Отмененные записи</b> (стр. {page}/{total_pages})\n"
            f"<b>📊 Всего записей:</b> {len(all_appointments)}\n\n"
        )
        
        keyboard = []
        
        # Группируем записи по датам для текущей страницы
        for app in current_appointments:
            date_str = app.time_slot.date.strftime('%d.%m.%Y')
            time_str = app.time_slot.date.strftime('%H:%M')
            
            text += (
                f"<b>🔸 #{app.id}</b> <i>{date_str} {time_str}</i>\n"
                f"<b>👤 Клиент:</b> {app.user.full_name}\n"
                f"<b>💇‍♂️ Услуга:</b> {app.service.name}\n"
                f"<b>❓ Причина:</b> <i>{app.cancellation_reason or 'Не указана'}</i>\n"
                "──────────────\n"
            )
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"#{app.id} {time_str} ❌ Подробнее",
                    callback_data=f"appointment_details_{app.id}"
                )
            ])
        
        # Добавляем кнопки пагинации
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(
                text="◀️",
                callback_data=f"view_cancelled_appointments_page_{page-1}"
            ))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(
                text="▶️",
                callback_data=f"view_cancelled_appointments_page_{page+1}"
            ))
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        # Добавляем кнопки управления
        keyboard.append([
            InlineKeyboardButton(text="🔄 Обновить", callback_data="view_cancelled_appointments"),
            InlineKeyboardButton(text="↩️ Назад", callback_data="manage_appointments")
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в view_cancelled_appointments: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке отмененных записей",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "filter_pending")
async def filter_pending_appointments(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает только ожидающие подтверждения записи
    """
    if not admin_filter(callback):
        await callback.answer("У вас нет прав для выполнения этого действия")
        return
        
    try:
        await callback.answer()
        
        # Получаем все ожидающие записи
        result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                TimeSlot.date >= datetime.now(),
                Appointment.status == "PENDING"
            )
            .order_by(TimeSlot.date)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointments = result.scalars().all()
        
        if not appointments:
            keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="view_week_appointments")]]
            await callback.message.edit_text(
                "🔍 Ожидающих подтверждения записей нет",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            return
        
        # Группируем записи по датам
        grouped = {}
        for app in appointments:
            date_str = app.time_slot.date.strftime('%d.%m.%Y')
            if date_str not in grouped:
                grouped[date_str] = []
            grouped[date_str].append(app)
        
        text = "<b>🕐 Ожидающие подтверждения записи:</b>\n\n"
        keyboard = []
        
        # Создаем кнопки для каждой записи
        for date_str, date_appointments in grouped.items():
            text += f"<b>📅 {date_str}</b> • <i>#{', #'.join(str(app.id) for app in date_appointments)}</i>:\n"
            for app in date_appointments:
                time_str = app.time_slot.date.strftime('%H:%M')
                price_text = f"от {app.service.price}₽"
                
                button_text = (
                    f"#{app.id} {time_str} 🕐 {app.user.full_name} • "
                    f"{app.service.name} • {price_text}"
                )
                keyboard.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"appointment_details_{app.id}"
                )])
            text += "\n"
        
        keyboard.append([InlineKeyboardButton(text="↩️ Назад", callback_data="view_week_appointments")])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при фильтрации записей: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при фильтрации записей",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "filter_confirmed")
async def filter_confirmed_appointments(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает только подтвержденные записи
    """
    if not admin_filter(callback):
        await callback.answer("У вас нет прав для выполнения этого действия")
        return
        
    try:
        await callback.answer()
        
        # Получаем все подтвержденные записи
        result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                TimeSlot.date >= datetime.now(),
                Appointment.status == "CONFIRMED"
            )
            .order_by(TimeSlot.date)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointments = result.scalars().all()
        
        if not appointments:
            keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="view_week_appointments")]]
            await callback.message.edit_text(
                "🔍 Подтвержденных записей нет",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            return
        
        # Подсчитываем общую выручку
        total_revenue = sum(app.final_price or app.service.price for app in appointments)
        
        # Группируем записи по датам
        grouped = {}
        for app in appointments:
            date_str = app.time_slot.date.strftime('%d.%m.%Y')
            if date_str not in grouped:
                grouped[date_str] = []
            grouped[date_str].append(app)
        
        text = "<b>✅ Подтвержденные записи</b>\n\n"
        keyboard = []
        
        # Создаем кнопки для каждой записи
        for date_str, date_appointments in grouped.items():
            text += f"<b>📅 {date_str}</b> • <i>#{', #'.join(str(app.id) for app in date_appointments)}</i>:\n"
            for app in date_appointments:
                time_str = app.time_slot.date.strftime('%H:%M')
                price_text = f"{app.final_price}₽" if app.final_price else f"от {app.service.price}₽"
                
                button_text = (
                    f"#{app.id} {time_str} ✅ {app.user.full_name} • "
                    f"{app.service.name} • {price_text}"
                )
                keyboard.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"appointment_details_{app.id}"
                )])
            text += "\n"
        
        keyboard.append([InlineKeyboardButton(text="↩️ Назад", callback_data="view_week_appointments")])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при фильтрации записей: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при фильтрации записей",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "refresh_week_appointments")
async def refresh_appointments(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Обновляет список записей
    """
    try:
        # Сразу отвечаем на callback
        await callback.answer()
        await view_week_appointments(callback, session)
    except Exception as e:
        logger.error(f"Ошибка в refresh_appointments: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при обновлении", show_alert=True)
        await callback.message.edit_text(
            "Произошла ошибка при обновлении списка записей",
            reply_markup=get_admin_inline_keyboard()
        )

@router.message()
async def catch_all_messages(message: Message, state: FSMContext):
    """
    Отлавливаем все сообщения, которые не попали в другие обработчики
    """
    # Проверяем, является ли пользователь админом
    if message.from_user.id not in settings.admin_ids:
        return
        
    logger.info("=================== НАЧАЛО catch_all_messages ===================")
    logger.info(f"User ID: {message.from_user.id}")
    logger.info(f"Текст сообщения: {message.text}")
    current_state = await state.get_state()
    state_data = await state.get_data()
    logger.info(f"Текущее состояние: {current_state}")
    logger.info(f"Данные состояния: {state_data}")
    logger.info("=================== КОНЕЦ catch_all_messages ===================\n")

@router.callback_query(F.data.startswith("quick_response_"))
async def handle_quick_response(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Обработка быстрых ответов на комментарий клиента
    """
    logger.info("=== Начало handle_quick_response ===")
    try:
        # Сразу отвечаем на callback
        await callback.answer()
        
        # Разбираем callback data
        parts = callback.data.split("_")
        if len(parts) < 4:
            logger.error(f"Некорректный формат callback data: {callback.data}")
            await callback.answer("Ошибка в формате ответа")
            return
            
        appointment_id = int(parts[2])
        
        # Используем все части после appointment_id как тип ответа
        # Это позволит корректно обрабатывать типы вроде "contact_soon"
        response_type = "_".join(parts[3:])
        
        logger.info(f"ID записи: {appointment_id}, тип ответа: {response_type}")
        
        # Получаем запись
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
            logger.error(f"Запись {appointment_id} не найдена")
            await callback.answer("Запись не найдена")
            return
        
        # Определяем текст ответа в зависимости от выбранного варианта
        response_text = ""
        if response_type == "accepted":
            response_text = "Принято! Ждем вас в указанное время."
        elif response_type == "ok":
            response_text = "Всё хорошо, ваша запись будет подтверждена."
        elif response_type == "contact_soon":
            response_text = "Мы скоро свяжемся с вами для уточнения деталей."
        elif response_type == "will_call":
            response_text = "Мы позвоним вам в ближайшее время."
        elif response_type == "use_previous":
            # Используем предыдущий ответ администратора
            if appointment.admin_response:
                response_text = appointment.admin_response
                logger.info(f"Используем предыдущий ответ: {response_text}")
            else:
                # На случай, если предыдущего ответа нет
                logger.warning(f"Предыдущий ответ не найден для записи {appointment_id}")
                await callback.answer("Предыдущий ответ не найден")
                response_text = "Ваша запись будет подтверждена."
        elif response_type == "skip_to_price":
            # Сразу переходим к установке цены без ответа
            logger.info("Переход к установке цены без ответа клиенту")
            # Определяем предварительную стоимость
            preliminary_price = appointment.service.price
            
            # Проверяем, есть ли окончательная цена из запроса расчета стоимости
            if appointment.final_price:
                preliminary_price = appointment.final_price
            elif appointment.client_comment and "Ответ менеджера:" in appointment.client_comment:
                for line in appointment.client_comment.split('\n'):
                    if "Ответ менеджера:" in line:
                        price_match = re.search(r'(\d+)(?:₽)?', line)
                        if price_match:
                            preliminary_price = int(price_match.group(1))
                            break
            
            await callback.message.edit_text(
                f"<b>💰 Установите точную стоимость для записи <code>#{appointment.id}</code>:</b>\n\n"
                f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
                f"<b>📱 Телефон:</b> <code>{appointment.user.phone_number or 'Не указан'}</code>\n"
                f"<b>📅 Дата:</b> <code>{appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
                f"<b>💇‍♂️ Услуга:</b> <code>{appointment.service.name}</code>\n"
                f"<b>🚗 Автомобиль:</b> <code>{appointment.car_brand} {appointment.car_model} ({appointment.car_year})</code>\n"
                f"<b>💬 Комментарий клиента:</b> <i>{appointment.client_comment}</i>\n\n"
                f"<b>Предварительная стоимость:</b> <code>{preliminary_price}₽</code>\n\n"
                "Введите точную стоимость в рублях:",
                reply_markup=None,
                parse_mode="HTML"
            )
            
            # Устанавливаем новое состояние
            await state.set_state(AdminAppointmentStates.setting_appointment_price)
            await state.update_data(appointment_id=appointment_id)
            logger.info("Состояние изменено на setting_appointment_price")
            return
        elif response_type == "custom":
            # Переходим к вводу собственного ответа
            await callback.message.edit_text(
                f"<b>💬 Введите свой ответ клиенту для записи <code>#{appointment.id}</code>:</b>\n\n"
                f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
                f"<b>💭 Комментарий клиента:</b> <i>{appointment.client_comment}</i>\n",
                reply_markup=None,
                parse_mode="HTML"
            )
            await state.set_state(AdminAppointmentStates.setting_admin_response)
            await state.update_data(appointment_id=appointment_id)
            return
        else:
            logger.warning(f"Неизвестный тип ответа: {response_type}")
            await callback.answer("Неизвестный тип ответа")
            return
        
        # Сохраняем ответ администратора
        appointment.admin_response = response_text
        logger.info(f"Сохраняем ответ администратора: {response_text}")
        await session.commit()
        logger.info("Ответ администратора сохранен в базе данных")
        
        # Определяем предварительную стоимость
        preliminary_price = appointment.service.price
        
        # Проверяем, есть ли окончательная цена из запроса расчета стоимости
        if appointment.final_price:
            preliminary_price = appointment.final_price
        elif appointment.client_comment and "Ответ менеджера:" in appointment.client_comment:
            for line in appointment.client_comment.split('\n'):
                if "Ответ менеджера:" in line:
                    price_match = re.search(r'(\d+)(?:₽)?', line)
                    if price_match:
                        preliminary_price = int(price_match.group(1))
                        break
        
        # Переходим к установке цены
        await callback.message.edit_text(
            f"<b>💰 Установите точную стоимость для записи <code>#{appointment.id}</code>:</b>\n\n"
            f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            f"<b>📱 Телефон:</b> <code>{appointment.user.phone_number or 'Не указан'}</code>\n"
            f"<b>📅 Дата:</b> <code>{appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}</code>\n"
            f"<b>💇‍♂️ Услуга:</b> <code>{appointment.service.name}</code>\n"
            f"<b>🚗 Автомобиль:</b> <code>{appointment.car_brand} {appointment.car_model} ({appointment.car_year})</code>\n"
            f"<b>💬 Комментарий клиента:</b> <i>{appointment.client_comment}</i>\n"
            f"<b>↪️ Ваш ответ:</b> {response_text}\n\n"
            f"<b>Предварительная стоимость:</b> <code>{preliminary_price}₽</code>\n\n"
            "Введите точную стоимость в рублях:",
            reply_markup=None,
            parse_mode="HTML"
        )
        
        # Устанавливаем новое состояние
        await state.set_state(AdminAppointmentStates.setting_appointment_price)
        await state.update_data(appointment_id=appointment_id)
        logger.info("Переход к установке цены выполнен после быстрого ответа")
        
    except Exception as e:
        logger.error(f"Ошибка в handle_quick_response: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при обработке ответа")
    finally:
        logger.info("=== Конец handle_quick_response ===\n")

# Добавляем обработчик для всех остальных сообщений в состоянии установки цены
@router.message()
async def handle_other_messages(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработчик для всех остальных сообщений
    """
    current_state = await state.get_state()
    if current_state == AdminAppointmentStates.setting_appointment_price:
        # Если мы в состоянии установки цены, но сообщение не обработалось основным хендлером
        await message.answer("Пожалуйста, введите только цену в виде целого числа (например, 5000):")
        return
    elif current_state == AdminAppointmentStates.adding_appointment_comment:
        # Если мы в состоянии добавления комментария
        await process_admin_comment(message, state, session)
        return
    elif current_state == AdminAppointmentStates.setting_admin_response:
        # Если мы в состоянии ответа на комментарий клиента
        await process_admin_response(message, state, session)
        return
    elif current_state == AdminAppointmentStates.cancelling_appointment:
        # Если мы в состоянии отмены записи
        await process_cancel_reason(message, state, session)
        return

@router.callback_query()
async def catch_all_callbacks(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для всех остальных callback-ов
    """
    try:
        # Проверяем, нужно ли пропустить этот callback
        should_skip = any(callback.data.startswith(prefix) for prefix in skip_callbacks)
        logger.info(f"Проверка callback {callback.data} на пропуск: {should_skip}")
        
        if should_skip:
            # Если callback нужно пропустить, прерываем его обработку
            return
            
        logger.info("=================== НАЧАЛО catch_all_callbacks ===================")
        logger.info(f"User ID: {callback.from_user.id}")
        logger.info(f"Callback data: {callback.data}")
        
        # Получаем текущее состояние
        current_state = await state.get_state()
        state_data = await state.get_data()
        logger.info(f"Текущее состояние: {current_state}")
        logger.info(f"Данные состояния: {state_data}")
        logger.info("=================== КОНЕЦ catch_all_callbacks ===================")

        # Если callback не обработан, отправляем сообщение об ошибке
        await callback.answer("❌ Неизвестная команда", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка в catch_all_callbacks: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)





