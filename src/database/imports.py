"""
Модуль с импортами для базы данных.
Используется как в самом боте, так и в миграциях.
"""
import os
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в PYTHONPATH
root_dir = str(Path(__file__).parent.parent.parent)
sys.path.append(root_dir)

try:
    from config.settings import settings
except ImportError:
    from src.config.settings import settings

__all__ = ['settings'] 