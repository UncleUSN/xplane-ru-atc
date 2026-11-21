"""Тангента (push-to-talk): клавиша клавиатуры (библиотека keyboard) и/или кнопка джойстика (pygame)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)


class PTT:
    def __init__(self, key: Optional[str], joystick: Optional[dict],
                 on_press: Callable[[], None], on_release: Callable[[], None]):
        self.key = key
        self.joy = joystick
        self.on_press = on_press
        self.on_release = on_release
        self.down = False
        self._sources = set()
        self._lock = threading.Lock()

    def _press(self, src: str):
        with self._lock:
            was = bool(self._sources)
            self._sources.add(src)
            if not was:
                self.down = True
                self.on_press()

    def _release(self, src: str):
        with self._lock:
            if src not in self._sources:
                return
            self._sources.discard(src)
            if not self._sources:
                self.down = False
                self.on_release()

    def start(self):
        if self.key:
            try:
                import keyboard   # на Windows работает без прав администратора
                keyboard.on_press_key(self.key, lambda e: self._press("kbd"), suppress=False)
                keyboard.on_release_key(self.key, lambda e: self._release("kbd"), suppress=False)
                log.info("Тангента: клавиша '%s'", self.key)
            except Exception as e:
                log.warning("Клавиша тангенты недоступна (%s). Используйте кнопку в окне или джойстик.", e)
        if self.joy:
            threading.Thread(target=self._joy_loop, name="ptt-joy", daemon=True).start()

    def _joy_loop(self):
        try:
            import os
            os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
            import pygame
            pygame.init()
            pygame.joystick.init()
            js = pygame.joystick.Joystick(int(self.joy.get("device", 0)))
            js.init()
            btn = int(self.joy.get("button", 0))
            log.info("Тангента: джойстик '%s', кнопка %d", js.get_name(), btn)
        except Exception as e:
            log.warning("Джойстик недоступен: %s", e)
            return
        while True:
            pygame.event.pump()
            if js.get_button(btn):
                self._press("joy")
            else:
                self._release("joy")
            time.sleep(0.02)

    # для кнопки в окне
    def ui_press(self):
        self._press("ui")

    def ui_release(self):
        self._release("ui")
