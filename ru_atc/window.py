"""Поведение окна поверх X-Plane: always-on-top с периодическим «переподнятием», компактный
полупрозрачный режим, показ/скрытие по глобальной горячей клавише.

Модуль не импортирует tkinter: root — любой объект с методами Tk (тестируется подделкой).
Горячие клавиши (библиотека keyboard) срабатывают в чужом потоке, поэтому они только кладут
команду в очередь, а окно меняется из цикла tkinter (Tk не потокобезопасен).

Ограничение Windows: окно НЕ может быть поверх X-Plane в эксклюзивном полноэкранном режиме
(Direct3D/Vulkan exclusive fullscreen) — используйте в X-Plane оконный или «полноэкранный
в окне» (безрамочный) режим.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Callable, Dict, List, Optional

log = logging.getLogger(__name__)

GEOM_RE = re.compile(r"^(\d+)x(\d+)(?:([+-]-?\d+)([+-]-?\d+))?$")

HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
SW_SHOWNOACTIVATE = 4


def parse_geometry(g: str) -> Optional[tuple]:
    m = GEOM_RE.match(str(g or "").replace(" ", ""))
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return (w, h, m.group(3), m.group(4))


def clamp_alpha(a) -> float:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return 1.0
    return max(0.2, min(1.0, a))


class Win32:
    """Тонкая обёртка над user32 (только Windows); на других ОС все вызовы — пустые."""

    def __init__(self) -> None:
        self.ok = sys.platform == "win32"
        self.user32 = None
        if self.ok:
            try:
                import ctypes
                self.user32 = ctypes.windll.user32
            except Exception:
                self.ok = False

    def foreground(self) -> int:
        return int(self.user32.GetForegroundWindow()) if self.ok else 0

    def set_foreground(self, hwnd: int) -> None:
        if self.ok and hwnd:
            self.user32.SetForegroundWindow(hwnd)

    def make_topmost(self, hwnd: int) -> None:
        # Поднять наверх без активации (не забирает фокус у X-Plane)
        if self.ok and hwnd:
            self.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


class WindowController:
    def __init__(self, root, ui_cfg: Dict, on_mode: Optional[Callable[[bool], None]] = None,
                 win32: Optional[Win32] = None) -> None:
        self.root = root
        self.cfg = dict(ui_cfg or {})
        self.on_mode = on_mode            # колбэк перестройки виджетов: on_mode(compact)
        self.win32 = win32 or Win32()
        self.topmost = bool(self.cfg.get("always_on_top", True))
        self.reassert_ms = int(float(self.cfg.get("topmost_reassert_s", 2.0) or 0) * 1000)
        self.compact = False
        self.hidden = False
        self.full_geometry = str(self.cfg.get("full_geometry") or "1100x680")
        self.compact_geometry = str(self.cfg.get("compact_geometry") or "560x180-20+40")
        self.focus_on_show = bool(self.cfg.get("focus_on_show", False))
        self.messages: List[str] = []

    # ------------------------------------------------------------ служебное
    def hwnd(self) -> int:
        try:
            return int(self.root.wm_frame(), 16)
        except Exception:
            return 0

    def _safe(self, fn, *a):
        try:
            return fn(*a)
        except Exception as e:     # платформа/оконный менеджер не поддерживает атрибут
            log.debug("окно: %s%s: %s", getattr(fn, "__name__", fn), a, e)
            return None

    def apply_initial(self) -> None:
        self._safe(self.root.geometry, self.full_geometry)
        self.set_topmost(self.topmost)
        if self.cfg.get("start_compact"):
            self.set_compact(True)
        else:
            self._safe(self.root.attributes, "-alpha", clamp_alpha(self.cfg.get("full_alpha", 1.0)))
        if self.reassert_ms > 0:
            self.root.after(self.reassert_ms, self._reassert_loop)

    # ------------------------------------------------------------ поверх всех окон
    def set_topmost(self, on: bool) -> None:
        self.topmost = bool(on)
        self._safe(self.root.attributes, "-topmost", self.topmost)
        if self.topmost:
            self.win32.make_topmost(self.hwnd())

    def reassert_topmost(self) -> bool:
        """Полноэкранные (безрамочные) приложения могут перекрыть topmost-окно — поднимаем заново,
        не активируя (фокус остаётся у симулятора)."""
        if not self.topmost or self.hidden:
            return False
        self._safe(self.root.attributes, "-topmost", True)
        if self.win32.ok:
            self.win32.make_topmost(self.hwnd())
        else:
            self._safe(self.root.lift)
        return True

    def _reassert_loop(self) -> None:
        self.reassert_topmost()
        if self.reassert_ms > 0:
            self.root.after(self.reassert_ms, self._reassert_loop)

    # ------------------------------------------------------------ компактный режим
    def set_compact(self, on: bool) -> None:
        on = bool(on)
        if on == self.compact:
            return
        if on:
            g = self._safe(self.root.geometry)
            if isinstance(g, str) and parse_geometry(g):
                self.full_geometry = g        # запомнить размер/положение полного окна
        self.compact = on
        if self.on_mode:
            self.on_mode(on)
        if on:
            if self.cfg.get("compact_borderless", True):
                self._safe(self.root.overrideredirect, True)
            self._safe(self.root.geometry, self.compact_geometry)
            self._safe(self.root.attributes, "-alpha", clamp_alpha(self.cfg.get("compact_alpha", 0.85)))
        else:
            self._safe(self.root.overrideredirect, False)
            self._safe(self.root.geometry, self.full_geometry)
            self._safe(self.root.attributes, "-alpha", clamp_alpha(self.cfg.get("full_alpha", 1.0)))
        self.set_topmost(self.topmost)   # overrideredirect может сбросить topmost

    def toggle_compact(self) -> None:
        self.set_compact(not self.compact)

    # ------------------------------------------------------------ показать / спрятать
    def is_visible(self) -> bool:
        st = self._safe(self.root.state)
        return st not in ("withdrawn", "iconic") and not self.hidden

    def hide(self) -> None:
        self._safe(self.root.withdraw)
        self.hidden = True

    def show(self) -> None:
        prev = self.win32.foreground() if not self.focus_on_show else 0
        self._safe(self.root.deiconify)
        self.hidden = False
        if self.compact and self.cfg.get("compact_borderless", True):
            self._safe(self.root.overrideredirect, True)   # после deiconify рамка может вернуться
        self._safe(self.root.lift)
        self.set_topmost(self.topmost)
        if self.focus_on_show:
            self._safe(self.root.focus_force)
        elif prev:
            # Windows активирует окно при deiconify — возвращаем фокус симулятору
            self.root.after(60, lambda: self.win32.set_foreground(prev))

    def toggle_visible(self) -> None:
        if self.is_visible():
            self.hide()
        else:
            self.show()

    def command(self, name: str) -> None:
        {"toggle": self.toggle_visible, "compact": self.toggle_compact,
         "show": self.show, "hide": self.hide}.get(name, lambda: None)()


def register_hotkeys(ui_cfg: Dict, post: Callable[[str], None], kb=None) -> List[str]:
    """Глобальные горячие клавиши. post(cmd) вызывается из потока keyboard — только кладёт команду
    в очередь. Возвращает список сообщений об ошибках (для окна)."""
    errs: List[str] = []
    pairs = [(ui_cfg.get("hotkey_toggle"), "toggle"), (ui_cfg.get("hotkey_compact"), "compact")]
    pairs = [(k, c) for k, c in pairs if k]
    if not pairs:
        return errs
    if kb is None:
        try:
            import keyboard as kb      # на Windows работает без прав администратора; на Linux — нужен root
        except Exception as e:
            return [f"Горячие клавиши окна недоступны (библиотека keyboard: {e})"]
    for key, cmd in pairs:
        try:
            kb.add_hotkey(str(key), lambda c=cmd: post(c), suppress=False)
            log.info("Горячая клавиша окна: %s -> %s", key, cmd)
        except Exception as e:
            errs.append(f"Горячая клавиша '{key}' не назначена: {e}")
    return errs
