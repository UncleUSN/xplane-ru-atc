"""Позывной, который пилот назвал сам.

Первая передача вида «Сибирь 213» или «RA 73123» задаёт, как диспетчер
обращается дальше. Номер может быть цифрами («213») или словами
(«двести тринадцать», «два один три»): к этому моменту числительные уже
переведены в цифры. Таблица ниже — телефонные позывные российских
компаний; код ИКАО нужен, чтобы номер рейса из FMC («SBI213») совпал
с тем, что сказано в эфире.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


# Код ИКАО -> как компания звучит в эфире.
DEFAULT_AIRLINES: Dict[str, str] = {
    "AFL": "Аэрофлот",
    "SDM": "Россия",
    "PBD": "Победа",
    "SBI": "Сибирь",
    "UTA": "ЮТэйр",
    "SVR": "Уральские",
    "NWS": "Нордвинд",
    "AZO": "Азимут",
    "AUL": "Смартавиа",
    "RWZ": "Ред Вингс",
    "SHU": "Аврора",
    "LLM": "Ямал",
    "IAE": "ИрАэро",
    "SYL": "Якутия",
    "DRU": "Алроса",
    "GZP": "Газпром",
    "RLU": "РусЛайн",
    "SSF": "Северсталь",
    "TYA": "Нордстар",
    "AZV": "Азур",
    "KAR": "Пегас",
    "IZA": "Ижавиа",
    "UVT": "ЮВТ",
    "ABG": "Роял Флайт",
}

# Уже после normalize(): нижний регистр, «ё» -> «е». Длинные формы раньше коротких.
_ALIAS_ICAO: Tuple[Tuple[str, str], ...] = (
    ("уральские авиалинии", "SVR"),
    ("свердловск авиа", "SVR"),
    ("уральские", "SVR"),
    ("ред вингс", "RWZ"),
    ("редвингс", "RWZ"),
    ("ред винг", "RWZ"),
    ("смарт авиа", "AUL"),
    ("смартавиа", "AUL"),
    ("норд винд", "NWS"),
    ("нордвинд", "NWS"),
    ("азур эйр", "AZV"),
    ("азур", "AZV"),
    ("роял флайт", "ABG"),
    ("роялфлайт", "ABG"),
    ("газпром авиа", "GZP"),
    ("газпромавиа", "GZP"),
    ("газпром", "GZP"),
    ("рус лайн", "RLU"),
    ("руслайн", "RLU"),
    ("ир аэро", "IAE"),
    ("ираэро", "IAE"),
    ("ювт аэро", "UVT"),
    ("ювт", "UVT"),
    ("норд стар", "TYA"),
    ("нордстар", "TYA"),
    ("ю тейр", "UTA"),
    ("ютэир", "UTA"),
    ("ютейр", "UTA"),
    ("эс семь", "SBI"),
    ("эс 7", "SBI"),
    ("эс7", "SBI"),
    ("аэрофлот", "AFL"),
    ("сибирь", "SBI"),
    ("россия", "SDM"),
    ("победа", "PBD"),
    ("азимут", "AZO"),
    ("аврора", "SHU"),
    ("ямал", "LLM"),
    ("якутия", "SYL"),
    ("алроса", "DRU"),
    ("северсталь", "SSF"),
    ("ижавиа", "IZA"),
    ("пегас", "KAR"),
    ("икар", "KAR"),
)

_REG = re.compile(
    r"(?:^|\s)(?:регистрац\w+\s+)?"
    r"(?:ра|ra|эр\s+а|р\s+а|r\s+a)"
    r"\s*(\d{4,5})(?!\d)"
)


@dataclass(frozen=True)
class HeardCallsign:
    spoken: str
    number: str
    kind: str          # "airline" | "registration"
    icao: str = ""

    @property
    def label(self) -> str:
        return f"{self.spoken} {self.number}".strip()


def _norm_alias(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower().replace("ё", "е")).strip()


def airline_table(airlines: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Код ИКАО -> позывной. Значения из config перекрывают таблицу по умолчанию."""
    table = dict(DEFAULT_AIRLINES)
    for code, spoken in (airlines or {}).items():
        key = str(code or "").strip().upper()
        name = str(spoken or "").strip()
        if key and name:
            table[key] = name
    return table


def _patterns(table: Dict[str, str]) -> List[Tuple[re.Pattern, str, str]]:
    """(выражение, код ИКАО, канонический позывной), длинные имена раньше."""
    aliases: Dict[str, str] = {}
    for alias, icao in _ALIAS_ICAO:
        if icao in table:
            aliases.setdefault(_norm_alias(alias), icao)
    for icao, spoken in table.items():
        aliases.setdefault(_norm_alias(spoken), icao)
    ordered = sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True)
    out: List[Tuple[re.Pattern, str, str]] = []
    for alias, icao in ordered:
        if not alias:
            continue
        body = re.escape(alias).replace(r"\ ", r"\s+")
        pat = re.compile(
            rf"(?:^|\s)({body})(?:\s+(?:рейс|борт|номер))?(?:\s+|(?=\d))(\d{{1,4}})(?!\d)"
        )
        out.append((pat, icao, table[icao]))
    return out


def alias_tokens() -> List[str]:
    """Слова телефонных позывных для грамматики Vosk."""
    words = set()
    for alias, _icao in _ALIAS_ICAO:
        words.update(_norm_alias(alias).split())
    for spoken in DEFAULT_AIRLINES.values():
        words.update(_norm_alias(spoken).split())
    words.update(("рейс", "борт", "регистрация", "ра"))
    return sorted(words)


def _flight_number(raw: str) -> str:
    return raw.lstrip("0") or "0"


def extract_callsign(norm: str, airlines: Optional[Dict[str, str]] = None) -> Optional[HeardCallsign]:
    """Найти в уже нормализованной фразе позывной компании или регистрацию RA.

    Берётся самое левое вхождение. «Сибирь 213» не путается с частотой:
    после номера не должно быть ещё одной цифры, а «118.7» цифрой рейса не считается.
    """
    text = norm or ""
    if not text:
        return None
    table = airline_table(airlines)
    found: Optional[Tuple[int, int, HeardCallsign]] = None

    reg = _REG.search(text)
    if reg:
        number = reg.group(1)
        found = (reg.start(), -len(number), HeardCallsign("RA", number, "registration"))

    for pat, icao, spoken in _patterns(table):
        match = pat.search(text)
        if not match:
            continue
        number = _flight_number(match.group(2))
        # Совпадение внутри уже найденного более длинного имени не нужно:
        # сравниваем позицию начала.
        cand = (match.start(1), -len(match.group(1)), HeardCallsign(spoken, number, "airline", icao))
        if found is None or cand[0] < found[0] or (cand[0] == found[0] and cand[1] < found[1]):
            found = cand
    return found[2] if found else None


def callsign_words(hit: Optional[HeardCallsign]) -> Iterable[str]:
    if not hit:
        return ()
    return _norm_alias(hit.spoken).split() + [hit.number]
