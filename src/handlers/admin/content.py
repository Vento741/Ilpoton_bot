# src/handlers/admin/content.py

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import os

from config.settings import settings
from core.utils.logger import log_error, logger
from database.models import News, Broadcast, User
from keyboards.admin.admin import (
    get_admin_keyboard,
    get_news_management_keyboard,
    get_content_management_keyboard,
    get_broadcast_management_keyboard,
    get_admin_inline_keyboard
)
from core.utils.image_handler import delete_photo, save_photo_to_disk
from states.admin import NewsStates

router = Router(name='admin_content')

CONTENT_PREFIXES = [
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
    "edit_news_title_"
]

def is_content_callback(callback: CallbackQuery) -> bool:
    """
    Проверяет, относится ли callback к управлению контентом
    """
    return any(callback.data.startswith(prefix) for prefix in CONTENT_PREFIXES)

def admin_filter(message: Message | CallbackQuery) -> bool:
    """
    Фильтр для проверки прав администратора
    """
    user_id = message.from_user.id if isinstance(message, Message) else message.message.from_user.id
    return user_id in settings.admin_ids

@router.callback_query(F.data == "manage_content", admin_filter, is_content_callback)
async def manage_content(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Управление контентом
    """
    try:
        logger.info("=== НАЧАЛО manage_content ===")
        logger.info(f"Callback data: {callback.data}")
        logger.info(f"User ID: {callback.from_user.id}")

        # Получаем количество элементов для отображения в кнопках
        news_count = await session.scalar(select(News).count())
        broadcasts_count = await session.scalar(select(Broadcast).count())
        
        logger.info(f"Статистика: новости={news_count}, рассылки={broadcasts_count}")

        text = (
            "<b>📢 Управление контентом</b>\n\n"
            f"<b>📰 Новостей:</b> {news_count}\n"
            f"<b>📨 Рассылок:</b> {broadcasts_count}\n\n"
            "Выберите раздел для управления:"
        )
        
        logger.info("Отправка сообщения с клавиатурой")
        await callback.message.edit_text(
            text,
            reply_markup=get_content_management_keyboard(),
            parse_mode="HTML"
        )
        logger.info("Сообщение успешно отправлено")
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике manage_content: {e}", exc_info=True)
        log_error(e)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при открытии управления контентом</b>",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )
    finally:
        logger.info("=== КОНЕЦ manage_content ===")

@router.callback_query(F.data == "content_add_news_", is_content_callback)
async def start_add_news(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начало процесса добавления новости
    """
    try:
        logger.info(f"DEBUG: Вызван обработчик start_add_news с callback_data={callback.data}")
        logger.info(f"Администратор {callback.from_user.id} начал процесс добавления новости")
        await callback.answer()
        
        await state.set_state(NewsStates.entering_title)
        await callback.message.edit_text("Введите заголовок новости:")
    except Exception as e:
        logger.error(f"Ошибка в обработчике start_add_news: {e}")
        log_error(e)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при начале добавления новости</b>",
            reply_markup=get_news_management_keyboard([]),
            parse_mode="HTML"
        )


@router.message(NewsStates.entering_title, admin_filter)
async def process_news_title(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода заголовка новости
    """
    await state.update_data(title=message.text)
    await state.set_state(NewsStates.entering_content)
    await message.answer("Введите текст новости:")


@router.message(NewsStates.entering_content, admin_filter)
async def process_news_content(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода текста новости при создании
    """
    await state.update_data(content=message.text)
    await state.set_state(NewsStates.uploading_photo)
    await message.answer(
        "Отправьте фотографию для новости (или отправьте /skip, чтобы пропустить):"
    )


@router.message(NewsStates.uploading_photo, F.photo, admin_filter)
async def process_news_photo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """
    Обработка загрузки фото для новости
    """
    try:
        # Получаем пользователя из базы данных
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.answer(
                "❌ Ошибка: пользователь не найден в базе данных.",
                reply_markup=get_admin_keyboard()
            )
            return

        photo = message.photo[-1]
        data = await state.get_data()
        
        # Сохраняем фото и получаем путь и file_id
        image_path, file_id = await save_photo_to_disk(photo, bot, "news")
        
        news_item = News(
            title=data["title"],
            content=data["content"],
            image_url=image_path,  # Сохраняем только путь к файлу
            created_by=user.id  # Используем ID пользователя из базы данных
        )
        session.add(news_item)
        await session.commit()

        await state.clear()
        await message.answer(
            "✅ Новость успешно опубликована!",
            reply_markup=get_admin_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении фото новости: {e}")
        # Удаляем сохраненное фото в случае ошибки
        if 'image_path' in locals():
            await delete_photo(image_path)
        await message.answer(
            "❌ Произошла ошибка при сохранении фото. Попробуйте еще раз.",
            reply_markup=get_admin_keyboard()
        )


@router.message(NewsStates.uploading_photo, Command("skip"), admin_filter)
async def skip_news_photo(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Пропуск загрузки фото для новости
    """
    try:
        # Получаем пользователя из базы данных
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.answer(
                "❌ Ошибка: пользователь не найден в базе данных.",
                reply_markup=get_admin_keyboard()
            )
            return

        data = await state.get_data()
        
        news_item = News(
            title=data["title"],
            content=data["content"],
            created_by=user.id  # Используем ID пользователя из базы данных
        )
        session.add(news_item)
        await session.commit()

        await state.clear()
        await message.answer(
            "✅ Новость успешно опубликована!",
            reply_markup=get_admin_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка при публикации новости без фото: {e}")
        await message.answer(
            "❌ Произошла ошибка при публикации новости. Попробуйте еще раз.",
            reply_markup=get_admin_keyboard()
        )


@router.callback_query(F.data.startswith("content_delete_news_"), is_content_callback)
async def delete_news_item(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Удаление новости
    """
    try:
        news_id = int(callback.data.split("_")[3])
        logger.info(f"Attempting to delete news #{news_id}")
        
        news_item = await session.get(News, news_id)
        
        if not news_item:
            await callback.answer("❌ Новость не найдена!")
            return

        # Удаляем фото с диска
        if news_item.image_url:
            try:
                await delete_photo(news_item.image_url)
            except Exception as e:
                logger.error(f"Ошибка при удалении фото: {e}")

        # Удаляем новость из базы данных
        await session.delete(news_item)
        await session.commit()
        logger.info(f"News #{news_id} successfully deleted")
        
        await callback.answer("✅ Новость успешно удалена!")
        
        # Получаем обновленный список новостей
        news_items = await session.execute(
            select(News).order_by(News.created_at.desc())
        )
        news_items = news_items.scalars().all()
        
        # Формируем текст сообщения
        message_text = (
            "<b>📢 Управление новостями</b>\n\n"
            "Здесь вы можете управлять новостями:\n"
            "• Добавлять новые публикации\n"
            "• Просматривать существующие\n" 
            "• Удалять неактуальные\n\n"
            f"<b>📊 Всего новостей:</b> {len(news_items)}\n"
            "<code>━━━━━━━━━━━━━━━━</code>\n\n"
            "Выберите действие:"
        )

        try:
            await callback.message.delete()
        except Exception as e:
            logger.debug(f"Не удалось удалить старое сообщение: {e}")

        await callback.message.answer(
            message_text,
            reply_markup=get_news_management_keyboard(news_items),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при удалении новости: {e}")
        log_error(e)
        await callback.answer(
            "❌ Произошла ошибка при удалении новости",
            show_alert=True
        )

@router.callback_query(F.data == "content_manage_news", is_content_callback)
async def manage_news(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Управление новостями через callback
    """
    try:
        logger.info("=== НАЧАЛО manage_news ===")
        logger.info(f"Callback data: {callback.data}")
        logger.info(f"User ID: {callback.from_user.id}")
        await callback.answer()
        
        news_items = await session.execute(
            select(News).order_by(News.created_at.desc())
        )
        news_items = news_items.scalars().all()
        # Отправляем новое сообщение вместо редактирования
        await callback.message.answer(
            "<b>📢 Управление новостями</b>\n\n"
            "Здесь вы можете управлять новостями:\n"
            "• Добавлять новые публикации\n" 
            "• Просматривать существующие\n"
            "• Удалять неактуальные\n\n"
            f"📊 Всего новостей: {len(news_items)}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "Выберите действие:",
            reply_markup=get_news_management_keyboard(news_items),
            parse_mode="HTML"
        )
        # Удаляем предыдущее сообщение
        try:
            await callback.message.delete()
        except Exception as e:
            logger.debug(f"Не удалось удалить старое сообщение: {e}")
        
        logger.info("=== КОНЕЦ manage_news ===")
    except Exception as e:
        logger.error(f"Ошибка в обработчике manage_news: {e}")
        log_error(e)
        # В случае ошибки тоже отправляем новое сообщение
        await callback.message.answer(
            "❌ Произошла ошибка при открытии управления новостями",
            reply_markup=get_content_management_keyboard()
        )

@router.callback_query(F.data == "content_manage_broadcasts", is_content_callback)
async def manage_broadcasts(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Управление рассылками через callback
    """
    try:
        logger.info("=== НАЧАЛО manage_broadcasts ===")
        logger.info(f"Callback data: {callback.data}")
        logger.info(f"User ID: {callback.from_user.id}")
        await callback.answer()
        
        # Используем только существующие колонки из модели Broadcast
        result = await session.execute(
            select(Broadcast).order_by(Broadcast.created_at.desc())
        )
        broadcasts = result.scalars().all()

        # Создаем новое сообщение вместо редактирования существующего
        await callback.message.answer(
            "<b>📨 Управление рассылками</b>\n\n"
            "Выберите действие:",
            reply_markup=get_broadcast_management_keyboard(broadcasts),
            parse_mode="HTML"
        )
        # Удаляем предыдущее сообщение
        await callback.message.delete()
        
        logger.info("=== КОНЕЦ manage_broadcasts ===")
    except Exception as e:
        logger.error(f"Ошибка в обработчике manage_broadcasts: {e}")
        log_error(e)
        await callback.message.answer(
            "<b>❌ Произошла ошибка при открытии управления рассылками</b>",
            reply_markup=get_content_management_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data == "content_back_to_content", is_content_callback)
async def back_to_content(callback: CallbackQuery) -> None:
    """
    Возврат в меню управления контентом
    """
    try:
        logger.info(f"DEBUG: Вызван обработчик back_to_content с callback_data={callback.data}")
        logger.info(f"Администратор {callback.from_user.id} вернулся в меню управления контентом")
        await callback.answer()
        
        await callback.message.edit_text(
            "<b>📢 Управление контентом</b>\n\n"
            "Выберите раздел:",
            reply_markup=get_content_management_keyboard(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в обработчике back_to_content: {e}")
        log_error(e)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при возврате в меню управления контентом</b>",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("content_news_"), is_content_callback)
async def view_news_item(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Просмотр отдельной новости
    """
    try:
        news_id = int(callback.data.split("_")[2])
        logger.info(f"Просмотр новости #{news_id}")
        
        # Получаем новость
        news = await session.get(News, news_id)
        if not news:
            await callback.answer("❌ Новость не найдена", show_alert=True)
            return
            
        # Форматируем дату
        created_at = news.created_at.strftime("%d.%m.%Y %H:%M")
        
        # Форматируем текст новости с экранированием
        news_text = (
            f"<b>📰 Новость #{news.id}</b>\n\n"
            f"<b>📌 {news.title}</b>\n"
            f"🕒 _{created_at}_\n\n"
            f"{news.content}"
        )
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать",
                    callback_data=f"edit_news_start_{news.id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"content_delete_news_{news.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Назад к новостям",
                    callback_data="content_manage_news"
                )
            ]
        ])
        
        try:
            # Пытаемся удалить предыдущее сообщение
            await callback.message.delete()
        except Exception as e:
            logger.debug(f"Не удалось удалить предыдущее сообщение: {e}")
        
        # Проверяем наличие изображения
        if news.image_url:
            # Проверяем длину текста для caption
            if len(news_text) > 1024:
                # Если текст слишком длинный, отправляем фото и текст отдельно
                full_image_path = f"src/{news.image_url}"
                if os.path.exists(full_image_path):
                    await callback.message.answer_photo(
                        photo=FSInputFile(full_image_path),
                        caption="<b>📰 Изображение к новости</b>",
                        parse_mode="HTML"
                    )
                await callback.message.answer(
                    news_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                # Если текст помещается в caption
                full_image_path = f"src/{news.image_url}"
                if os.path.exists(full_image_path):
                    await callback.message.answer_photo(
                        photo=FSInputFile(full_image_path),
                        caption=news_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    await callback.message.answer(
                        news_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
        else:
            # Если нет изображения, отправляем только текст
            await callback.message.answer(
                news_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре новости: {e}")
        await callback.answer(
            "❌ Произошла ошибка при загрузке новости",
            show_alert=True
        )

@router.callback_query(F.data.startswith("edit_news_title_"), is_content_callback)
async def edit_news_title(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Редактирование заголовка новости
    """
    try:
        # Очищаем предыдущее состояние
        await state.clear()
        
        # Извлекаем ID новости из callback_data
        news_id = int(callback.data.rsplit("_", 1)[1])
        
        # Получаем новость из базы данных
        news = await session.get(News, news_id)
        if not news:
            await callback.answer("❌ Новость не найдена", show_alert=True)
            return
        
        # Сохраняем данные в состояние
        await state.update_data(
            news_id=news_id,
            current_title=news.title,
            current_photo=news.image_url,  # Сохраняем текущее фото
            edit_mode="title_only"
        )
        
        # Устанавливаем состояние редактирования заголовка
        await state.set_state(NewsStates.edit_title)
        
        message_text = (
            f"<b>📝 Текущий заголовок:</b>\n{news.title}\n\n"
            "Введите новый заголовок:"
        )

        # Пытаемся удалить предыдущее сообщение
        try:
            await callback.message.delete()
        except Exception as e:
            logger.debug(f"Не удалось удалить старое сообщение: {e}")

        # Отправляем новое сообщение
        await callback.message.answer(
            message_text,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при редактировании заголовка: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@router.message(NewsStates.edit_title)
async def process_edit_news_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка ввода нового заголовка новости
    """
    try:
        data = await state.get_data()
        news_id = data.get('news_id')
        current_photo = data.get('current_photo')
        edit_mode = data.get('edit_mode')
        
        # Проверяем режим редактирования
        if not news_id or edit_mode != "title_only":
            await message.answer("❌ Некорректное состояние редактирования")
            await state.clear()
            await state.set_state(None)
            return
        
        # Получаем новость
        news = await session.get(News, news_id)
        if not news:
            await message.answer("❌ Новость не найдена")
            await state.clear()
            await state.set_state(None)
            return
        
        # Обновляем заголовок, сохраняя текущее фото
        news.title = message.text
        news.image_url = current_photo  # Явно сохраняем текущее фото
        await session.commit()
        
        await message.answer("✅ Заголовок успешно обновлен!")
        await show_news_after_edit(message, news, state)
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении заголовка: {e}")
        await message.answer("❌ Произошла ошибка при сохранении")
        await state.clear()
        await state.set_state(None)

@router.callback_query(F.data.startswith("edit_news_text_"), is_content_callback)
async def edit_news_content(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Редактирование текста новости
    """
    try:
        # Очищаем предыдущее состояние
        await state.clear()
        
        # Извлекаем ID новости из callback_data
        news_id = int(callback.data.rsplit("_", 1)[1])
        
        # Получаем новость из базы данных
        news = await session.get(News, news_id)
        if not news:
            await callback.answer("❌ Новость не найдена", show_alert=True)
            return
            
        # Сохраняем только необходимые данные в состояние
        await state.update_data(
            news_id=news_id,
            current_photo=news.image_url,  # Сохраняем текущее фото
            edit_mode="text_only"  # Явно указываем режим редактирования
        )
        
        # Устанавливаем состояние редактирования текста
        await state.set_state(NewsStates.edit_content)
        
        # Форматируем текущий текст для отображения
        current_text = (
            "<b>📄 Текущий текст:</b>\n"
            f"{news.content}\n\n"
            "Введите новый текст:"
        )
        
        # Пытаемся удалить предыдущее сообщение
        try:
            await callback.message.delete()
        except Exception as e:
            logger.debug(f"Не удалось удалить старое сообщение: {e}")

        # Отправляем новое сообщение
        await callback.message.answer(
            current_text,
            parse_mode="HTML"
        )
        
    except ValueError as e:
        logger.error(f"Ошибка при извлечении ID новости: {e}")
        await callback.answer("❌ Некорректный формат ID новости", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при редактировании текста: {e}")
        await callback.answer("❌ Произошла ошибка при редактировании", show_alert=True)

@router.message(NewsStates.edit_content)
async def process_edit_news_content(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка ввода нового текста новости
    """
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        news_id = data.get('news_id')
        current_photo = data.get('current_photo')
        edit_mode = data.get('edit_mode')
        
        # Проверяем режим редактирования
        if not news_id or edit_mode != "text_only":
            await message.answer("❌ Некорректное состояние редактирования")
            await state.clear()
            await state.set_state(None)
            return
        
        # Получаем новость
        news = await session.get(News, news_id)
        if not news:
            await message.answer("❌ Новость не найдена")
            await state.clear()
            await state.set_state(None)
            return
        
        # Обновляем только текст, сохраняя текущее фото
        news.content = message.text
        news.image_url = current_photo  # Явно сохраняем текущее фото
        await session.commit()
        
        # Показываем обновленную новость
        created_at = news.created_at.strftime("%d.%m.%Y %H:%M")
        news_text = (
            f"<b>📰 Новость #{news.id}</b>\n\n"
            f"<b>📌 {news.title}</b>\n"
            f"🕒 _{created_at}_\n\n"
            f"{news.content}\n\n"
            "✅ Текст новости успешно обновлен!"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Продолжить редактирование",
                    callback_data=f"edit_news_start_{news.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ К списку новостей",
                    callback_data="content_manage_news"
                )
            ]
        ])
        
        # Отправляем сообщение с обновленной новостью
        if news.image_url:
            full_image_path = f"src/{news.image_url}"
            if os.path.exists(full_image_path):
                if len(news_text) > 1024:
                    # Отправляем фото с коротким описанием
                    await message.answer_photo(
                        photo=FSInputFile(full_image_path),
                        caption="<b>📰 Изображение к новости</b>",
                        parse_mode="HTML"
                    )
                    # Отправляем полный текст с кнопками
                    await message.answer(
                        news_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    # Если текст помещается в caption, отправляем всё вместе
                    await message.answer_photo(
                        photo=FSInputFile(full_image_path),
                        caption=news_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
            else:
                # Если файл не найден, отправляем только текст с кнопками
                await message.answer(
                    news_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
        else:
            # Если нет изображения, отправляем только текст с кнопками
            await message.answer(
                news_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        
        # Полностью очищаем состояние
        await state.clear()
        await state.set_state(None)
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении текста: {e}")
        await message.answer("❌ Произошла ошибка при сохранении")
        await state.clear()
        await state.set_state(None)

@router.callback_query(F.data.startswith("edit_news_photo_"), is_content_callback)
async def edit_news_photo(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Редактирование фото новости
    """
    try:
        # Очищаем предыдущее состояние
        await state.clear()
        
        # Извлекаем ID новости из callback_data
        news_id = int(callback.data.rsplit("_", 1)[1])
        
        # Получаем новость из базы данных
        news = await session.get(News, news_id)
        if not news:
            await callback.answer("❌ Новость не найдена", show_alert=True)
            return
        
        # Сохраняем данные в состояние
        await state.update_data(
            news_id=news_id,
            edit_mode="photo_only"
        )
        
        # Устанавливаем состояние редактирования фото
        await state.set_state(NewsStates.edit_photo)
        
        message_text = (
            "<b>🖼 Отправьте новое изображение для новости</b>\n"
            "<i>(или отправьте /skip, чтобы удалить текущее изображение)</i>"
        )

        # Пытаемся удалить предыдущее сообщение
        try:
            await callback.message.delete()
        except Exception as e:
            logger.debug(f"Не удалось удалить старое сообщение: {e}")

        # Отправляем новое сообщение
        await callback.message.answer(message_text)
        
    except Exception as e:
        logger.error(f"Ошибка при редактировании фото: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@router.message(NewsStates.edit_photo, F.photo)
async def process_edit_news_photo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """
    Обработка загрузки нового фото для новости
    """
    try:
        data = await state.get_data()
        news_id = data.get('news_id')
        edit_mode = data.get('edit_mode')
        
        # Проверяем режим редактирования
        if not news_id or edit_mode != "photo_only":
            await message.answer("❌ Некорректное состояние редактирования")
            await state.clear()
            await state.set_state(None)
            return
        
        # Получаем новость
        news = await session.get(News, news_id)
        if not news:
            await message.answer("❌ Новость не найдена")
            await state.clear()
            await state.set_state(None)
            return
        
        # Удаляем старое фото если есть
        if news.image_url:
            await delete_photo(news.image_url)
        
        # Сохраняем новое фото
        photo = message.photo[-1]
        image_path, file_id = await save_photo_to_disk(photo, bot, "news")
        
        # Обновляем путь к фото
        news.image_url = image_path
        await session.commit()
        
        await message.answer("✅ Фото успешно обновлено!")
        await show_news_after_edit(message, news, state)
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении фото: {e}")
        await message.answer("❌ Произошла ошибка при сохранении")
        await state.clear()
        await state.set_state(None)

@router.message(NewsStates.edit_photo, Command("skip"))
async def skip_edit_news_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Удаление фото новости
    """
    try:
        data = await state.get_data()
        news_id = data.get('news_id')
        edit_mode = data.get('edit_mode')
        
        # Проверяем режим редактирования
        if not news_id or edit_mode != "photo_only":
            await message.answer("❌ Некорректное состояние редактирования")
            await state.clear()
            await state.set_state(None)
            return
        
        # Получаем новость
        news = await session.get(News, news_id)
        if not news:
            await message.answer("❌ Новость не найдена")
            await state.clear()
            await state.set_state(None)
            return
        
        # Удаляем фото если есть
        if news.image_url:
            await delete_photo(news.image_url)
            news.image_url = None
            await session.commit()
        
        await message.answer("✅ Фото удалено!")
        await show_news_after_edit(message, news, state)
        
    except Exception as e:
        logger.error(f"Ошибка при удалении фото: {e}")
        await message.answer("❌ Произошла ошибка при удалении фото")
        await state.clear()
        await state.set_state(None)

async def show_news_after_edit(message: Message, news: News, state: FSMContext) -> None:
    """
    Показ новости после редактирования
    """
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✏️ Продолжить редактирование",
                callback_data=f"edit_news_start_{news.id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="↩️ К списку новостей",
                callback_data="content_manage_news"
            )
        ]
    ])
    
    created_at = news.created_at.strftime("%d.%m.%Y %H:%M")
    news_text = (
        f"<b>📰 Новость #{news.id}</b>\n\n"
        f"<b>📌 {news.title}</b>\n"
        f"🕒 _{created_at}_\n\n"
        f"{news.content}"
    )
    
    if news.image_url:
        full_image_path = f"src/{news.image_url}"
        if os.path.exists(full_image_path):
            if len(news_text) > 1024:
                await message.answer_photo(
                    photo=FSInputFile(full_image_path),
                    caption="<b>📰 Изображение к новости</b>",
                    parse_mode="HTML"
                )
                await message.answer(
                    news_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                await message.answer_photo(
                    photo=FSInputFile(full_image_path),
                    caption=news_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
        else:
            await message.answer(
                news_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    else:
        await message.answer(
            news_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("edit_news_start_"), is_content_callback)
async def start_edit_news(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Начало процесса редактирования новости
    """
    try:
        # Извлекаем ID новости из callback_data
        news_id = int(callback.data.split("_")[3])
        
        # Получаем новость из базы данных
        news = await session.get(News, news_id)
        if not news:
            await callback.answer("❌ Новость не найдена", show_alert=True)
            return
        
        # Создаем клавиатуру для редактирования
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Заголовок",
                    callback_data=f"edit_news_title_{news_id}"
                ),
                InlineKeyboardButton(
                    text="📝 Текст",
                    callback_data=f"edit_news_text_{news_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🖼 Изображение",
                    callback_data=f"edit_news_photo_{news_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="content_manage_news"
                )
            ]
        ])
        
        # Форматируем текст сообщения
        created_at = news.created_at.strftime("%d.%m.%Y %H:%M")
        text = (
            f"<b>✏️ Редактирование новости #{news_id}</b>\n\n"
            f"<b>📌 Заголовок:</b> {news.title}\n"
            f"<b>🕒 Дата создания:</b> {created_at}\n\n"
            f"<b>📄 Текст:</b>\n{news.content}\n\n"
            "Выберите, что хотите отредактировать:"
        )
        
        # Если есть изображение, отправляем его с текстом
        if news.image_url:
            full_image_path = f"src/{news.image_url}"
            if os.path.exists(full_image_path):
                # Пытаемся удалить предыдущее сообщение
                try:
                    await callback.message.delete()
                except Exception as e:
                    logger.debug(f"Не удалось удалить старое сообщение: {e}")
                
                if len(text) > 1024:
                    # Если текст слишком длинный, отправляем фото и текст отдельно
                    await callback.message.answer_photo(
                        photo=FSInputFile(full_image_path),
                        caption="<b>📰 Изображение к новости</b>",
                        parse_mode="HTML"
                    )
                    await callback.message.answer(
                        text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    await callback.message.answer_photo(
                        photo=FSInputFile(full_image_path),
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
            else:
                await callback.message.edit_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
        else:
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Ошибка при начале редактирования новости: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

