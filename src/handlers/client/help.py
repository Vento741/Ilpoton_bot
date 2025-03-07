from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode

from core.utils.constants import MAIN_HELP_TEXT, CONTACT_TEXT, LOCATION_TEXT

router = Router()

@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def show_help(message: Message):
    """
    Показывает справочную информацию
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📞 Связаться с администратором",
                    callback_data="contact_admin"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📍 Показать на карте",
                    callback_data="show_location"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Вернуться в главное меню",
                    callback_data="back_to_main"
                )
            ]
        ]
    )
    
    await message.answer(
        MAIN_HELP_TEXT,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "contact_admin")
async def contact_admin(callback_query):
    """
    Показывает контакты администратора
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↩️ Назад к помощи",
                    callback_data="back_to_help"
                )
            ]
        ]
    )
    
    await callback_query.message.edit_text(
        CONTACT_TEXT,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "show_location")
async def show_location(callback_query):
    """
    Показывает адрес и схему проезда
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗺 Открыть в Google Maps",
                    url="https://maps.app.goo.gl/HYDtZBGgvHGJL7Uw8"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧭 Проложить маршрут (Яндекс Навигатор)",
                    url="https://yandex.ru/maps/-/CHBSAY9K"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Назад к помощи",
                    callback_data="back_to_help"
                )
            ]
        ]
    )
    
    await callback_query.message.edit_text(
        LOCATION_TEXT,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "back_to_help")
async def back_to_help(callback_query):
    """
    Возвращает к основному меню помощи
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📞 Связаться с администратором",
                    callback_data="contact_admin"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📍 Показать на карте",
                    callback_data="show_location"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Вернуться в главное меню",
                    callback_data="back_to_main"
                )
            ]
        ]
    )
    
    await callback_query.message.edit_text(
        MAIN_HELP_TEXT,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    ) 