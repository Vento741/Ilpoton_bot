# src/handlers/client/news.py

import os
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from loguru import logger

from database.models import News
from keyboards.client.client import get_main_keyboard
from core.utils.logger import log_error

router = Router()

def get_news_keyboard(current_index: int, total_news: int) -> InlineKeyboardMarkup:
    """
    Создает улучшенную клавиатуру для навигации по новостям
    """
    keyboard = []
    nav_row = []
    
    # Навигационные кнопки
    if current_index > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="⏮",
                callback_data="news_first"
            )
        )
        nav_row.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"news_prev_{current_index}"
            )
        )
    
    # Индикатор позиции
    position_text = f"📰 {current_index + 1}/{total_news}"
    nav_row.append(
        InlineKeyboardButton(
            text=position_text,
            callback_data="news_position"
        )
    )
    
    if current_index < total_news - 1:
        nav_row.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=f"news_next_{current_index}"
            )
        )
        nav_row.append(
            InlineKeyboardButton(
                text="⏭",
                callback_data="news_last"
            )
        )
    
    keyboard.append(nav_row)
    
    # Кнопка для перехода в канал
    channel_row = [
        InlineKeyboardButton(
            text="📢 Наш Telegram канал",
            url="https://t.me/ILPOavtoTON"
        )
    ]
    keyboard.append(channel_row)
    
    # Дополнительные кнопки управления
    control_row = []
    control_row.append(
        InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data="refresh_news"
        )
    )
    control_row.append(
        InlineKeyboardButton(
            text="🔙 Меню",
            callback_data="back_to_main"
        )
    )
    keyboard.append(control_row)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def format_news_date(date: datetime) -> str:
    """
    Форматирует дату новости в красивый вид
    """
    now = datetime.now()
    delta = now - date
    
    if delta.days == 0:
        if delta.seconds < 3600:
            minutes = delta.seconds // 60
            return f"{minutes} {'минуту' if minutes == 1 else 'минут'} назад"
        else:
            hours = delta.seconds // 3600
            return f"{hours} {'час' if hours == 1 else 'часов'} назад"
    elif delta.days == 1:
        return "Вчера"
    elif delta.days == 2:
        return "Позавчера"
    else:
        # Используем более простой формат даты
        return date.strftime("%d %m %Y")

# Константы для ограничений Telegram
MAX_CAPTION_LENGTH = 1024
MAX_MESSAGE_LENGTH = 4096

def truncate_text(text: str, max_length: int) -> str:
    """
    Обрезает текст до максимальной длины, добавляя '...' в конце
    """
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

async def show_news_item(message: Message | CallbackQuery, session: AsyncSession, index: int = 0) -> None:
    """
    Показывает одну новость с указанным индексом
    """
    try:
        # Получаем общее количество новостей
        total_news = await session.scalar(
            select(func.count()).select_from(News)
        )
        
        if total_news == 0:
            text = "<b>📢 Новости</b>\n\nВ данный момент новостей нет. Следите за обновлениями!"
            if isinstance(message, CallbackQuery):
                await message.message.edit_text(
                    text,
                    reply_markup=get_news_keyboard(0, 1),
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    text,
                    reply_markup=get_news_keyboard(0, 1),
                    parse_mode="HTML"
                )
            return

        # Получаем новость по индексу
        news_item = await session.execute(
            select(News)
            .order_by(News.created_at.desc())
            .offset(index)
            .limit(1)
        )
        news_item = news_item.scalar_one_or_none()
        
        if not news_item:
            await message.answer("❌ Новость не найдена")
            return
        
        # Форматируем сообщение с HTML тегами
        date_str = format_news_date(news_item.created_at)
        news_text = (
            f"📌 <b>{news_item.title}</b>\n\n"
            f"🕒 <i>{date_str}</i>\n\n"
            f"{news_item.content}"
        )
        
        # Проверяем длину текста и обрезаем при необходимости
        if news_item.image_url:
            news_text = truncate_text(news_text, MAX_CAPTION_LENGTH)
        else:
            news_text = truncate_text(news_text, MAX_MESSAGE_LENGTH)
        
        # Создаем клавиатуру
        keyboard = get_news_keyboard(index, total_news)
        
        # Отправляем или редактируем сообщение
        if isinstance(message, CallbackQuery):
            try:
                if news_item.image_url:
                    # Сначала пытаемся удалить старое сообщение
                    try:
                        await message.message.delete()
                    except Exception as e:
                        logger.debug(f"Не удалось удалить старое сообщение: {e}")
                    
                    # Отправляем новое сообщение с фото
                    full_image_path = f"src/{news_item.image_url}"
                    if os.path.exists(full_image_path):
                        await message.message.answer_photo(
                            photo=FSInputFile(full_image_path),
                            caption=news_text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                    else:
                        await message.message.answer(
                            news_text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                else:
                    # Для сообщений без фото
                    try:
                        await message.message.edit_text(
                            news_text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.debug(f"Не удалось отредактировать сообщение: {e}")
                        # Если не удалось отредактировать, отправляем новое
                        try:
                            await message.message.delete()
                        except Exception:
                            pass
                        await message.message.answer(
                            news_text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
            except Exception as e:
                logger.error(f"Ошибка при обновлении новости: {e}")
                await message.message.answer(
                    "❌ Произошла ошибка при загрузке новости",
                    reply_markup=get_main_keyboard()
                )
        else:
            # Для первого показа новости
            if news_item.image_url:
                full_image_path = f"src/{news_item.image_url}"
                if os.path.exists(full_image_path):
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
                
    except Exception as e:
        log_error(e)
        error_text = "❌ Произошла ошибка при загрузке новости"
        if isinstance(message, CallbackQuery):
            await message.message.answer(
                error_text,
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(
                error_text,
                reply_markup=get_main_keyboard()
            )

@router.message(F.text == "📢 Новости")
async def show_news_command(message: Message, session: AsyncSession) -> None:
    """
    Показывает последнюю новость
    """
    try:
        logger.info(f"Пользователь {message.from_user.id} открыл новости")
        
        # Получаем общее количество новостей
        total_news = await session.scalar(
            select(func.count()).select_from(News)
        )
        
        if total_news == 0:
            await message.answer(
                "<b>📢 Новости</b>\n\nВ данный момент новостей нет. Следите за обновлениями!",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
            return

        # Получаем последнюю новость
        news_item = await session.execute(
            select(News)
            .order_by(News.created_at.desc())
            .limit(1)
        )
        news_item = news_item.scalar_one_or_none()
        
        if not news_item:
            await message.answer(
                "❌ Ошибка при загрузке новостей",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Форматируем сообщение с HTML тегами
        date_str = format_news_date(news_item.created_at)
        news_text = (
            f"📌 <b>{news_item.title}</b>\n\n"
            f"🕒 <i>{date_str}</i>\n\n"
            f"{news_item.content}"
        )
        
        # Проверяем длину текста и обрезаем при необходимости
        if news_item.image_url:
            news_text = truncate_text(news_text, MAX_CAPTION_LENGTH)
        else:
            news_text = truncate_text(news_text, MAX_MESSAGE_LENGTH)
        
        # Создаем клавиатуру
        keyboard = get_news_keyboard(0, total_news)
        
        # Отправляем сообщение
        if news_item.image_url:
            full_image_path = f"src/{news_item.image_url}"
            if os.path.exists(full_image_path):
                await message.answer_photo(
                    photo=FSInputFile(full_image_path),
                    caption=news_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                logger.warning(f"Image file not found: {full_image_path}")
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
            
    except Exception as e:
        logger.error(f"Error in show_news_command: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при загрузке новостей",
            reply_markup=get_main_keyboard()
        )

@router.callback_query(F.data.startswith("news_next_"))
async def show_next_news(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает следующую новость
    """
    try:
        current_index = int(callback.data.split("_")[2])
        await callback.answer()
        await show_news_item(callback, session, current_index + 1)
    except Exception as e:
        logger.error(f"Error in show_next_news: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке следующей новости", show_alert=True)

@router.callback_query(F.data.startswith("news_prev_"))
async def show_prev_news(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает предыдущую новость
    """
    try:
        current_index = int(callback.data.split("_")[2])
        await callback.answer()
        await show_news_item(callback, session, current_index - 1)
    except Exception as e:
        logger.error(f"Error in show_prev_news: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке предыдущей новости", show_alert=True)

@router.callback_query(F.data == "news_first")
async def show_first_news(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает первую (самую свежую) новость
    """
    try:
        await callback.answer()
        await show_news_item(callback, session, 0)
    except Exception as e:
        logger.error(f"Error in show_first_news: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке первой новости", show_alert=True)

@router.callback_query(F.data == "news_last")
async def show_last_news(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает последнюю (самую старую) новость
    """
    try:
        total_news = await session.scalar(select(func.count()).select_from(News))
        await callback.answer()
        await show_news_item(callback, session, total_news - 1)
    except Exception as e:
        logger.error(f"Error in show_last_news: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке последней новости", show_alert=True)

@router.callback_query(F.data == "news_position")
async def show_position_info(callback: CallbackQuery) -> None:
    """
    Показывает информацию о текущей позиции в списке новостей
    """
    await callback.answer("Позиция в списке новостей")

@router.callback_query(F.data == "refresh_news")
async def refresh_news(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Обновляет текущую новость
    """
    try:
        await callback.answer("🔄 Обновляем...")
        await show_news_item(callback, session, 0)
    except Exception as e:
        logger.error(f"Error in refresh_news: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при обновлении новостей", show_alert=True)