# src/handlers/client/__init__.py

from aiogram import Router
from . import base, profile, appointments, services, help, news, ratings, slot_machine
from .base import router as base_router
from .appointments import router as appointments_router
from .profile import router as profile_router
from .services import router as services_router
from .ratings import router as ratings_router
from .help import router as help_router
from .news import router as news_router
from .slot_machine import router as slot_machine_router

router = Router()

router.include_router(profile.router)
router.include_router(base.router)
router.include_router(appointments.router)
router.include_router(services.router)
router.include_router(ratings_router)
router.include_router(help_router)
router.include_router(news_router)
router.include_router(slot_machine_router)

__all__ = [
    "base_router",
    "appointments_router",
    "profile_router",
    "services_router",
    "help_router",
    "news_router",
    "ratings_router",
    "slot_machine_router",
    "router"
] 