# src/handlers/admin/slot_machine.py

from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from loguru import logger

from config.settings import settings
from database.models import Prize, User, SlotSpin
from keyboards.admin.admin import get_admin_inline_keyboard
from src.handlers.admin.appointments import STATUS_TRANSLATIONS

# Дополняем словарь статусов для слот-машины
STATUS_TRANSLATIONS.update({
    "PENDING": "Ожидает подтверждения",
    "CONFIRMED": "Подтвержден",
    "REJECTED": "Отклонен",
    "USED": "Использован"
})

router = Router(name='admin_slot_machine_router')

SLOT_MACHINE_PREFIXES = [
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

def is_slot_callback(callback: CallbackQuery) -> bool:
    """
    Проверяет, относится ли callback к управлению слот-машиной
    """
    return any(callback.data.startswith(prefix) for prefix in SLOT_MACHINE_PREFIXES)

router.callback_query.filter(is_slot_callback)

def admin_filter(callback: CallbackQuery) -> bool:
    """
    Фильтр для проверки прав администратора
    """
    return callback.from_user.id in settings.admin_ids

@router.callback_query(F.data == "admin_slot_machine_menu")
async def manage_slot_machine(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает меню управления слот-машиной
    """
    try:
        # Получаем статистику
        total_spins = await session.scalar(select(func.count(Prize.id)))
        pending_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "PENDING")
        )
        confirmed_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "CONFIRMED")
        )
        used_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "USED")
        )
        
        # Получаем последние 5 призов
        recent_prizes = await session.execute(
            select(Prize)
            .options(selectinload(Prize.user))
            .order_by(Prize.created_at.desc())
            .limit(5)
        )
        recent_prizes = recent_prizes.scalars().all()

        text = (
            "<b>🎰 Управление слот-машиной</b>\n\n"
            f"<b>📊 Статистика:</b>\n"
            f"• Всего игр: {total_spins}\n"
            f"• Ожидают подтверждения: {pending_prizes}\n"
            f"• Подтверждено призов: {confirmed_prizes}\n"
            f"• Выдано призов: {used_prizes}\n\n"
            "<b>🎁 Последние призы:</b>\n"
        )

        if recent_prizes:
            for prize in recent_prizes:
                # Выбираем эмодзи в зависимости от статуса
                status_emoji = {
                    "PENDING": "⏳",
                    "CONFIRMED": "✅",
                    "REJECTED": "❌",
                    "USED": "🎉"
                }.get(prize.status, "❓")
                
                text += (
                    f"{status_emoji} {prize.user.full_name} - {prize.prize_name}\n"
                    f"Комбинация: {prize.combination}\n"
                    f"Статус: {STATUS_TRANSLATIONS[prize.status]}\n\n"
                )
        else:
            text += "Пока нет призов\n"

        keyboard = [
            [
                InlineKeyboardButton(
                    text="⏳ Призы на подтверждение",
                    callback_data="admin_slot_prizes_page_1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Подтвержденные призы",
                    callback_data="admin_slot_confirmed_prizes_1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎉 Выданные призы",
                    callback_data="admin_slot_used_prizes_1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклоненные призы",
                    callback_data="admin_slot_rejected_prizes_1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Подробная статистика",
                    callback_data="admin_slot_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="back_to_admin"
                )
            ]
        ]

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при открытии управления слот-машиной: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке управления слот-машиной",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("admin_slot_prizes_page_"))
async def view_prizes_list(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает список призов с пагинацией
    """
    try:
        page = int(callback.data.split("_")[-1])
        items_per_page = 5

        # Получаем общее количество призов
        total_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "PENDING")
        )

        # Вычисляем общее количество страниц
        total_pages = (total_prizes + items_per_page - 1) // items_per_page

        # Получаем призы для текущей страницы
        prizes = await session.execute(
            select(Prize)
            .where(Prize.status == "PENDING")
            .options(selectinload(Prize.user))
            .order_by(Prize.created_at.desc())
            .offset((page - 1) * items_per_page)
            .limit(items_per_page)
        )
        prizes = prizes.scalars().all()

        if not prizes:
            text = "<b>🎁 Нет призов, ожидающих подтверждения</b>"
            keyboard = [[
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ]]
        else:
            text = "<b>🎁 Призы, ожидающие подтверждения:</b>\n\n"
            keyboard = []

            for prize in prizes:
                text += (
                    f"👤 #{prize.id} {prize.user.full_name}\n"
                    f"🎁 Приз: {prize.prize_name}\n"
                    f"🎰 Комбинация: {prize.combination}\n"
                    f"📅 {prize.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                )
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"👁 Просмотреть #{prize.id}",
                        callback_data=f"admin_slot_view_prize_{prize.id}"
                    )
                ])

            # Добавляем навигационные кнопки
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"admin_slot_prizes_page_{page-1}"
                ))
            nav_buttons.append(InlineKeyboardButton(
                text=f"📄 {page}/{total_pages}",
                callback_data="ignore"
            ))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"admin_slot_prizes_page_{page+1}"
                ))
            if nav_buttons:
                keyboard.append(nav_buttons)

            keyboard.append([
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ])

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре призов: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке списка призов",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("admin_slot_view_prize_"))
async def view_prize_details(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает детальную информацию о призе
    """
    try:
        prize_id = int(callback.data.split("_")[-1])
        
        # Получаем приз с информацией о пользователе
        result = await session.execute(
            select(Prize)
            .where(Prize.id == prize_id)
            .options(selectinload(Prize.user))
        )
        prize = result.scalar_one_or_none()
        
        if not prize:
            await callback.answer("❌ Приз не найден", show_alert=True)
            return

        # Формируем текст с информацией о призе
        text = (
            f"<b>🎁 Приз #{prize.id}</b>\n\n"
            f"<b>👤 Игрок:</b> {prize.user.full_name}\n"
            f"<b>🆔 ID игрока:</b> {prize.user.telegram_id}\n"
            f"<b>📱 Телефон:</b> {prize.user.phone_number or 'Не указан'}\n\n"
            f"<b>🎁 Приз:</b> {prize.prize_name}\n"
            f"<b>🎰 Комбинация:</b> {prize.combination}\n"
            f"<b>📅 Получен:</b> {prize.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"<b>📊 Статус:</b> {STATUS_TRANSLATIONS[prize.status]}\n"
        )

        # Добавляем информацию о подтверждении/отклонении
        if prize.status in ["CONFIRMED", "REJECTED"]:
            message_text = text + f"\n📝 <b>Дата {STATUS_TRANSLATIONS[prize.status].lower()}:</b> {prize.confirmed_at.strftime('%d.%m.%Y %H:%M')}\n"
            
            # Получаем информацию об администраторе
            admin_result = await session.execute(
                select(User).where(User.id == prize.confirmed_by)
            )
            admin = admin_result.scalar_one_or_none()
            admin_name = admin.full_name if admin else "Неизвестный администратор"
            
            if prize.status == "CONFIRMED":
                message_text += f"\n🎉 <b>Приз подтвержден!</b>\n"
                message_text += f"👨‍💼 Подтвердил: {admin_name}\n"
                message_text += f"📅 Дата: {prize.confirmed_at.strftime('%d.%m.%Y %H:%M')}\n"
            else:
                message_text += f"\n❌ <b>Приз отклонен!</b>\n"
                message_text += f"📝 Причина: {prize.reject_reason}\n"
                message_text += f"👨‍💼 Отклонил: {admin_name}\n"
                message_text += f"📅 Дата: {prize.confirmed_at.strftime('%d.%m.%Y %H:%M')}\n"
        else:
            message_text = text

        # Создаем клавиатуру с действиями
        keyboard = []
        if prize.status == "PENDING":
            keyboard.extend([
                [
                    InlineKeyboardButton(
                        text="✅ Подтвердить",
                        callback_data=f"admin_slot_confirm_{prize.id}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"admin_slot_reject_{prize.id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💬 Написать игроку",
                        url=f"tg://user?id={prize.user.telegram_id}"
                    )
                ]
            ])
        elif prize.status == "CONFIRMED":
            keyboard.extend([
                [
                    InlineKeyboardButton(
                        text="🎉 Отметить как выданный",
                        callback_data=f"admin_slot_mark_used_{prize.id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💬 Написать победителю",
                        url=f"tg://user?id={prize.user.telegram_id}"
                    )
                ]
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    text="💬 Написать победителю",
                    url=f"tg://user?id={prize.user.telegram_id}"
                )
            ])

        # Добавляем кнопку "Назад" с правильным возвратом в зависимости от статуса
        back_callback = {
            "PENDING": "admin_slot_prizes_page_1",
            "CONFIRMED": "admin_slot_confirmed_prizes_1",
            "REJECTED": "admin_slot_rejected_prizes_1",
            "USED": "admin_slot_used_prizes_1"
        }.get(prize.status, "admin_slot_machine_menu")

        keyboard.append([
            InlineKeyboardButton(
                text="↩️ Назад",
                callback_data=back_callback
            )
        ])

        await callback.message.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре деталей приза: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке информации о призе",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("admin_slot_confirm_"))
async def confirm_prize(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """
    Подтверждает выигрыш приза
    """
    try:
        prize_id = int(callback.data.split("_")[-1])  # Берем последний элемент после разделения
        
        # Получаем приз
        result = await session.execute(
            select(Prize)
            .where(Prize.id == prize_id)
            .options(selectinload(Prize.user))
        )
        prize = result.scalar_one_or_none()
        
        if not prize:
            await callback.answer("❌ Приз не найден", show_alert=True)
            return

        if prize.status != "PENDING":
            await callback.answer(
                f"❌ Приз уже {STATUS_TRANSLATIONS[prize.status].lower()}",
                show_alert=True
            )
            return

        # Получаем администратора
        admin_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        admin = admin_result.scalar_one_or_none()
        
        if not admin:
            await callback.answer("❌ Ошибка: администратор не найден", show_alert=True)
            return

        # Обновляем статус приза
        prize.status = "CONFIRMED"
        prize.confirmed_at = datetime.now()
        prize.confirmed_by = admin.id
        await session.commit()

        # Отправляем уведомление игроку
        try:
            notification = (
                f"🎉 <b>Ваш приз подтвержден!</b>\n\n"
                f"<b>Приз:</b> {prize.prize_name}\n"
                f"<b>Комбинация:</b> {prize.combination}\n\n"
                f"<b>Для получения приза:</b>\n"
                f"Обратитесь в наш автосервис по адресу: <b>ул.Калинина 128А к2</b>\n"
                f"При себе иметь документ, удостоверяющий личность.\n\n"
                f"<i>Приз действителен в течение 30 дней.</i>"
            )
            await bot.send_message(
                chat_id=prize.user.telegram_id,
                text=notification,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления игроку: {e}")

        await callback.answer("✅ Приз подтвержден!", show_alert=True)
        
        # Возвращаемся к списку призов
        await view_prizes_list(callback, session)

    except Exception as e:
        logger.error(f"Ошибка при подтверждении приза: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при подтверждении приза",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("admin_slot_reject_"), ~F.data.startswith("admin_slot_reject_reason_"))
async def reject_prize(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """
    Отклоняет выигрыш приза
    """
    try:
        prize_id = int(callback.data.split("_")[-1])
        
        # Получаем приз
        result = await session.execute(
            select(Prize)
            .where(Prize.id == prize_id)
            .options(selectinload(Prize.user))
        )
        prize = result.scalar_one_or_none()
        
        if not prize:
            await callback.answer("❌ Приз не найден", show_alert=True)
            return

        if prize.status != "PENDING":
            await callback.answer(
                f"❌ Приз уже {STATUS_TRANSLATIONS[prize.status].lower()}",
                show_alert=True
            )
            return

        # Показываем форму для ввода причины отклонения
        text = (
            f"<b>❌ Отклонение приза #{prize.id}</b>\n\n"
            f"<b>👤 Игрок:</b> {prize.user.full_name}\n"
            f"<b>🎁 Приз:</b> {prize.prize_name}\n"
            f"<b>🎰 Комбинация:</b> {prize.combination}\n\n"
            f"<b>Выберите причину отклонения:</b>"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    text="🚫 Неверная комбинация",
                    callback_data=f"admin_slot_reject_reason_{prize_id}_invalid_combination"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⛔️ Подозрение в мошенничестве",
                    callback_data=f"admin_slot_reject_reason_{prize_id}_fraud"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚠️ Технический сбой",
                    callback_data=f"admin_slot_reject_reason_{prize_id}_technical"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Отмена",
                    callback_data=f"admin_slot_view_prize_{prize_id}"
                )
            ]
        ]

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при отклонении приза: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при отклонении приза",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("admin_slot_reject_reason_"))
async def reject_prize_with_reason(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """
    Отклоняет приз с указанной причиной
    """
    try:
        # Парсим ID приза и причину из callback_data
        # Формат: admin_slot_reject_reason_1_fraud
        parts = callback.data.split("_")
        if len(parts) < 6:  # проверяем, что достаточно частей
            logger.error(f"Неверный формат callback_data: {callback.data}")
            await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
            return
            
        try:
            prize_id = int(parts[4])  # пятый элемент должен быть ID
            reason = parts[5]    # шестой элемент - причина
        except (IndexError, ValueError) as e:
            logger.error(f"Ошибка при извлечении ID приза: {e}")
            await callback.answer("❌ Ошибка при обработке данных", show_alert=True)
            return
        
        # Словарь с текстовыми описаниями причин
        reason_texts = {
            "invalid_combination": "Неверная комбинация",
            "fraud": "Подозрение в мошенничестве",
            "technical": "Технический сбой"
        }
        
        if reason not in reason_texts:
            logger.error(f"Неизвестная причина отклонения: {reason}")
            await callback.answer("❌ Неизвестная причина отклонения", show_alert=True)
            return
        
        # Получаем приз
        result = await session.execute(
            select(Prize)
            .where(Prize.id == prize_id)
            .options(selectinload(Prize.user))
        )
        prize = result.scalar_one_or_none()
        
        if not prize:
            await callback.answer("❌ Приз не найден", show_alert=True)
            return

        # Получаем администратора
        admin_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        admin = admin_result.scalar_one_or_none()
        
        if not admin:
            await callback.answer("❌ Ошибка: администратор не найден", show_alert=True)
            return

        # Обновляем статус приза
        prize.status = "REJECTED"
        prize.confirmed_at = datetime.now()
        prize.confirmed_by = admin.id
        prize.reject_reason = reason_texts.get(reason, "Другая причина")
        await session.commit()

        # Отправляем уведомление игроку
        try:
            notification = (
                f"❌ <b>К сожалению, ваш приз не подтвержден</b>\n\n"
                f"<b>Приз:</b> {prize.prize_name}\n"
                f"<b>Комбинация:</b> {prize.combination}\n"
                f"<b>Причина:</b> {reason_texts.get(reason, 'Не указана')}\n\n"
                f"Для уточнения деталей обратитесь к администратору."
            )
            await bot.send_message(
                chat_id=prize.user.telegram_id,
                text=notification,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления игроку: {e}")

        await callback.answer("❌ Приз отклонен", show_alert=True)
        
        # Создаем новый callback для возврата к списку призов
        new_callback = CallbackQuery(
            id=callback.id,
            from_user=callback.from_user,
            chat_instance=callback.chat_instance,
            message=callback.message,
            data="admin_slot_prizes_page_1"
        )
        
        # Возвращаемся к списку призов
        await view_prizes_list(new_callback, session)

    except Exception as e:
        logger.error(f"Ошибка при отклонении приза с причиной: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при отклонении приза",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "admin_slot_stats")
async def view_slot_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает подробную статистику слот-машины
    """
    try:
        # Получаем общую статистику из таблицы slot_spins
        total_spins = await session.scalar(select(func.count(SlotSpin.id)))
        
        # Получаем статистику выигрышей из таблицы prizes
        total_wins = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status.in_(["PENDING", "CONFIRMED", "USED"]))
        )
        
        # Статистика по статусам
        pending_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "PENDING")
        )
        confirmed_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "CONFIRMED")
        )
        rejected_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "REJECTED")
        )
        used_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "USED")
        )
        
        # Статистика за последние 24 часа
        day_ago = datetime.now() - timedelta(days=1)
        spins_24h = await session.scalar(
            select(func.count(SlotSpin.id))
            .where(SlotSpin.created_at >= day_ago)
        )
        wins_24h = await session.scalar(
            select(func.count(Prize.id))
            .where(
                Prize.created_at >= day_ago,
                Prize.status.in_(["PENDING", "CONFIRMED", "USED"])
            )
        )

        # Статистика за последнюю неделю
        week_ago = datetime.now() - timedelta(days=7)
        spins_week = await session.scalar(
            select(func.count(SlotSpin.id))
            .where(SlotSpin.created_at >= week_ago)
        )
        wins_week = await session.scalar(
            select(func.count(Prize.id))
            .where(
                Prize.created_at >= week_ago,
                Prize.status.in_(["PENDING", "CONFIRMED", "USED"])
            )
        )

        # Получаем дату первой игры
        first_game_result = await session.execute(
            select(SlotSpin.created_at)
            .order_by(SlotSpin.created_at.asc())
            .limit(1)
        )
        first_game_date = first_game_result.scalar_one_or_none()
        
        if first_game_date:
            days_since_start = (datetime.now() - first_game_date).days
            avg_spins_per_day = total_spins / max(days_since_start, 1)
            avg_wins_per_day = total_wins / max(days_since_start, 1)
        else:
            days_since_start = 0
            avg_spins_per_day = 0
            avg_wins_per_day = 0

        # Формируем текст со статистикой
        text = (
            "<b>📊 Подробная статистика слот-машины</b>\n\n"
            f"<b>🎮 Общая статистика:</b>\n"
            f"• Всего игр: {total_spins}\n"
            f"• Всего выигрышей: {total_wins}\n"
        )
        
        # Добавляем процент выигрышей только если были игры
        if total_spins > 0:
            text += f"• Процент выигрышей: {(total_wins/total_spins*100):.1f}%\n"
        else:
            text += "• Процент выигрышей: 0%\n"
            
        text += (
            f"• Дней работы: {days_since_start}\n"
            f"• Среднее кол-во игр в день: {avg_spins_per_day:.1f}\n"
            f"• Среднее кол-во выигрышей в день: {avg_wins_per_day:.1f}\n\n"
            
            f"<b>📈 За последние 24 часа:</b>\n"
            f"• Игр: {spins_24h}\n"
            f"• Выигрышей: {wins_24h}\n"
        )
        
        # Добавляем процент выигрышей за 24 часа только если были игры
        if spins_24h > 0:
            text += f"• Процент выигрышей: {(wins_24h/spins_24h*100):.1f}%\n\n"
        else:
            text += "• Процент выигрышей: 0%\n\n"
            
        text += (
            f"<b>📊 За последнюю неделю:</b>\n"
            f"• Игр: {spins_week}\n"
            f"• Выигрышей: {wins_week}\n"
        )
        
        # Добавляем процент выигрышей за неделю только если были игры
        if spins_week > 0:
            text += f"• Процент выигрышей: {(wins_week/spins_week*100):.1f}%\n\n"
        else:
            text += "• Процент выигрышей: 0%\n\n"
            
        text += (
            f"<b>🎁 Статус призов:</b>\n"
            f"• Ожидают подтверждения: {pending_prizes}\n"
            f"• Подтверждено: {confirmed_prizes}\n"
            f"• Отклонено: {rejected_prizes}\n"
            f"• Выдано: {used_prizes}\n"
        )
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика по призам",
                    callback_data="admin_slot_prize_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при получении статистики слот-машины: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при получении статистики", show_alert=True)

@router.callback_query(F.data == "admin_slot_prize_stats")
async def view_prize_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает детальную статистику по призам
    """
    try:
        # Статистика по призам с разбивкой по статусам
        prize_stats = await session.execute(
            select(
                Prize.prize_name,
                Prize.status,
                func.count(Prize.id).label('count')
            )
            .group_by(Prize.prize_name, Prize.status)
        )
        prize_stats = prize_stats.all()
        
        # Группируем статистику по призам
        prize_breakdown = {}
        most_common_prize = {"name": "", "count": 0}
        most_issued_prize = {"name": "", "count": 0}
        
        for prize_name, status, count in prize_stats:
            if prize_name not in prize_breakdown:
                prize_breakdown[prize_name] = {
                    'total': 0,
                    'pending': 0,
                    'confirmed': 0,
                    'rejected': 0,
                    'used': 0
                }
            prize_breakdown[prize_name]['total'] += count
            if prize_breakdown[prize_name]['total'] > most_common_prize["count"]:
                most_common_prize["name"] = prize_name
                most_common_prize["count"] = prize_breakdown[prize_name]['total']
                
            if status == "PENDING":
                prize_breakdown[prize_name]['pending'] += count
            elif status == "CONFIRMED":
                prize_breakdown[prize_name]['confirmed'] += count
            elif status == "REJECTED":
                prize_breakdown[prize_name]['rejected'] += count
            elif status == "USED":
                prize_breakdown[prize_name]['used'] += count
                if prize_breakdown[prize_name]['used'] > most_issued_prize["count"]:
                    most_issued_prize["name"] = prize_name
                    most_issued_prize["count"] = prize_breakdown[prize_name]['used']

        # Формируем текст со статистикой призов
        text = (
            "<b>🎁 Статистика по призам</b>\n\n"
            f"<b>🏆 Топ призов:</b>\n"
            f"• Самый частый приз: {most_common_prize['name']} ({most_common_prize['count']} раз)\n"
            f"• Чаще всего выдан: {most_issued_prize['name']} ({most_issued_prize['count']} раз)\n\n"
            f"<b>📋 Детальная статистика:</b>\n\n"
            "<b>💎 Сертификат на ремонт 1500₽:</b>\n"
            f"{get_prize_stats(prize_breakdown, 'Сертификат на ремонт 1500₽')}\n"
            "<b>🎉 Скидка 10% на тонировку:</b>\n"
            f"{get_prize_stats(prize_breakdown, 'Скидка 10% на тонировку')}\n"
            "<b>🛢️ Бесплатная замена масла:</b>\n"
            f"{get_prize_stats(prize_breakdown, 'Бесплатная замена масла')}\n"
            "<b>🚗 Полировка фар в подарок:</b>\n"
            f"{get_prize_stats(prize_breakdown, 'Полировка фар в подарок')}\n"
            "<b>🎁 Автопорфюмерная продукция в подарок:</b>\n"
            f"{get_prize_stats(prize_breakdown, 'Автопорфюмерная продукция в подарок')}\n"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    text="📊 Общая статистика",
                    callback_data="admin_slot_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ]
        ]

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре статистики призов: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке статистики призов",
            reply_markup=get_admin_inline_keyboard()
        )

def get_prize_stats(prize_breakdown: dict, prize_name: str) -> str:
    """
    Форматирует статистику для конкретного приза
    """
    stats = prize_breakdown.get(prize_name, {
        'total': 0,
        'pending': 0,
        'confirmed': 0,
        'rejected': 0,
        'used': 0
    })
    
    success_rate = (stats['confirmed'] + stats['used']) / stats['total'] * 100 if stats['total'] > 0 else 0
    
    return (
        f"• Всего: {stats['total']}\n"
        f"• Ожидает: {stats['pending']}\n"
        f"• Подтверждено: {stats['confirmed']}\n"
        f"• Выдано: {stats['used']}\n"
        f"• Отклонено: {stats['rejected']}\n"
        f"• Процент успеха: {success_rate:.1f}%"
    )

@router.callback_query(F.data.startswith("admin_slot_mark_used_"))
async def mark_prize_used(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    """
    Отмечает приз как использованный/выданный
    """
    try:
        # Извлекаем ID приза из callback_data
        prize_id = int(callback.data.split("_")[-1])
        
        # Получаем информацию о призе
        prize_result = await session.execute(
            select(Prize)
            .where(Prize.id == prize_id)
            .options(selectinload(Prize.user))
        )
        prize = prize_result.scalar_one_or_none()
        
        if not prize:
            await callback.answer("❌ Приз не найден", show_alert=True)
            return
        
        # Проверяем статус приза
        if prize.status != "CONFIRMED":
            await callback.answer(
                f"❌ Нельзя отметить как выданный приз со статусом {prize.status}",
                show_alert=True
            )
            return
        
        # Получаем администратора
        admin_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        admin = admin_result.scalar_one_or_none()
        
        if not admin:
            await callback.answer("❌ Ошибка: администратор не найден", show_alert=True)
            return
        
        # Обновляем статус приза
        prize.status = "USED"
        prize.used_at = datetime.now()
        prize.admin_comment = f"Приз выдан администратором {admin.full_name}"
        
        await session.commit()
        
        # Отправляем уведомление пользователю
        try:
            await bot.send_message(
                chat_id=prize.user.telegram_id,
                text=(
                    f"🎉 <b>Ваш приз был успешно выдан!</b>\n\n"
                    f"<b>Приз:</b> {prize.prize_name}\n"
                    f"<b>Дата выдачи:</b> {prize.used_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"Спасибо за участие в розыгрыше! Ждем вас снова! 🎰"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {prize.user.telegram_id}: {e}")
        
        # Обновляем сообщение с информацией о призе
        text = (
            f"✅ <b>Приз выдан!</b>\n\n"
            f"👤 Игрок: {prize.user.full_name}\n"
            f"🆔 ID: {prize.user.telegram_id}\n"
            f"🎁 Приз: {prize.prize_name}\n"
            f"🎰 Комбинация: {prize.combination}\n"
            f"📅 Выдан: {prize.used_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"👨‍💼 Выдал: {admin.full_name}"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Написать победителю",
                    url=f"tg://user?id={prize.user.telegram_id}"
                ),
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ]
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer("✅ Приз отмечен как выданный!", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка при отметке приза как выданного: {e}")
        await callback.answer("❌ Произошла ошибка при выполнении операции", show_alert=True)
        await session.rollback()

@router.callback_query(F.data.startswith("admin_slot_confirmed_prizes_"))
async def view_confirmed_prizes(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает список подтвержденных призов с пагинацией
    """
    try:
        page = int(callback.data.split("_")[-1])
        items_per_page = 5

        # Получаем общее количество призов
        total_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "CONFIRMED")
        )

        # Вычисляем общее количество страниц
        total_pages = (total_prizes + items_per_page - 1) // items_per_page

        # Получаем призы для текущей страницы
        prizes = await session.execute(
            select(Prize)
            .where(Prize.status == "CONFIRMED")
            .options(selectinload(Prize.user))
            .order_by(Prize.created_at.desc())
            .offset((page - 1) * items_per_page)
            .limit(items_per_page)
        )
        prizes = prizes.scalars().all()

        if not prizes:
            text = "<b>🎁 Нет подтвержденных призов</b>"
            keyboard = [[
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ]]
        else:
            text = "<b>✅ Подтвержденные призы:</b>\n\n"
            keyboard = []

            for prize in prizes:
                text += (
                    f"👤 #{prize.id} {prize.user.full_name}\n"
                    f"🎁 Приз: {prize.prize_name}\n"
                    f"🎰 Комбинация: {prize.combination}\n"
                    f"📅 Подтвержден: {prize.confirmed_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                )
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"👁 Просмотреть #{prize.id}",
                        callback_data=f"admin_slot_view_prize_{prize.id}"
                    )
                ])

            # Добавляем навигационные кнопки
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"admin_slot_confirmed_prizes_{page-1}"
                ))
            nav_buttons.append(InlineKeyboardButton(
                text=f"📄 {page}/{total_pages}",
                callback_data="ignore"
            ))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"admin_slot_confirmed_prizes_{page+1}"
                ))
            if nav_buttons:
                keyboard.append(nav_buttons)

            keyboard.append([
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ])

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре подтвержденных призов: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке списка призов",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("admin_slot_used_prizes_"))
async def view_used_prizes(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает список выданных призов с пагинацией
    """
    try:
        page = int(callback.data.split("_")[-1])
        items_per_page = 5

        # Получаем общее количество призов
        total_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "USED")
        )

        # Вычисляем общее количество страниц
        total_pages = (total_prizes + items_per_page - 1) // items_per_page

        # Получаем призы для текущей страницы
        prizes = await session.execute(
            select(Prize)
            .where(Prize.status == "USED")
            .options(selectinload(Prize.user))
            .order_by(Prize.created_at.desc())
            .offset((page - 1) * items_per_page)
            .limit(items_per_page)
        )
        prizes = prizes.scalars().all()

        if not prizes:
            text = "<b>🎁 Нет выданных призов</b>"
            keyboard = [[
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ]]
        else:
            text = "<b>🎉 Выданные призы:</b>\n\n"
            keyboard = []

            for prize in prizes:
                text += (
                    f"👤 #{prize.id} {prize.user.full_name}\n"
                    f"🎁 Приз: {prize.prize_name}\n"
                    f"🎰 Комбинация: {prize.combination}\n"
                    f"📅 Выдан: {prize.used_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                )
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"👁 Просмотреть #{prize.id}",
                        callback_data=f"admin_slot_view_prize_{prize.id}"
                    )
                ])

            # Добавляем навигационные кнопки
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"admin_slot_used_prizes_{page-1}"
                ))
            nav_buttons.append(InlineKeyboardButton(
                text=f"📄 {page}/{total_pages}",
                callback_data="ignore"
            ))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"admin_slot_used_prizes_{page+1}"
                ))
            if nav_buttons:
                keyboard.append(nav_buttons)

            keyboard.append([
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ])

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре выданных призов: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке списка призов",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("admin_slot_rejected_prizes_"))
async def view_rejected_prizes(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает список отклоненных призов с пагинацией
    """
    try:
        page = int(callback.data.split("_")[-1])
        items_per_page = 5

        # Получаем общее количество призов
        total_prizes = await session.scalar(
            select(func.count(Prize.id))
            .where(Prize.status == "REJECTED")
        )

        # Вычисляем общее количество страниц
        total_pages = (total_prizes + items_per_page - 1) // items_per_page

        # Получаем призы для текущей страницы
        prizes = await session.execute(
            select(Prize)
            .where(Prize.status == "REJECTED")
            .options(selectinload(Prize.user))
            .order_by(Prize.created_at.desc())
            .offset((page - 1) * items_per_page)
            .limit(items_per_page)
        )
        prizes = prizes.scalars().all()

        if not prizes:
            text = "<b>🎁 Нет отклоненных призов</b>"
            keyboard = [[
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ]]
        else:
            text = "<b>❌ Отклоненные призы:</b>\n\n"
            keyboard = []

            for prize in prizes:
                text += (
                    f"👤 #{prize.id} {prize.user.full_name}\n"
                    f"🎁 Приз: {prize.prize_name}\n"
                    f"🎰 Комбинация: {prize.combination}\n"
                    f"📅 Отклонен: {prize.confirmed_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📝 Причина: {prize.reject_reason}\n\n"
                )
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"👁 Просмотреть #{prize.id}",
                        callback_data=f"admin_slot_view_prize_{prize.id}"
                    )
                ])

            # Добавляем навигационные кнопки
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"admin_slot_rejected_prizes_{page-1}"
                ))
            nav_buttons.append(InlineKeyboardButton(
                text=f"📄 {page}/{total_pages}",
                callback_data="ignore"
            ))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"admin_slot_rejected_prizes_{page+1}"
                ))
            if nav_buttons:
                keyboard.append(nav_buttons)

            keyboard.append([
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="admin_slot_machine_menu"
                )
            ])

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре отклоненных призов: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке списка призов",
            reply_markup=get_admin_inline_keyboard()
        ) 