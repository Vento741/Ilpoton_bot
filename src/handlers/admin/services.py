# src/handlers/admin/services.py

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from loguru import logger
from datetime import datetime

from config.settings import settings
from database.models import Service, Appointment
from keyboards.admin.admin import get_services_management_keyboard, get_admin_inline_keyboard, get_service_edit_keyboard, get_service_view_keyboard, get_back_to_edit_keyboard
from states.admin import ServiceStates
from core.utils.logger import log_error
from core.utils.image_handler import delete_photo, save_photo_to_disk

router = Router(name='admin_services')

SERVICE_PREFIXES = [
    "add_service",
    "back_to_admin",
    "edit_service_",
    "edit_field_",
    "back_to_services",
    "delete_service_",
    "view_all_services",
    "view_service_",
    "back_to_service_edit",
    "manage_services",
    "view_archived_services",
    "process_edit_service_photo"
]

def admin_filter(message: Message | CallbackQuery) -> bool:
    """
    Фильтр для проверки прав администратора
    """
    if isinstance(message, Message):
        user_id = message.from_user.id
    else:  # CallbackQuery
        user_id = message.from_user.id
        
    logger.debug(f"Проверка прав администратора для пользователя {user_id}")
    logger.debug(f"Список администраторов: {settings.admin_ids}")
    return user_id in settings.admin_ids

def is_service_callback(callback: CallbackQuery) -> bool:
    """
    Проверяет, относится ли callback к управлению услугами
    """
    return any(callback.data.startswith(prefix) for prefix in SERVICE_PREFIXES)

@router.message(F.text == "💰 Управление услугами", admin_filter)
async def services_management(message: Message, session: AsyncSession) -> None:
    """
    Показывает меню управления услугами
    """
    try:
        logger.info(f"Администратор {message.from_user.id} открыл управление услугами")
        services = await session.execute(
            select(Service).where(
                Service.is_active == True,
                Service.is_archived == False
            )
        )
        services = services.scalars().all()
        logger.debug(f"Найдено {len(services)} активных услуг")

        keyboard = get_services_management_keyboard(services)
        logger.debug(f"Создана клавиатура: {keyboard.inline_keyboard}")

        await message.answer(
            "<b>💰 Управление услугами</b>\n\n"
            "Выберите действие:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при загрузке услуг")

@router.callback_query(F.data == "manage_services", admin_filter, is_service_callback)
async def manage_services(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Управление услугами
    """
    try:
        logger.info(f"Администратор {callback.from_user.id} открыл управление услугами")
        await callback.answer()
        
        # Получаем все услуги
        services = await session.execute(select(Service))
        services = services.scalars().all()
        
        await callback.message.edit_text(
            "<b>💰 Управление услугами</b>\n\n"
            "Выберите действие:",
            reply_markup=get_services_management_keyboard(services),
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке услуг",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "add_service", admin_filter, is_service_callback)
async def start_add_service(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начало процесса добавления услуги
    """
    try:
        logger.info(f"Администратор {callback.from_user.id} начал добавление услуги. Callback data: {callback.data}")
        await callback.answer("Начинаем добавление услуги")
        await state.set_state(ServiceStates.adding_name)  # Используем отдельное состояние для добавления
        await callback.message.edit_text("Введите название услуги:")
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при добавлении услуги",
            reply_markup=get_services_management_keyboard([])
        )


@router.callback_query(F.data == "back_to_admin", admin_filter, is_service_callback)
async def back_to_admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Возврат в главное меню администратора
    """
    try:
        logger.info(f"Администратор {callback.from_user.id} вернулся в главное меню. Callback data: {callback.data}")
        await callback.answer("Возвращаемся в главное меню")
        await state.clear()
        await callback.message.edit_text(
            "Вы вернулись в главное меню администратора",
            reply_markup=get_admin_inline_keyboard()
        )
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при возврате в главное меню",
            reply_markup=get_admin_inline_keyboard()
        )


@router.callback_query(F.data.startswith("edit_service_"), is_service_callback)
async def edit_service(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Начало процесса редактирования услуги
    """
    try:
        service_id = int(callback.data.split("_")[2])
        service = await session.get(Service, service_id)
        
        if not service:
            await callback.answer("Услуга не найдена!")
            return

        await state.set_state(ServiceStates.editing)
        await state.update_data(service_id=service_id)
        
        # Формируем информацию об изображении
        image_info = "не загружено"
        if service.image_id:
            image_info = "загружено"
        
        service_info = (
            f"<b>🔄 Редактирование услуги:</b>\n\n"
            f"<b>Название:</b> {service.name}\n"
            f"<b>Описание:</b> {service.description}\n"
            f"<b>Стоимость:</b> от {service.price}₽\n"
            f"<b>Длительность:</b> от {service.duration} мин.\n"
            f"<b>Изображение:</b> {image_info}\n\n"
            "<b>Что вы хотите изменить?</b>"
        )

        try:
            # Пробуем отредактировать текущее сообщение
            await callback.message.edit_text(
                service_info,
                reply_markup=get_service_edit_keyboard()
            )
        except Exception as e:
            # Если не получилось отредактировать (например, сообщение с фото),
            # удаляем старое и отправляем новое
            try:
                await callback.message.delete()
            except Exception as delete_error:
                logger.error(f"Ошибка при удалении сообщения: {delete_error}")
            
            await callback.message.answer(
                service_info,
                reply_markup=get_service_edit_keyboard()
            )
            
    except Exception as e:
        log_error(e)
        # В случае ошибки пробуем отправить новое сообщение
        await callback.message.answer(
            "Произошла ошибка при редактировании услуги",
            reply_markup=get_services_management_keyboard([])
        )


@router.callback_query(F.data.startswith("edit_field_"), ServiceStates.editing, is_service_callback)
async def process_edit_field_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка выбора поля для редактирования
    """
    field = callback.data.split("_")[2]
    await state.update_data(editing_field=field)
    
    field_messages = {
        "name": "Введите новое название услуги:",
        "description": "Введите новое описание услуги:",
        "price": "Введите новую стоимость услуги (в рублях):",
        "duration": "Введите новую длительность услуги (в минутах):",
        "image": "📸 Отправьте новое фото для услуги:"
    }
    
    field_states = {
        "name": ServiceStates.entering_name,
        "description": ServiceStates.entering_description,
        "price": ServiceStates.entering_price,
        "duration": ServiceStates.entering_duration,
        "image": ServiceStates.uploading_photo
    }
    
    # Добавим логирование для отладки
    logger.debug(f"Получен callback с полем: {field}")
    logger.debug(f"Доступные поля в field_messages: {list(field_messages.keys())}")
    logger.debug(f"Доступные поля в field_states: {list(field_states.keys())}")
    
    await state.set_state(field_states[field])
    await callback.message.edit_text(
        field_messages[field],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_services")]
        ])
    )


@router.callback_query(F.data == "back_to_services", is_service_callback)
async def back_to_services_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Возврат к списку услуг
    """
    try:
        await state.clear()
        services = await session.execute(select(Service))
        services = services.scalars().all()
        
        message_text = (
            "<b>💰 Управление услугами</b>\n\n"
            "<b>Выберите действие:</b>"
        )
        
        try:
            # Пробуем отредактировать текущее сообщение
            await callback.message.edit_text(
                message_text,
                reply_markup=get_services_management_keyboard(services),
                parse_mode="HTML"
            )
        except Exception as e:
            # Если не получилось отредактировать (например, сообщение с фото),
            # удаляем старое и отправляем новое
            try:
                await callback.message.delete()
            except Exception as delete_error:
                logger.error(f"Ошибка при удалении сообщения: {delete_error}")
            
            await callback.message.answer(
                message_text,
                reply_markup=get_services_management_keyboard(services),
                parse_mode="HTML"
            )
            
    except Exception as e:
        log_error(e)
        # В случае ошибки пробуем отправить новое сообщение
        await callback.message.answer(
            "Произошла ошибка при возврате к списку услуг",
            reply_markup=get_services_management_keyboard([])
        )


@router.message(ServiceStates.adding_name, admin_filter)
async def process_add_name(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода названия новой услуги
    """
    try:
        await state.update_data(name=message.text)
        await state.set_state(ServiceStates.adding_description)
        await message.answer("Введите описание услуги:")
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при сохранении названия услуги")


@router.message(ServiceStates.adding_description, admin_filter)
async def process_add_description(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода описания новой услуги
    """
    try:
        await state.update_data(description=message.text)
        await state.set_state(ServiceStates.adding_price)
        await message.answer("Введите стоимость услуги (в рублях):")
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при сохранении описания услуги")


@router.message(ServiceStates.adding_price, admin_filter)
async def process_add_price(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода стоимости новой услуги
    """
    try:
        price_text = message.text.lower().replace('от', '').strip()
        
        if not price_text.isdigit():
            await message.answer("Пожалуйста, введите число (например: 1000 или От 1000):")
            return
            
        await state.update_data(price=int(price_text))
        await state.set_state(ServiceStates.adding_duration)
        await message.answer("Введите длительность услуги (в минутах):")
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при сохранении стоимости услуги")


@router.message(ServiceStates.adding_duration, admin_filter)
async def process_add_duration(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода длительности новой услуги
    """
    try:
        duration_text = message.text.lower().replace('от', '').strip()
        
        if not duration_text.isdigit():
            await message.answer("Пожалуйста, введите число в минутах (например: 30 или От 30):")
            return
            
        # Сохраняем длительность в состояние
        await state.update_data(duration=int(duration_text))
        
        # Переходим к загрузке фото
        await state.set_state(ServiceStates.uploading_photo)
        await message.answer(
            "📸 Отправьте фотографию для услуги:",
            reply_markup=get_back_to_edit_keyboard()
        )
        
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при сохранении длительности услуги")


@router.message(ServiceStates.uploading_photo, F.photo, admin_filter)
async def process_add_service_photo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """Обработка загруженного фото при создании новой услуги"""
    try:
        # Получаем все сохраненные данные
        data = await state.get_data()
        
        # Проверяем, есть ли service_id в данных
        if 'service_id' in data:
            # Если есть service_id, значит это редактирование - передаем управление другому обработчику
            await process_edit_service_photo(message, state, session, bot)
            return
        
        # Создаем новую услугу без фото
        new_service = Service(
            name=data['name'],
            description=data['description'],
            price=data['price'],
            duration=data['duration']
        )
        session.add(new_service)
        await session.flush()  # Получаем ID новой услуги
        
        # Сохраняем фото
        photo = message.photo[-1]
        image_path, file_id = await save_photo_to_disk(photo, bot, f"services/{new_service.id}")
        
        # Обновляем данные услуги
        new_service.image_path = image_path
        new_service.image_id = file_id
        await session.commit()
        
        # Формируем информацию об услуге
        service_info = (
            f"<b>✅ Услуга успешно добавлена!</b>\n\n"
            f"<b>Название:</b> {new_service.name}\n"
            f"<b>Описание:</b> {new_service.description}\n"
            f"<b>Стоимость:</b> от {new_service.price}₽\n"
            f"<b>Длительность:</b> от {new_service.duration} мин."
        )
        
        # Отправляем фото с информацией об услуге
        await message.answer_photo(
            photo=file_id,
            caption=service_info
        )
        
        # Показываем обновленный список услуг
        services = await session.execute(select(Service))
        services = services.scalars().all()
        await message.answer(
            "<b>💰 Управление услугами</b>\n\n"
            "<b>Выберите действие:</b>",
            reply_markup=get_services_management_keyboard(services),
            parse_mode="HTML"
        )
        await state.clear()
        
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при создании услуги")


@router.message(ServiceStates.uploading_photo, admin_filter)
async def process_add_service_no_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Обработка создания услуги без фото"""
    try:
        await message.answer(
            "❌ Пожалуйста, отправьте фотографию для услуги.\n"
            "Отправка URL больше не поддерживается.",
            reply_markup=get_back_to_edit_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке создания услуги без фото: {e}")
        await message.answer(
            "❌ Произошла ошибка. Пожалуйста, попробуйте отправить фото:",
            reply_markup=get_back_to_edit_keyboard()
        )


@router.message(ServiceStates.entering_name, admin_filter)
async def process_edit_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка изменения названия услуги
    """
    try:
        data = await state.get_data()
        service_id = data['service_id']
        service = await session.get(Service, service_id)
        
        if not service:
            await message.answer("Услуга не найдена!")
            await state.clear()
            return
        
        service.name = message.text
        await session.commit()
        
        await show_updated_service(message, service, state, session)
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при обновлении названия услуги")


@router.message(ServiceStates.entering_description, admin_filter)
async def process_edit_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка изменения описания услуги
    """
    try:
        data = await state.get_data()
        service_id = data['service_id']
        service = await session.get(Service, service_id)
        
        if not service:
            await message.answer("Услуга не найдена!")
            await state.clear()
            return
        
        service.description = message.text
        await session.commit()
        
        await show_updated_service(message, service, state, session)
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при обновлении описания услуги")


@router.message(ServiceStates.entering_price, admin_filter)
async def process_edit_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка изменения стоимости услуги
    """
    try:
        # Убираем "от" и пробелы, если они есть
        price_text = message.text.lower().replace('от', '').strip()
        
        if not price_text.isdigit():
            await message.answer("Пожалуйста, введите число (например: 1000 или От 1000):")
            return
            
        data = await state.get_data()
        service_id = data['service_id']
        service = await session.get(Service, service_id)
        
        if not service:
            await message.answer("Услуга не найдена!")
            await state.clear()
            return
        
        service.price = int(price_text)
        await session.commit()
        
        await show_updated_service(message, service, state, session)
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при обновлении стоимости услуги")


@router.message(ServiceStates.entering_duration, admin_filter)
async def process_edit_duration(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка изменения длительности услуги
    """
    try:
        # Убираем "от" и пробелы, если они есть
        duration_text = message.text.lower().replace('от', '').strip()
        
        if not duration_text.isdigit():
            await message.answer("Пожалуйста, введите число в минутах (например: 30 или От 30):")
            return
            
        data = await state.get_data()
        service_id = data['service_id']
        service = await session.get(Service, service_id)
        
        if not service:
            await message.answer("Услуга не найдена!")
            await state.clear()
            return
        
        service.duration = int(duration_text)
        await session.commit()
        
        await show_updated_service(message, service, state, session)
    except Exception as e:
        log_error(e)
        await message.answer("Произошла ошибка при обновлении длительности услуги")

@router.message(ServiceStates.uploading_photo, F.photo, admin_filter)
async def process_edit_service_photo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """Обработка загруженного фото при редактировании услуги"""
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        service_id = data.get('service_id')
        
        if not service_id:
            await message.answer("❌ Ошибка: данные услуги не найдены")
            await state.clear()
            return
        
        # Получаем услугу из БД
        service = await session.get(Service, service_id)
        if not service:
            await message.answer("❌ Ошибка: услуга не найдена")
            await state.clear()
            return
        
        # Если есть старое фото, удаляем его
        if service.image_path:
            await delete_photo(service.image_path)
        
        # Сохраняем новое фото
        photo = message.photo[-1]
        image_path, file_id = await save_photo_to_disk(photo, bot, f"services/{service.id}")
        
        # Обновляем данные услуги
        service.image_path = image_path
        service.image_id = file_id
        await session.commit()
        
        # Формируем информацию об услуге
        service_info = (
            f"<b>✅ Фото успешно обновлено!</b>\n\n"
            f"<b>Название:</b> {service.name}\n"
            f"<b>Описание:</b> {service.description}\n"
            f"<b>Стоимость:</b> от {service.price}₽\n"
            f"<b>Длительность:</b> от {service.duration} мин."
        )
        
        # Отправляем фото с информацией об услуге
        await message.answer_photo(
            photo=file_id,
            caption=service_info,
            reply_markup=get_service_edit_keyboard()
        )
        
        # Возвращаемся к состоянию редактирования
        await state.set_state(ServiceStates.editing)
        
    except Exception as e:
        log_error(e)
        await message.answer(
            "❌ Произошла ошибка при обновлении фото",
            reply_markup=get_back_to_edit_keyboard()
        )

async def show_updated_service(message: Message, service: Service, state: FSMContext, session: AsyncSession) -> None:
    """
    Показывает обновленную информацию об услуге
    """
    await state.set_state(ServiceStates.editing)
    
    # Формируем информацию об изображении
    image_info = "не загружено"
    if service.image_id:
        image_info = "загружено"
    
    service_info = (
        f"<b>✅ Услуга успешно обновлена!</b>\n\n"
        f"<b>Название:</b> {service.name}\n"
        f"<b>Описание:</b> {service.description}\n"
        f"<b>Стоимость:</b> от {service.price}₽\n"
        f"<b>Длительность:</b> от {service.duration} мин.\n"
        f"<b>Изображение:</b> {image_info}\n\n"
        "<b>Что вы хотите изменить?</b>"
    )
    
    await message.answer(service_info, reply_markup=get_service_edit_keyboard())


@router.callback_query(F.data.startswith("delete_service_"), admin_filter, is_service_callback)
async def delete_service(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Удаление услуги
    """
    try:
        service_id = int(callback.data.split("_")[2])
        logger.info(f"Попытка удаления услуги с ID {service_id}")
        
        # Получаем услугу вместе со связанными записями
        appointments_count = await session.scalar(
            select(func.count(Appointment.id)).where(Appointment.service_id == service_id)
        )
        
        service = await session.get(Service, service_id)
        if not service:
            logger.warning(f"Услуга с ID {service_id} не найдена")
            await callback.answer("❌ Услуга не найдена!", show_alert=True)
            return

        service_name = service.name
        has_appointments = appointments_count > 0
        
        if has_appointments:
            logger.info(f"Архивация услуги '{service_name}' (ID: {service_id}) из-за наличия связанных записей")
            # Помечаем услугу как неактивную и архивированную
            service.is_active = False
            service.is_archived = True
            service.updated_at = datetime.now()
            
            # Если есть изображение, удаляем его
            if service.image_path:
                await delete_photo(service.image_path)
                service.image_path = None
                service.image_id = None
                
            await session.commit()
            logger.info(f"Услуга '{service_name}' успешно архивирована")
            
            await callback.answer(
                "ℹ️ Услуга перемещена в архив, так как есть связанные записи",
                show_alert=True
            )
        else:
            logger.info(f"Полное удаление услуги '{service_name}' (ID: {service_id})")
            
            # Если есть изображение, удаляем его
            if service.image_path:
                await delete_photo(service.image_path)
            
            # Удаляем услугу из БД
            await session.delete(service)
            await session.commit()
            logger.info(f"Услуга '{service_name}' полностью удалена")
            
            await callback.answer("✅ Услуга удалена!", show_alert=True)
        
        # Получаем обновленный список активных и неархивированных услуг
        services = await session.execute(
            select(Service).where(
                Service.is_active == True,
                Service.is_archived == False
            )
        )
        services = services.scalars().all()
        logger.debug(f"Получен обновленный список услуг: {len(services)} активных услуг")
        
        status_text = "архивирована" if has_appointments else "удалена"
        message_text = (
            f"<b>✅ Услуга '{service_name}' {status_text}!</b>\n\n"
            "<b>💰 Управление услугами</b>\n"
            "<b>Выберите действие:</b>"
        )

        try:
            # Пробуем отредактировать текущее сообщение
            await callback.message.edit_text(
                message_text,
                reply_markup=get_services_management_keyboard(services),
                parse_mode="HTML"
            )
        except Exception as e:
            # Если не получилось отредактировать (например, сообщение с фото),
            # удаляем старое и отправляем новое
            try:
                await callback.message.delete()
            except Exception as delete_error:
                logger.error(f"Ошибка при удалении сообщения: {delete_error}")
            
            await callback.message.answer(
                message_text,
                reply_markup=get_services_management_keyboard(services),
                parse_mode="HTML"
            )
        
    except ValueError as e:
        logger.error(f"Ошибка преобразования ID услуги: {str(e)}")
        await callback.answer("❌ Некорректный ID услуги!", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при удалении/архивации услуги: {str(e)}")
        await callback.answer(
            "❌ Произошла ошибка при удалении услуги. Попробуйте позже.",
            show_alert=True
        )


@router.callback_query(F.data == "view_all_services", is_service_callback)
async def view_all_services(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает список всех активных и неархивированных услуг
    """
    try:
        services = await session.execute(
            select(Service).where(
                Service.is_active == True,
                Service.is_archived == False
            )
        )
        services = services.scalars().all()
        
        # Формируем новый текст и клавиатуру
        new_text = "<b>📋 Список активных услуг:</b>\nВыберите услугу для просмотра подробной информации:"
        keyboard = []
        
        if not services:
            new_text = "<b>Нет доступных услуг.</b>"
            new_keyboard = get_services_management_keyboard([])
        else:
            # Создаем кнопки для каждой услуги
            for service in services:
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"{service.name} - от {service.price}₽",
                        callback_data=f"view_service_{service.id}"
                    )
                ])
            
            # Добавляем кнопку "Назад"
            keyboard.append([
                InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_services")
            ])
            new_keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        # Проверяем, отличается ли новое сообщение от текущего
        current_text = callback.message.text
        current_markup = callback.message.reply_markup
        
        if current_text != new_text or current_markup != new_keyboard:
            await callback.message.edit_text(
                new_text,
                reply_markup=new_keyboard,
                parse_mode="HTML"
            )
        else:
            # Если сообщение не изменилось, просто отвечаем на callback
            await callback.answer()
            
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке списка услуг",
            reply_markup=get_services_management_keyboard([]),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("view_service_"), admin_filter, is_service_callback)
async def view_service_details(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает подробную информацию об услуге
    """
    try:
        service_id = int(callback.data.split("_")[2])
        service = await session.get(Service, service_id)
        
        if not service:
            await callback.answer("❌ Услуга не найдена!", show_alert=True)
            return
        
        service_info = (
            f"<b>📋 Информация об услуге:</b>\n\n"
            f"<b>Название:</b> {service.name}\n"
            f"<b>Описание:</b> {service.description}\n"
            f"<b>Стоимость:</b> от {service.price}₽\n"
            f"<b>Длительность:</b> от {service.duration} мин."
        )
        
        # Если есть фото, отправляем его вместе с информацией
        if service.image_id:
            # Удаляем предыдущее сообщение
            await callback.message.delete()
            # Отправляем фото с описанием
            await callback.message.answer_photo(
                photo=service.image_id,
                caption=service_info,
                reply_markup=get_service_view_keyboard(service.id)
            )
        else:
            # Если фото нет, отправляем только текст
            await callback.message.edit_text(
                service_info,
                reply_markup=get_service_view_keyboard(service.id)
            )
            
    except ValueError:
        await callback.answer("❌ Некорректный ID услуги!", show_alert=True)
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке информации об услуге",
            reply_markup=get_services_management_keyboard([]),
            parse_mode="HTML"
        )


@router.callback_query(F.data == "edit_field_image_url", admin_filter, is_service_callback)
async def process_edit_image_url(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка изменения изображения услуги
    """
    try:
        data = await state.get_data()
        service_id = data['service_id']
        service = await session.get(Service, service_id)
        
        if not service:
            await callback.answer("Услуга не найдена!")
            await state.clear()
            return
        
        await state.set_state(ServiceStates.uploading_photo)
        await callback.message.edit_text(
            "<b>📸 Отправьте новое фото для услуги:</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_services")]
            ]),
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при изменении изображения",
            reply_markup=get_service_edit_keyboard(),
            parse_mode="HTML"
        )


@router.callback_query(F.data == "back_to_service_edit", admin_filter, is_service_callback)
async def back_to_service_edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Возврат к редактированию услуги
    """
    try:
        data = await state.get_data()
        service_id = data.get('service_id')
        
        if not service_id:
            await callback.message.edit_text(
                "❌ Ошибка: данные услуги не найдены",
                reply_markup=get_services_management_keyboard([]),
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        service = await session.get(Service, service_id)
        if not service:
            await callback.message.edit_text(
                "❌ Ошибка: услуга не найдена",
                reply_markup=get_services_management_keyboard([])
            )
            await state.clear()
            return
        
        await state.set_state(ServiceStates.editing)
        
        # Формируем информацию об изображении
        image_info = "не загружено"
        if service.image_id:
            image_info = "загружено"
        
        service_info = (
            f"<b>🔄 Редактирование услуги:</b>\n\n"
            f"<b>Название:</b> {service.name}\n"
            f"<b>Описание:</b> {service.description}\n"
            f"<b>Стоимость:</b> от {service.price}₽\n"
            f"<b>Длительность:</b> от {service.duration} мин.\n"
            f"<b>Изображение:</b> {image_info}\n\n"
            "Что вы хотите изменить?"
        )
        
        await callback.message.edit_text(
            service_info,
            reply_markup=get_service_edit_keyboard(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при возврате к редактированию услуги: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при возврате к редактированию",
            reply_markup=get_services_management_keyboard([]),
            parse_mode="HTML"
        )
        await state.clear()

@router.callback_query(F.data == "view_archived_services", admin_filter, is_service_callback)
async def view_archived_services(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает список архивированных услуг
    """
    try:
        # Получаем архивированные услуги
        services = await session.execute(
            select(Service).where(
                Service.is_archived == True
            )
        )
        services = services.scalars().all()
        
        if not services:
            await callback.message.edit_text(
                "<b>📁 В архиве нет услуг.</b>",
                reply_markup=get_services_management_keyboard([]),
                parse_mode="HTML"
            )
            return
        
        keyboard = []
        # Создаем кнопки для каждой архивированной услуги
        for service in services:
            # Добавляем статус архивации к названию услуги
            keyboard.append([
                InlineKeyboardButton(
                    text=f"📁 {service.name} - от {service.price}₽",
                    callback_data=f"view_service_{service.id}"
                )
            ])
        
        # Добавляем кнопку "Назад"
        keyboard.append([
            InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_services")
        ])
        
        # Формируем новый текст и клавиатуру
        new_text = (
            "<b>📁 Архив услуг:</b>\n"
            "<i>Выберите услугу для просмотра подробной информации:</i>"
        )
        new_keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        # Проверяем, отличается ли новое сообщение от текущего
        current_text = callback.message.text
        current_markup = callback.message.reply_markup
        
        if current_text != new_text or current_markup != new_keyboard:
            await callback.message.edit_text(
                new_text,
                reply_markup=new_keyboard
            )
        else:
            # Если сообщение не изменилось, просто отвечаем на callback
            await callback.answer()
            
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке архива услуг",
            reply_markup=get_services_management_keyboard([])
        )