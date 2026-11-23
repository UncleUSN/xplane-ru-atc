"""Откуда брать навигацию. Сейчас работает только X-Plane, Navigraph — интерфейс."""
from __future__ import annotations

from typing import Callable, Optional, Protocol

Progress = Callable[[str, float], None]


class NavDataProvider(Protocol):
    name: str

    def available(self) -> bool:
        """Можно ли реально прочитать данные этого провайдера."""

    def explain(self) -> str:
        """Одна-две фразы в журнал и в окно."""


class NavigraphProvider:
    """Заглушка. Ключ ``navdata.provider: navigraph`` зарезервирован.

    Подписка Navigraph в эту версию не входит: нет ни загрузки цикла,
    ни формата их поставки сверх того, что X-Plane и так читает из ``Custom Data``,
    если пользователь когда-нибудь положит файлы сам. Пока ключ включён,
    программа пишет пояснение и читает данные X-Plane.
    """

    name = "navigraph"

    def available(self) -> bool:
        return False

    def explain(self) -> str:
        return ("navdata.provider: navigraph — подписка Navigraph не подключена "
                "(заглушка, отдельной загрузки цикла нет). "
                "Если в Custom Data уже лежат файлы цикла, X-Plane их подхватит как обычные "
                "файлы симулятора. Иначе берутся Resources/default data и yaml.")


class NullProvider:
    name = "off"

    def available(self) -> bool:
        return False

    def explain(self) -> str:
        return ("Навигационные данные выключены (navdata.provider: off). "
                "Частоты и секторы — из data/airports.yaml и data/airspace.yaml.")


def provider_name(cfg: dict) -> str:
    nav = cfg.get("navdata") or {}
    return str(nav.get("provider") or "xplane").strip().lower()


def make_provider(cfg: dict) -> NavDataProvider:
    name = provider_name(cfg)
    if name in ("navigraph", "navigraph-stub"):
        return NavigraphProvider()
    if name in ("off", "none", "yaml", "disabled"):
        return NullProvider()
    from .xplane import XPlaneProvider
    return XPlaneProvider(cfg)
