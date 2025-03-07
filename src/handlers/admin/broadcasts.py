# src/handlers/admin/broadcasts.py

from aiogram import Router, F, Bot
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime
import asyncio
import logging

from config.settings import settings
from database.models import User, Broadcast, Appointment
from keyboards.admin.admin import (
    get_admin_keyboard,
    get_content_management_keyboard,
    get_broadcast_management_keyboard,
    get_broadcast_audience_keyboard,
    get_skip_image_keyboard
)
from states.admin import BroadcastStates

router = Router(name='admin_broadcasts')

BROADCAST_PREFIXES = [
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
    "broadcast_cancel"
]

def is_broadcast_callback(callback: CallbackQuery) -> bool:
    """
    Проверяет, относится ли callback к управлению рассылками
    """
    return any(callback.data.startswith(prefix) for prefix in BROADCAST_PREFIXES)


def admin_filter(message: Message | CallbackQuery) -> bool:
    """
    Фильтр для проверки прав администратора
    """
    user_id = message.from_user.id if isinstance(message, Message) else message.message.from_user.id
    return user_id in settings.admin_ids


# Управление рассылками
@router.message(F.text == "📨 Управление рассылками", admin_filter)
async def broadcast_management(message: Message, session: AsyncSession) -> None:
    """
    Показывает меню управления рассылками
    """
    broadcasts = await session.execute(
        select(Broadcast).order_by(Broadcast.created_at.desc())
    )
    broadcasts = broadcasts.scalars().all()

    await message.answer(
        "<b>📨 Управление рассылками</b>\n\n"
        "Выберите действие:",
        reply_markup=get_broadcast_management_keyboard(broadcasts),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "broadcast_add", is_broadcast_callback)
async def start_add_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает процесс создания новой рассылки
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    await callback.message.edit_text(
        "<b>📨 Создание новой рассылки</b>\n\n"
        "Введите заголовок рассылки:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_title)
    await callback.answer()


@router.message(StateFilter(BroadcastStates.waiting_for_title), admin_filter)
async def process_broadcast_title(message: Message, state: FSMContext) -> None:
    """
    Обрабатывает ввод заголовка рассылки
    """
    await state.update_data(title=message.text)
    
    await message.answer(
        "<b>Заголовок сохранен!</b>\n\n"
        "Теперь введите текст рассылки:",
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_content)


@router.message(StateFilter(BroadcastStates.waiting_for_content), admin_filter)
async def process_broadcast_content(message: Message, state: FSMContext) -> None:
    """
    Обрабатывает ввод текста рассылки
    """
    await state.update_data(content=message.text)
    
    await message.answer(
        "<b>Текст рассылки сохранен!</b>\n\n"
        "Отправьте изображение для рассылки или нажмите 'Пропустить':",
        reply_markup=get_skip_image_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_image)


@router.message(StateFilter(BroadcastStates.waiting_for_image), F.text == "Пропустить", admin_filter)
async def skip_broadcast_image(message: Message, state: FSMContext) -> None:
    """
    Пропускает добавление изображения к рассылке
    """
    await state.update_data(image_url=None)
    await select_broadcast_audience(message, state)


@router.message(StateFilter(BroadcastStates.waiting_for_image), F.photo, admin_filter)
async def process_broadcast_image(message: Message, state: FSMContext) -> None:
    """
    Обрабатывает загрузку изображения для рассылки
    """
    photo = message.photo[-1]
    file_id = photo.file_id
    await state.update_data(image_url=file_id)
    
    await select_broadcast_audience(message, state)


async def select_broadcast_audience(message: Message, state: FSMContext) -> None:
    """
    Предлагает выбрать аудиторию для рассылки
    """
    await message.answer(
        "<b>Выберите аудиторию для рассылки:</b>",
        reply_markup=get_broadcast_audience_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_audience)


@router.callback_query(StateFilter(BroadcastStates.waiting_for_audience),
                       F.data.in_(["broadcast_audience_all", "broadcast_audience_active"]))
async def process_broadcast_audience(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Обрабатывает выбор аудитории для рассылки
    """
    try:
        # Получаем и проверяем данные из state
        data = await state.get_data()
        required_fields = ["title", "content"]
        if not all(field in data for field in required_fields):
            await callback.answer("Ошибка: неполные данные рассылки", show_alert=True)
            await state.clear()
            return

        # Получаем пользователя из базы данных по telegram_id
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Ошибка: пользователь не найден", show_alert=True)
            await state.clear()
            return

        audience_type = callback.data.replace("broadcast_audience_", "")
        
        # Создаем рассылку используя ID пользователя из базы данных
        new_broadcast = Broadcast(
            title=data["title"],
            content=data["content"],
            image_url=data.get("image_url"),  # используем .get() для опциональных полей
            created_by=user.id,  # Используем ID из базы данных
            audience_type=audience_type,
            status="DRAFT"
        )
        
        session.add(new_broadcast)
        await session.commit()
        await session.refresh(new_broadcast)
        
        # Получаем список всех рассылок для отображения в клавиатуре
        broadcasts = await session.execute(
            select(Broadcast).order_by(Broadcast.created_at.desc())
        )
        broadcasts = broadcasts.scalars().all()
        
        # Формируем текст ответа
        audience_text = "Все пользователи" if audience_type == "all" else "Активные клиенты"
        await callback.message.edit_text(
            f"<b>✅ Рассылка \"{data['title']}\" успешно создана!</b>\n\n"
            f"<b>ID:</b> {new_broadcast.id}\n"
            f"<b>Статус:</b> Черновик\n"
            f"<b>Аудитория:</b> {audience_text}\n\n"
            f"<b>Для отправки или удаления рассылки вернитесь в меню управления рассылками.</b>",
            reply_markup=get_broadcast_management_keyboard(broadcasts),
            parse_mode="HTML"
        )
        
        await state.clear()
        await callback.answer("<b>Рассылка успешно создана</b>", parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при создании рассылки: {e}")
        await callback.answer("<b>Произошла ошибка при создании рассылки</b>", show_alert=True, parse_mode="HTML")
        await state.clear()
        # Откатываем транзакцию в случае ошибки
        await session.rollback()


@router.callback_query(F.data.startswith("broadcast_delete_"), is_broadcast_callback)
async def delete_broadcast(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Удаляет рассылку
    """
    broadcast_id = int(callback.data.split("_")[-1])
    
    broadcast = await session.get(Broadcast, broadcast_id)
    if not broadcast:
        await callback.answer("<b>Рассылка не найдена!</b>", parse_mode="HTML")
        return
    
    await session.delete(broadcast)
    await session.commit()
    
    broadcasts = await session.execute(
        select(Broadcast).order_by(Broadcast.created_at.desc())
    )
    broadcasts = broadcasts.scalars().all()
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        # Отправляем новое сообщение
        await callback.message.answer(
            "<b>📨 Управление рассылками</b>\n\n"
            "✅ Рассылка успешно удалена!\n\n"
            "Выберите действие:",
            reply_markup=get_broadcast_management_keyboard(broadcasts),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при обновлении сообщения после удаления: {e}")
    
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast_send_"), is_broadcast_callback)
async def send_broadcast(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """
    Отправляет рассылку пользователям
    """
    broadcast_id = int(callback.data.split("_")[-1])
    
    broadcast = await session.get(Broadcast, broadcast_id)
    if not broadcast:
        await callback.answer("Рассылка не найдена!")
        return
    
    # Получаем пользователей для рассылки
    query = select(User)
    if broadcast.audience_type == "active":
        # Фильтр для активных клиентов - пользователей, у которых есть выполненные записи
        query = query.filter(User.appointments.any(Appointment.status == "COMPLETED"))
    
    users = await session.execute(query)
    users = users.scalars().all()
    
    # Обновляем статус рассылки
    broadcast.status = "SENDING"
    await session.commit()
    await session.refresh(broadcast)  # Обновляем объект из базы данных
    
    # Отправляем сообщение о начале рассылки
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        # Отправляем новое сообщение
        await callback.message.answer(
            f"<b>🔄 Начинаем отправку рассылки \"{broadcast.title}\" для {len(users)} пользователей...</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при обновлении сообщения: {e}")
    
    # Запускаем отправку рассылки в фоне
    task = asyncio.create_task(
        send_broadcast_to_users(bot, broadcast, users, session)
    )
    
    # Добавляем обработчик завершения задачи
    def handle_task_result(task):
        try:
            task.result()
        except Exception as e:
            logger.error(f"Ошибка при отправке рассылки: {e}")
    
    task.add_done_callback(handle_task_result)
    await callback.answer()


async def send_broadcast_to_users(bot: Bot, broadcast: Broadcast, users: list[User], session: AsyncSession) -> None:
    """
    Отправляет рассылку пользователям
    """
    success_count = 0
    error_count = 0
    
    # Получаем ID рассылки для последующего использования
    broadcast_id = broadcast.id
    
    for user in users:
        try:
            if broadcast.image_url:
                await bot.send_photo(
                    chat_id=user.telegram_id,
                    photo=broadcast.image_url,
                    caption=f"<b>{broadcast.title}</b>\n\n{broadcast.content}",
                    parse_mode="HTML"
                )
            else:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"<b>{broadcast.title}</b>\n\n{broadcast.content}",
                    parse_mode="HTML"
                )
            success_count += 1
            # Небольшая задержка между отправками, чтобы не превысить лимиты Telegram
            await asyncio.sleep(0.05)
        except Exception as e:
            logging.error(f"Ошибка при отправке рассылки пользователю {user.telegram_id}: {e}")
            error_count += 1
    
    # Получаем новый объект рассылки из базы данных
    broadcast = await session.get(Broadcast, broadcast_id)
    if not broadcast:
        logger.error(f"Не удалось найти рассылку с ID {broadcast_id}")
        return
    
    # Обновляем статус рассылки
    broadcast.status = "SENT"
    broadcast.sent_at = datetime.now()
    broadcast.sent_count = success_count
    await session.commit()
    await session.refresh(broadcast)
    
    # Получаем список рассылок для клавиатуры
    broadcasts = await session.execute(
        select(Broadcast).order_by(Broadcast.created_at.desc())
    )
    broadcasts = broadcasts.scalars().all()
    
    try:
        # Получаем telegram_id администратора из базы данных
        admin_result = await session.execute(
            select(User).where(User.id == broadcast.created_by)
        )
        admin = admin_result.scalar_one_or_none()
        
        if admin:
            # Отправляем сообщение о завершении рассылки
            completion_message = await bot.send_message(
                chat_id=admin.telegram_id,
                text=f"<b>✅ Рассылка \"{broadcast.title}\" завершена!</b>\n\n"
                     f"<b>Успешно отправлено:</b> {success_count}\n"
                     f"<b>Ошибок:</b> {error_count}",
                reply_markup=get_broadcast_management_keyboard(broadcasts),
                parse_mode="HTML"
            )
            
            # Обновляем сообщение с деталями рассылки, если оно существует
            try:
                # Формируем статус рассылки
                status_text = {
                    "DRAFT": "📝 Черновик",
                    "SENDING": "🔄 Отправляется",
                    "SENT": "✅ Отправлена",
                    "CANCELLED": "❌ Отменена"
                }.get(broadcast.status, broadcast.status)
                
                # Формируем аудиторию рассылки
                audience_text = {
                    "all": "👥 Все пользователи",
                    "active": "👤 Активные клиенты"
                }.get(broadcast.audience_type, broadcast.audience_type)
                
                # Формируем текст с деталями рассылки
                text = (
                    f"📨 Рассылка: <b>{broadcast.title}</b>\n\n"
                    f"Статус: {status_text}\n"
                    f"Аудитория: {audience_text}\n"
                    f"Создана: {broadcast.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                )
                
                if broadcast.sent_at:
                    text += f"Отправлена: {broadcast.sent_at.strftime('%d.%m.%Y %H:%M')}\n"
                
                if broadcast.sent_count:
                    text += f"Отправлено: {broadcast.sent_count} пользователям\n"
                
                text += f"\nТекст рассылки:\n{broadcast.content}"
                
                # Создаем клавиатуру с действиями
                keyboard = [
                    [
                        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"broadcast_delete_{broadcast.id}")
                    ],
                    [
                        InlineKeyboardButton(text="◀️ Назад", callback_data="broadcast_back_to_broadcasts")
                    ]
                ]
                
                # Находим и обновляем предыдущее сообщение с деталями рассылки
                messages = await bot.get_chat_history(admin.telegram_id, limit=10)
                for msg in messages:
                    if msg.text and "📨 Рассылка:" in msg.text and broadcast.title in msg.text:
                        try:
                            await msg.edit_text(
                                text=text,
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                                parse_mode="HTML"
                            )
                            break
                        except Exception as e:
                            logger.error(f"Ошибка при обновлении сообщения с деталями: {e}")
                            # Если не удалось обновить, отправляем новое сообщение
                            await bot.send_message(
                                chat_id=admin.telegram_id,
                                text=text,
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                                parse_mode="HTML"
                            )
                            break
            except Exception as e:
                logger.error(f"Ошибка при обновлении деталей рассылки: {e}")
            
    except Exception as e:
        logging.error(f"Ошибка при отправке уведомления администратору: {e}")


@router.callback_query(F.data == "broadcast_back_to_broadcasts", is_broadcast_callback)
async def back_to_broadcasts(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Возвращает к списку рассылок и очищает состояние
    """
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
    
    broadcasts = await session.execute(
        select(Broadcast).order_by(Broadcast.created_at.desc())
    )
    broadcasts = broadcasts.scalars().all()
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        # Отправляем новое сообщение
        await callback.message.answer(
            "<b>📨 Управление рассылками</b>\n\n"
            "Выберите действие:",
            reply_markup=get_broadcast_management_keyboard(broadcasts),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при возврате к списку рассылок: {e}")
    
    await callback.answer()


@router.callback_query(F.data == "broadcast_back_to_content")
async def back_to_content_management(callback: CallbackQuery) -> None:
    """
    Возвращает в меню управления контентом
    """
    await callback.message.edit_text(
        "<b>📢 Управление контентом</b>\n\n"
        "Выберите раздел:",
        reply_markup=get_content_management_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast_view_"), is_broadcast_callback)
async def view_broadcast(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает детали рассылки
    """
    try:
        logger.info(f"=== НАЧАЛО view_broadcast ===")
        logger.info(f"Callback data: {callback.data}")
        logger.info(f"User ID: {callback.from_user.id}")
        
        broadcast_id = int(callback.data.split("_")[-1])
        logger.info(f"Извлечен ID рассылки: {broadcast_id}")
        
        broadcast = await session.get(Broadcast, broadcast_id)
        logger.info(f"Получена рассылка: {broadcast}")
        
        if not broadcast:
            logger.warning(f"Рассылка с ID {broadcast_id} не найдена")
            await callback.answer("Рассылка не найдена!")
            return
        
        # Формируем статус рассылки
        status_text = {
            "DRAFT": "📝 Черновик",
            "SENDING": "🔄 Отправляется",
            "SENT": "✅ Отправлена",
            "CANCELLED": "❌ Отменена"
        }.get(broadcast.status, broadcast.status)
        
        # Формируем аудиторию рассылки
        audience_text = {
            "all": "👥 Все пользователи",
            "active": "👤 Активные клиенты"
        }.get(broadcast.audience_type, broadcast.audience_type)
        
        # Формируем текст с деталями рассылки
        text = (
            f"<b>📨 Рассылка:</b> <b>{broadcast.title}</b>\n\n"
            f"<b>Статус:</b> {status_text}\n"
            f"<b>Аудитория:</b> {audience_text}\n"
            f"<b>Создана:</b> {broadcast.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        )
        
        if broadcast.sent_at:
            text += f"<b>Отправлена:</b> {broadcast.sent_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        if broadcast.sent_count:
            text += f"<b>Отправлено:</b> {broadcast.sent_count} пользователям\n"
        
        text += f"\nТекст рассылки:\n{broadcast.content}"
        logger.info("Сформирован текст сообщения")
        
        # Создаем клавиатуру с действиями
        keyboard = []
        
        # Если рассылка в статусе черновика, добавляем кнопку отправки
        if broadcast.status == "DRAFT":
            keyboard.append([
                InlineKeyboardButton(text="📤 Отправить", callback_data=f"broadcast_send_{broadcast.id}")
            ])
        
        # Добавляем кнопку удаления
        keyboard.append([
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"broadcast_delete_{broadcast.id}")
        ])
        
        # Добавляем кнопку возврата
        keyboard.append([
            InlineKeyboardButton(text="◀️ Назад", callback_data="broadcast_back_to_broadcasts")
        ])
        logger.info("Сформирована клавиатура")
        
        try:
            # Если есть изображение, отправляем фото с подписью
            if broadcast.image_url:
                logger.info("Отправка сообщения с изображением")
                await callback.message.delete()
                await callback.message.answer_photo(
                    photo=broadcast.image_url,
                    caption=text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                    parse_mode="HTML"
                )
            else:
                logger.info("Отправка текстового сообщения")
                await callback.message.edit_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                    parse_mode="HTML"
                )
            logger.info("Сообщение успешно отправлено")
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {e}")
            raise
        
        await callback.answer()
        logger.info("=== КОНЕЦ view_broadcast ===")
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре рассылки: {e}")
        await callback.answer("Произошла ошибка при просмотре рассылки", show_alert=True)


@router.callback_query(F.data == "broadcast_cancel", is_broadcast_callback)
async def cancel_broadcast_creation(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Отменяет создание рассылки
    """
    await state.clear()
    broadcasts = await session.execute(
        select(Broadcast).order_by(Broadcast.created_at.desc())
    )
    broadcasts = broadcasts.scalars().all()
    
    await callback.message.edit_text(
        "<b>📨 Управление рассылками</b>\n\n"
        "❌ Создание рассылки отменено\n\n"
        "Выберите действие:",
        reply_markup=get_broadcast_management_keyboard(broadcasts),
        parse_mode="HTML"
    )
    await callback.answer() 