"""Разбор русской радиотелефонной фразеологии пилота -> намерение (intent) + параметры.

Работает с текстом распознавателя (Vosk выдаёт слова, Whisper — иногда цифры):
нормализует текст, переводит числительные в цифры и ищет ключевые конструкции.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .callsign import HeardCallsign, extract_callsign
from .confirm import acknowledgement_span
from .courtesy import annotate
from .numbers import words_to_digits


# Порядок важен: более специфичные намерения раньше
INTENT_PATTERNS: List[tuple] = [
    ("radio_check", [r"проверка связи", r"как (?:меня )?слыши"]),
    ("request_push_start", [r"буксировк\w* и запуск", r"запуск и буксировк", r"буксировк\w*.*запуск",
                            r"выталкивани\w* и запуск"]),
    ("request_pushback", [r"буксировк", r"выталкивани", r"\bбуксир\b", r"пушбэк", r"пушбек"]),
    ("request_startup", [r"(?:разрешите|прошу|запрашиваю|просим)\s+(?:\w+\s+)?запуск", r"готов\w* к запуску",
                         r"запуск\w*\s+(?:разрешите|прошу)"]),
    ("request_clearance", [r"(?:прошу|разрешите|запрашиваю)\s+(?:\w+\s+){0,2}(?:условия|разрешени\w*)\s+(?:\w+\s+){0,2}(?:выход|вылет|полет|до\b)",
                           r"условия выхода", r"разрешени\w* (?:на )?(?:вылет|полет)", r"разрешени\w* до\b",
                           r"запрос\w* (?:условий|разрешения)", r"разрешение по плану", r"(?:прошу|разрешите) разрешение"]),
    ("ready_departure", [r"готов\w* к (?:взлет|вылет)", r"к взлету готов", r"к вылету готов",
                         r"на предварительно\w*.*готов", r"готов\w* исполнительн", r"разрешите взлет"]),
    ("request_lineup", [r"(?:разрешите|прошу) (?:занять )?исполнительн", r"на предварительном"]),
    ("request_taxi_in", [r"(?:рулить|рулени\w*) на стоянк", r"на стоянку"]),
    ("request_taxi", [r"(?:разрешите|прошу|запрашиваю)\s+(?:\w+\s+)?рулени", r"разрешите рулить", r"прошу рулить",
                      r"готов\w* к рулени", r"рулени\w* (?:разрешите|прошу)"]),
    ("runway_vacated", [r"освободил\w*", r"полосу освободил", r"впп освободил"]),
    ("report_airborne", [r"взлетел\w*", r"после взлета", r"в наборе", r"набираю"]),
    ("request_descent", [r"(?:разрешите|прошу|запрашиваю)\s+снижени", r"готов\w* к снижени", r"разрешите снижаться"]),
    ("request_climb", [r"(?:разрешите|прошу|запрашиваю)\s+набор"]),
    ("request_approach", [r"(?:разрешите|прошу|запрашиваю)\s+(?:\w+\s+)?заход", r"готов\w* к заходу"]),
    ("report_established", [r"\bпосадочн\w*", r"на курсе посадки", r"захватил\w* (?:курс|глиссад|локалайзер)",
                            r"установил\w* на (?:курс|посадоч)", r"на глиссаде", r"на прямой"]),
    ("request_landing", [r"(?:разрешите|прошу)\s+посадк", r"к посадке готов", r"готов\w* к посадке"]),
    ("going_around", [r"ухожу на второй", r"на второй круг"]),
    ("report_level", [r"занял\w*", r"сохраняю", r"на эшелоне", r"иду на эшелоне", r"следую на эшелоне"]),
    ("request_weather", [r"сообщите погод", r"фактическ\w* погод", r"какая погода",
                         r"погод\w*\s+(?:в|на|по)\b", r"\bметеор"]),
    ("check_in", [r"на связи", r"добрый (?:день|вечер)", r"доброе утро", r"здравствуйте", r"приветствую"]),
    ("request_atis", [r"\bатис\b", r"прослушайте информаци", r"включите информаци",
                      r"запросите информаци", r"повторите информаци"]),
    ("say_again", [r"повторите", r"не понял"]),
    ("atis_ack", [r"информаци\w*.{0,40}(?:получил\w*|принял\w*|имею|принято)",
                  r"(?:получил\w*|принял\w*|имею)\s+информаци"]),
]

RUNWAY_RE = re.compile(r"(?:впп|полос\w*|вэпэпэ)\s+(\d{1,2})\s*(лев\w*|прав\w*|центр\w*)?")
LEVEL_RE = re.compile(r"эшелон\w*\s+(\d{2,3})")
ALT_FT_RE = re.compile(r"(\d{3,5})\s*(?:футов|фута|фут)")
ALT_M_RE = re.compile(r"(\d{3,5})\s*(?:метров|метра|метр)")
ALT_GENERIC_RE = re.compile(r"высот\w*\s+(\d{3,5})")
SQUAWK_RE = re.compile(r"(?:ответчик\w*|код\w*|сквок)\s+(?:код\w*\s+)?([0-7]{4})\b")
FREQ_RE = re.compile(r"\b(1[1-3]\d)\.(\d{1,3})\b")
FREQ_SPLIT_RE = re.compile(r"\b(1[1-3]\d)\s+(\d{1,3})\b")
QNH_RE = re.compile(r"(?:давлени\w*|qnh|кьюэнаш|ку эн аш)\s+(?:\w+\s+)?(\d{3,4})")
STAND_RE = re.compile(r"(?:стоянк\w*|место стоянки)\s+(\d{1,3}[а-я]?)")
TARGET_LEVEL_RE = re.compile(r"(?:в наборе|набираю|набор\w*|снижаюсь|в снижении|снижени\w*|занимаю)\s+(?:до\s+)?(?:эшелон\w*)\s+(\d{2,3})")
TARGET_ALT_RE = re.compile(r"(?:в наборе|набираю|набор\w*|снижаюсь|в снижении|снижени\w*|занимаю)\s+(?:до\s+)?(?:высот\w*\s+)?(\d{3,5})\s*(?:футов|фута|фут)")
HEADING_RE = re.compile(r"курс\w*\s+(\d{3})")


FIXUPS = [
    (r"\b(?:шалун\w*|ешелон\w*|эшалон\w*|эшелона?м?|шелон\w*)\b", "эшелон"),
    (r"\bэшелон а\b", "эшелон"),
    (r"\b(?:вэ пэ пэ|в п п|вэпэпэ|вэ пэ|бы по|вы по|вэ по|в пп)\b", "впп"),
    (r"\bруле не\b", "рулени"),
    (r"\bрулении\b", "рулени"),
    (r"\bпосадочным\b", "посадочном"),
    (r"\bправ(?:о|ое|ой|ую)?\b", "правая"), (r"\bлев(?:ое|ой|ую)\b", "левая"), (r"\bправа\b", "правая"),
    (r"\bлева\b", "левая"), (r"\bлево\b", "левая"),
    (r"\bразрешения да\b", "разрешение до"), (r"\bразрешение да\b", "разрешение до"),
    (r"\bзаняло\b", "занял"), (r"\bзанял а\b", "занял"),
    (r"\bнаборе\b", "в наборе"), (r"\bв в наборе\b", "в наборе"),
    (r"\bответчика?м?\b", "ответчик"),
]


@dataclass
class ParsedMessage:
    raw: str
    norm: str
    intent: str = "unknown"
    intents: List[str] = field(default_factory=list)
    slots: Dict[str, object] = field(default_factory=dict)
    greet: bool = False
    thanks: bool = False
    goodbye: bool = False
    farewell: bool = False
    callsign: Optional[HeardCallsign] = None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.intent} {self.slots} '{self.norm}'>"


def normalize(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[«»\"!?;:()\[\]]", " ", t)
    t = t.replace("-", " ")
    # Точки/запятые между цифрами сохраняем (118.7 / 118,7), прочие убираем
    t = re.sub(r"(?<!\d)[.,]|[.,](?!\d)", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Типичные ошибки распознавания (Vosk small)
    for pat, rep in FIXUPS:
        t = re.sub(pat, rep, t)
    return words_to_digits(t)


def _side(word: Optional[str]) -> str:
    if not word:
        return ""
    return {"л": "L", "п": "R", "ц": "C"}[word[0]]


def extract_slots(norm: str) -> Dict[str, object]:
    s: Dict[str, object] = {}
    m = RUNWAY_RE.search(norm)
    if m:
        s["runway"] = f"{int(m.group(1)):02d}{_side(m.group(2))}"
    m = LEVEL_RE.search(norm)
    if m:
        s["level"] = int(m.group(1))
    m = ALT_FT_RE.search(norm)
    if m:
        s["alt_ft"] = int(m.group(1))
    m = ALT_M_RE.search(norm)
    if m:
        s["alt_m"] = int(m.group(1))
    if "alt_ft" not in s and "alt_m" not in s:
        m = ALT_GENERIC_RE.search(norm)
        if m:
            s["alt_ft"] = int(m.group(1))
    m = SQUAWK_RE.search(norm)
    if m:
        s["squawk"] = m.group(1)
    m = FREQ_RE.search(norm)
    if m:
        s["freq"] = float(f"{m.group(1)}.{m.group(2)}")
    else:
        m = FREQ_SPLIT_RE.search(norm)
        if m and ("частот" in norm or "работаю" in norm or "связь" in norm or "контрол" in norm
                  or "подход" in norm or "круг" in norm or "старт" in norm or "вышк" in norm
                  or "рулени" in norm or "перрон" in norm):
            s["freq"] = float(f"{m.group(1)}.{m.group(2)}")
    m = QNH_RE.search(norm)
    if m:
        v = int(m.group(1))
        if 900 <= v <= 1100:
            s["qnh"] = v
    if "стандарт" in norm:
        s["std"] = True
    m = STAND_RE.search(norm)
    if m:
        s["stand"] = m.group(1)
    m = TARGET_LEVEL_RE.search(norm)
    if m:
        s["target_level"] = int(m.group(1))
    m = TARGET_ALT_RE.search(norm)
    if m:
        s["target_alt_ft"] = int(m.group(1))
    m = HEADING_RE.search(norm)
    if m:
        s["heading"] = int(m.group(1))
    if "информаци" in norm:
        m = re.search(r"информаци\w*\s+([а-я]+)", norm)
        if m:
            s["atis"] = m.group(1)
    return s


def parse(text: str) -> ParsedMessage:
    norm = normalize(text)
    msg = ParsedMessage(raw=text, norm=norm)
    for intent, pats in INTENT_PATTERNS:
        if any(re.search(p, norm) for p in pats):
            msg.intents.append(intent)
    # Взаимоисключения
    if "request_push_start" in msg.intents:
        msg.intents = [i for i in msg.intents if i not in ("request_pushback", "request_startup")]
    if "ready_departure" in msg.intents and "request_lineup" in msg.intents:
        msg.intents.remove("request_lineup")
    msg.intent = msg.intents[0] if msg.intents else "unknown"
    msg.slots = extract_slots(norm)
    msg.callsign = extract_callsign(norm)
    # «подтверждаю» / «понял» / «роджер», в том числе с опечаткой распознавателя.
    # «не понял» сюда не попадает: отрицание отсекается, остаётся say_again.
    if acknowledgement_span(norm.split()):
        if "wilco" not in msg.intents:
            msg.intents.append("wilco")
        if msg.intent == "unknown":
            msg.intent = "wilco"
    # Короткое подтверждение с параметрами -> считаем readback
    if msg.intent in ("wilco", "unknown") and msg.slots:
        msg.intent = "readback"
    # «добрый день» и «до свидания» не меняют просьбу и не делают фразу незнакомой.
    annotate(msg)
    # Одно название борта без другой просьбы — выход на связь, а не «повторите».
    if msg.callsign and msg.intent == "unknown" and not msg.slots:
        others = [i for i in msg.intents if i not in ("unknown", "check_in")]
        if not others:
            msg.intent = "check_in"
            if "check_in" not in msg.intents:
                msg.intents.append("check_in")
    return msg
