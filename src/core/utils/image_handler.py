import os
from datetime import datetime
from aiogram import Bot
from aiogram.types import PhotoSize
from typing import Tuple

async def save_photo_to_disk(photo: PhotoSize, bot: Bot, folder: str) -> Tuple[str, str]:
    """
    Сохраняет фото в указанную папку и возвращает кортеж из пути к файлу и file_id
    
    Args:
        photo (PhotoSize): Объект фотографии от Telegram
        bot (Bot): Экземпляр бота
        folder (str): Папка для сохранения
        
    Returns:
        Tuple[str, str]: (относительный путь к файлу, file_id)
    """
    # Создаем папку если её нет
    os.makedirs(f"src/images/{folder}", exist_ok=True)
    
    # Генерируем уникальное имя файла
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{photo.file_id[-8:]}.jpg"
    filepath = f"src/images/{folder}/{filename}"
    
    # Скачиваем и сохраняем файл
    file = await bot.get_file(photo.file_id)
    await bot.download_file(file.file_path, filepath)
    
    # Возвращаем относительный путь и file_id
    return f"images/{folder}/{filename}", photo.file_id

async def delete_photo(filepath: str) -> None:
    """
    Удаляет фото с диска
    
    Args:
        filepath (str): Путь к файлу для удаления
    """
    full_path = f"src/{filepath}"
    if os.path.exists(full_path):
        os.remove(full_path)
        # Удаляем пустую директорию, если это была последняя фотография
        directory = os.path.dirname(full_path)
        if not os.listdir(directory):
            os.rmdir(directory)
