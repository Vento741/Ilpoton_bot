# src/keyboards/client/__init__.py

from .client import (
    get_main_keyboard,
    get_contact_keyboard,
    get_services_keyboard,
    get_time_slots_keyboard,
    get_profile_keyboard
)

__all__ = [
    "get_main_keyboard",
    "get_contact_keyboard",
    "get_services_keyboard",
    "get_time_slots_keyboard",
    "get_profile_keyboard"
] 