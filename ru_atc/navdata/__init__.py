"""Навигация и частоты из файлов X-Plane 12.

Провайдер читает данные один раз в локальный кэш SQLite и дальше отвечает
из кэша. ``navigraph`` — заглушка: подписки нет, реализация не входит в этот выпуск.
"""
from .provider import NavDataProvider, make_provider
from .service import prepare_navdata

__all__ = ["NavDataProvider", "make_provider", "prepare_navdata"]
