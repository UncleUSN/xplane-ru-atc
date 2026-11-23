"""Короткие приветствия и прощания, которые не заменяют фразеологию.

Разрешение, частота, высота, код ответчика и ВПП остаются в тексте как были.
Добавка только спереди (после позывного) или в самом конце. ``off`` ничего не добавляет.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Sequence, Tuple

# Вероятность, что добавка прозвучит. Не 1: даже high иногда молчит.
PROBS = {
    "off": {"greet": 0.0, "farewell": 0.0, "touch": 0.0, "greet_back": 0.0, "reply": 0.0},
    "normal": {"greet": 0.6, "farewell": 0.7, "touch": 0.25, "greet_back": 0.75, "reply": 0.5},
    "high": {"greet": 0.9, "farewell": 0.9, "touch": 0.55, "greet_back": 0.95, "reply": 0.8},
}

# Пилот. После normalize() «ё» уже «е», но шаблон принимает оба варианта.
GREET_PHRASES = (
    "доброе утро",
    "добрый день",
    "добрый вечер",
    "здравствуйте",
    "приветствую",
)
GOODBYE_PHRASES = (
    "до свидания",
    "до свиданья",
    "всего доброго",
    "счастливого пути",
    "счастливого полёта",
    "счастливого полета",
    "хорошего дня",
    "хорошего полёта",
    "хорошего полета",
    "мягкой посадки",
)
THANKS_PHRASES = ("спасибо", "благодарю")

# То, что диспетчер может сказать. В речи сохраняем «ё», Silero её читает.
_INFORMAL = "принято, хорошего полёта"


def _yo(phrase: str) -> str:
    return "".join("[её]" if ch in "её" else re.escape(ch) for ch in phrase)


def _re(phrases: Sequence[str]) -> re.Pattern:
    body = "|".join(_yo(p) for p in sorted(phrases, key=len, reverse=True))
    return re.compile(rf"\b(?:{body})\b")


GREET_RE = _re(GREET_PHRASES)
GOODBYE_RE = _re(GOODBYE_PHRASES)
THANKS_RE = _re(THANKS_PHRASES)

# Для вырезания из уже показанного текста (там «ё» на месте).
_DISPLAY_PHRASES = tuple(sorted(
    set(GREET_PHRASES)
    | set(GOODBYE_PHRASES)
    | set(THANKS_PHRASES)
    | {_INFORMAL, "принято, хорошего полета"},
    key=len,
    reverse=True,
))

_TOKEN_PHRASES = tuple(sorted(
    (tuple(p.replace("ё", "е").split()) for p in
     list(GREET_PHRASES) + list(GOODBYE_PHRASES) + list(THANKS_PHRASES)),
    key=len,
    reverse=True,
))


def normalize_chattiness(value) -> str:
    """off | normal | high. В YAML 1.1 голое ``off`` — это false, его тоже понимаем."""
    if isinstance(value, bool):
        return "normal" if value else "off"
    if value is None:
        return "normal"
    text = str(value).strip().lower()
    if text in ("off", "0", "false", "no", "strict"):
        return "off"
    if text in ("high", "chatty"):
        return "high"
    if text in ("normal", "on", "true", "yes", "mid", "medium"):
        return "normal"
    return "normal"


def day_part(hour: int) -> str:
    """Местный час: утро 5–11, день 12–16, вечер 17–22, иначе ночь."""
    hour = int(hour) % 24
    if 5 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 16:
        return "day"
    if 17 <= hour <= 22:
        return "evening"
    return "night"


def hour_of(local_time_sec: Optional[float], now: Optional[datetime] = None) -> Tuple[int, str]:
    """Час и откуда он: ``sim`` (dataref, секунды от местной полуночи) или ``system``."""
    if isinstance(local_time_sec, (int, float)) and not isinstance(local_time_sec, bool):
        if local_time_sec == local_time_sec and local_time_sec >= 0:
            return int(float(local_time_sec) // 3600) % 24, "sim"
    moment = now if now is not None else datetime.now().astimezone()
    return moment.hour, "system"


def greeting_options(part: str) -> Tuple[str, ...]:
    if part == "morning":
        return ("доброе утро", "здравствуйте", "доброе утро")
    if part == "day":
        return ("добрый день", "здравствуйте", "добрый день")
    if part == "evening":
        return ("добрый вечер", "здравствуйте", "добрый вечер")
    return ("здравствуйте",)


def farewell_options(part: str, landing: bool = False) -> Tuple[str, ...]:
    if landing:
        return ("мягкой посадки", "до свидания", "всего доброго", "счастливого пути")
    base = ["до свидания", "счастливого пути", "счастливого полёта", "всего доброго"]
    if part == "morning":
        base.append("хорошего полёта")
    elif part == "day":
        base.append("хорошего дня")
    elif part == "evening":
        base.append("всего доброго")
    base.append(_INFORMAL)
    return tuple(base)


def reply_options(part: str, *, landing: bool, thanks: bool, greet: bool) -> Tuple[str, ...]:
    """Короткий ответ на голое приветствие или прощание пилота."""
    if landing:
        return ("мягкой посадки", "до свидания", "всего доброго")
    if greet and not thanks:
        return greeting_options(part)
    if thanks and not greet:
        return ("спасибо", "всего доброго", "хорошего полёта")
    return ("до свидания", "всего доброго", "хорошего полёта", "спасибо")


def insert_greeting(template: str, greeting: str) -> str:
    """После позывного, до разрешения. Сам шаблон с цифрами не переписывается."""
    greeting = (greeting or "").strip()
    if not greeting:
        return template
    if template.startswith("{cs},"):
        rest = template[len("{cs},"):].lstrip()
        return f"{{cs}}, {greeting}, {rest}"
    if template.startswith("{cs}"):
        rest = template[len("{cs}"):].lstrip(" ,")
        return f"{{cs}}, {greeting}, {rest}"
    return f"{greeting}, {template}"


def append_clause(template: str, clause: str) -> str:
    clause = (clause or "").strip().strip(",")
    if not clause:
        return template
    return f"{template.rstrip().rstrip(',')}, {clause}"


def strip_courtesy_tokens(tokens: Sequence[str]) -> list:
    """Убрать приветствие и прощание из уже нормализованных слов."""
    out: list = []
    i = 0
    n = len(tokens)
    while i < n:
        matched = False
        for phrase in _TOKEN_PHRASES:
            k = len(phrase)
            if i + k <= n and tuple(tokens[i:i + k]) == phrase:
                i += k
                matched = True
                break
        if not matched:
            out.append(tokens[i])
            i += 1
    return out


def strip_courtesy_text(text: str) -> str:
    """Убрать вежливые добавки из готовой реплики, не трогая «взлёт» и числа."""
    cleaned = text
    for phrase in _DISPLAY_PHRASES:
        cleaned = re.sub(
            rf"(,\s*)?{re.escape(phrase)}(,\s*)?",
            lambda m: ", " if m.group(1) and m.group(2) else "",
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"(,\s*){2,}", ", ", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    return cleaned.strip()


def is_only_courtesy(text: str, callsign: str = "", number: str = "", extra: str = "") -> bool:
    """Текст — приветствие или прощание, можно с позывным и органом.

    Любое другое слово («абракадабра», ВПП, код) делает фразу обычной:
    её разбирает readback или «повторите».
    """
    from .confirm import _FILLERS, _allowed_tokens, _token_allowed
    from .parser import normalize
    norm = normalize(text or "")
    if not (GREET_RE.search(norm) or GOODBYE_RE.search(norm) or THANKS_RE.search(norm)):
        return False
    rest = strip_courtesy_tokens(norm.split())
    allowed = _allowed_tokens(callsign, number, extra)
    station = set(normalize(extra).split()) if extra else set()
    return all(tok in _FILLERS or _token_allowed(tok, allowed, station) for tok in rest)


def annotate(msg) -> None:
    """Пометить приветствие и прощание. Просьбу и подтверждение не затирает.

    Голое «до свидания» / «спасибо» становится намерением farewell.
    «добрый день» без другой просьбы остаётся выходом на связь.
    """
    norm = getattr(msg, "norm", "") or ""
    msg.greet = bool(GREET_RE.search(norm))
    msg.thanks = bool(THANKS_RE.search(norm))
    msg.goodbye = bool(GOODBYE_RE.search(norm))
    msg.farewell = bool(msg.thanks or msg.goodbye)
    if msg.slots and msg.intent == "check_in" and "на связи" not in norm:
        others = [i for i in msg.intents if i not in ("check_in", "wilco", "farewell", "unknown")]
        if not others:
            msg.intent = "readback"
            if "readback" not in msg.intents:
                msg.intents.append("readback")
    if "wilco" in msg.intents and msg.intent in ("check_in", "unknown", "farewell") and not msg.slots:
        others = [i for i in msg.intents if i not in ("check_in", "wilco", "farewell", "unknown")]
        if not others:
            msg.intent = "wilco"
    operational = [i for i in msg.intents if i not in ("check_in", "unknown", "wilco", "farewell")]
    if operational or msg.intent in ("wilco", "readback") or "wilco" in msg.intents or msg.slots:
        return
    if "на связи" in norm and not msg.goodbye:
        return
    if msg.goodbye or msg.thanks:
        msg.intent = "farewell"
        if "farewell" not in msg.intents:
            msg.intents.append("farewell")
