"""
Модуль для работы со слот-машиной
Предоставляет функции генерации комбинаций и проверки выигрышей
"""

import random
import asyncio
from typing import Tuple, List, Dict
from aiogram.types import Message

# Символы и их веса для слот-машины (чем выше вес, тем чаще выпадает)
SLOT_SYMBOLS = [
    ('🍒', 75),  # Вишня - очень частая, дает доп попытки при 2+ совпадениях
    ('💎', 5),   # Алмаз - увеличен шанс главного приза
    ('🎉', 20),   # Праздник - увеличен шанс скидки
    ('🛢️', 25),   # Бочка - частый приз
    ('🚘', 30),   # Машина - средняя редкость
    ('🎁', 40)    # Подарок - частый приз
]

# Таблица призов
PRIZES = {
    ('💎', '💎', '💎'): "Сертификат на ремонт 1500₽",
    ('🎉', '🎉', '🎉'): "Скидка 10% на тонировку",
    ('🛢️', '🛢️', '🛢️'): "Бесплатная замена масла",
    ('🚘', '🚘', '🚘'): "Полировка фар в подарок",
    ('🎁', '🎁', '🎁'): "Автопорфюмерная продукция в подарок",
    ('🍒', '🍒', '🍒'): "2 дополнительные попытки"
}

def generate_slot_combination() -> Tuple[str, str, str]:
    """
    Генерирует случайную комбинацию символов для слот-машины
    с учетом их весов (вероятностей выпадения)
    
    Returns:
        Tuple[str, str, str]: Кортеж из трех символов-эмодзи
    """
    # Создаем взвешенный список символов
    weighted_symbols = []
    for symbol, weight in SLOT_SYMBOLS:
        weighted_symbols.extend([symbol] * weight)
    
    # Генерируем комбинацию из 3 случайных символов
    return tuple(random.choice(weighted_symbols) for _ in range(3))

def check_win(combination: Tuple[str, str, str]) -> Tuple[str, int]:
    """
    Проверяет комбинацию на выигрыш
    
    Args:
        combination: Кортеж из трех символов
        
    Returns:
        Tuple[str, int]: Сообщение о выигрыше и количество дополнительных попыток
    """
    # Проверяем наличие комбинации в таблице призов
    if combination in PRIZES:
        prize_text = PRIZES[combination]
        # Если выиграли дополнительные попытки
        extra_attempts = 2 if combination == ('🍒', '🍒', '🍒') else 0
        return prize_text, extra_attempts
    
    # Проверяем другие комбинации (все три одинаковых, но не из списка выше)
    if len(set(combination)) == 1:
        return "Скидка 5% на следующую услугу", 0
    
    # Проверяем на две вишни
    cherry_count = combination.count('🍒')
    if cherry_count >= 2:
        return "Дополнительная попытка", 1
    
    # Ничего не выиграли
    return "Повезет в следующий раз!", 0

def format_slot_result(combination: Tuple[str, str, str]) -> str:
    """
    Форматирует комбинацию для красивого вывода
    
    Args:
        combination: Кортеж из трех символов
        
    Returns:
        str: Отформатированная строка с символами
    """
    return " | ".join(combination)

async def animate_slot_machine(message: Message, final_combination: Tuple[str, str, str]) -> None:
    """
    Создает анимацию вращения слот-машины
    
    Args:
        message: Сообщение для обновления
        final_combination: Финальная комбинация символов
    """
    # Символы для анимации (используем все доступные символы)
    symbols = [symbol for symbol, _ in SLOT_SYMBOLS]
    
    # Создаем разные варианты текста для анимации
    spin_texts = [
        "🎰 Крутим барабаны",
        "🎰 Барабаны вращаются",
        "🎰 Испытываем удачу",
        "🎰 Ищем выигрышную комбинацию",
        "🎰 Магия слот-машины"
    ]
    
    # Эмодзи для индикации процесса
    process_emojis = ["⚡️", "✨", "💫", "🌟", "⭐️"]
    
    # Анимация вращения (5 кадров)
    for i in range(5):
        # Генерируем случайную комбинацию для анимации
        random_combination = tuple(random.choice(symbols) for _ in range(3))
        # Выбираем случайный текст и эмодзи
        spin_text = random.choice(spin_texts)
        emoji = random.choice(process_emojis)
        
        # Формируем текст с точками
        dots = "." * ((i % 3) + 1)
        animation_text = f"{spin_text}{dots}\n{emoji}\n\n{format_slot_result(random_combination)}"
        
        # Обновляем сообщение
        await message.edit_text(animation_text)
        await asyncio.sleep(0.5)
    
    # Эффект замедления перед финальной комбинацией
    slow_frames = []
    # Генерируем кадры для замедления, где символы останавливаются по очереди
    for i in range(3):
        combination = list(random.choice(symbols) for _ in range(3))
        # Фиксируем символы слева направо
        for j in range(i):
            combination[j] = final_combination[j]
        slow_frames.append(tuple(combination))
    
    # Показываем кадры замедления
    for i, combination in enumerate(slow_frames):
        await message.edit_text(
            f"🎰 Барабаны останавливаются{'.' * (i + 1)}\n💫\n\n{format_slot_result(combination)}"
        )
        await asyncio.sleep(0.7)
    
    # Показываем финальную комбинацию
    await message.edit_text(
        "🎰 Результат:\n✨\n\n" + 
        format_slot_result(final_combination)
    )

def generate_animation_frame() -> str:
    """
    Генерирует случайный кадр для анимации
    
    Returns:
        str: Строка с анимированными символами
    """
    symbols = [symbol for symbol, _ in SLOT_SYMBOLS]
    combination = tuple(random.choice(symbols) for _ in range(3))
    return format_slot_result(combination) 