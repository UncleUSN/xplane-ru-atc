"""Короткие подтверждения пилота: «подтверждаю», «понял», «роджер» и похожие.

Vosk путает буквы, поэтому слова сравниваются нечётко (расстояние Дамерау–Левенштейна).
«Подтверждаю» и «подтвреждаю» — одно и то же. Отрицание («не понял») подтверждением не считается.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Set, Tuple

# Одно слово. Длинные формы терпят 1–2 опечатки, короткие — одну.
_SINGLE: Tuple[str, ...] = (
    "подтверждаю", "подтверждаем", "подтвердил", "подтвердила",
    "понял", "поняла", "поняли", "понятно",
    "принял", "приняла", "приняли", "принято",
    "выполняю", "выполнил", "выполнила", "выполним", "выполнили",
    "роджер", "roger", "уилко", "wilco", "вилко",
)

# Два слова: короткое («вас», «так») само по себе ничего не значит.
_MULTI: Tuple[Tuple[str, ...], ...] = (
    ("вас", "понял"),
    ("вас", "поняла"),
    ("вас", "поняли"),
    ("так", "точно"),
)

_NEGATION = {"не", "ни", "нет"}
# Слова без смысла, которые можно выкинуть, если подтверждение уже найдено.
# «приём» — обычное «подтверждаю приём», само по себе указанием не является.
_FILLERS = {"да", "ну", "а", "и", "э", "эм", "мм", "ага", "угу", "прием"}


def _damerau(a: str, b: str) -> int:
    """Расстояние Дамерау–Левенштейна: соседняя перестановка букв стоит 1."""
    la, lb = len(a), len(b)
    if a == b:
        return 0
    if la == 0 or lb == 0:
        return la + lb
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def _max_dist(canon: str) -> int:
    n = len(canon)
    if n <= 3:
        return 0
    if n <= 7:
        return 1
    return 2


def _close(heard: str, canon: str) -> bool:
    if heard == canon:
        return True
    limit = _max_dist(canon)
    if limit == 0 or abs(len(heard) - len(canon)) > limit:
        return False
    # «неподтверждаю» — это отказ, а не опечатка в «подтверждаю».
    for neg in ("не", "ни"):
        if heard.startswith(neg) and _damerau(heard[len(neg):], canon) <= limit:
            return False
    return _damerau(heard, canon) <= limit


def _match_at(tokens: Sequence[str], i: int) -> Optional[int]:
    """Конец (не включая) подтверждения, начинающегося в i, либо None."""
    if tokens[i] in _NEGATION or (i > 0 and tokens[i - 1] in _NEGATION):
        return None
    n = len(tokens)
    for ph in _MULTI:
        L = len(ph)
        if i + L <= n and all(_close(tokens[i + k], ph[k]) for k in range(L)):
            return i + L
        # «такточно», «васпонял» — без пробела
        if L == 2 and _close(tokens[i], ph[0] + ph[1]):
            return i + 1
    word = tokens[i]
    for canon in _SINGLE:
        if _close(word, canon):
            return i + 1
        # «под» + «тверждаю»: длинное слово, разрезанное распознавателем
        if len(canon) >= 8 and i + 1 < n and len(word) < len(canon):
            nxt = tokens[i + 1]
            if not any(c.isdigit() for c in word + nxt) and _close(word + nxt, canon):
                return i + 2
            if i + 2 < n and len(word) <= 4 and not any(c.isdigit() for c in tokens[i + 2]):
                if _close(word + nxt + tokens[i + 2], canon):
                    return i + 3
    return None


def acknowledgement_span(tokens: Sequence[str]) -> Optional[Tuple[int, int]]:
    """Первое подтверждение в списке слов (уже нормализованных) или None."""
    for i in range(len(tokens)):
        end = _match_at(tokens, i)
        if end is not None:
            return i, end
    return None


def _remaining(tokens: Sequence[str]) -> Optional[List[str]]:
    """Слова без подтверждений. None, если подтверждения в тексте нет."""
    rest: List[str] = []
    found = False
    i = 0
    n = len(tokens)
    while i < n:
        end = _match_at(tokens, i)
        if end is not None:
            found = True
            i = end
        else:
            rest.append(tokens[i])
            i += 1
    return rest if found else None


def _allowed_tokens(callsign: str, number: str, extra: str) -> Set[str]:
    from .parser import normalize
    allowed: Set[str] = set()
    for chunk in (callsign, number, extra):
        if chunk:
            allowed.update(normalize(str(chunk)).split())
    return allowed


def _token_allowed(tok: str, allowed: Set[str], station: Set[str]) -> bool:
    if tok in allowed or tok in _FILLERS:
        return True
    for a in allowed:
        if len(a) < 6:
            continue
        # Длинные имена («шереметьево» / «шереметев») терпят две правки.
        limit = 2 if len(a) >= 8 else 1
        if abs(len(a) - len(tok)) <= limit and _damerau(tok, a) <= limit:
            return True
    # «делились» вместо «деливери»: общий корень, расстояние уже большое.
    for a in station:
        if len(a) >= 6 and len(tok) >= 6 and tok[:4] == a[:4] and abs(len(a) - len(tok)) <= 3:
            return True
    return False


def is_bare_confirmation(text: str, callsign: str = "", number: str = "", extra: str = "") -> bool:
    """Текст — только подтверждение, можно с позывным и позывным органа.

    Лишние слова (ВПП, эшелон, частота…) делают фразу не «голой»: её разбирает
    обычная проверка readback и ловит неверное значение. Искажённый позывной
    органа («шереметев», «делились») и «приём» голым подтверждением остаются.
    """
    from .parser import normalize
    tokens = normalize(text or "").split()
    if not tokens:
        return False
    rest = _remaining(tokens)
    if rest is None:
        return False
    from .courtesy import strip_courtesy_tokens
    rest = strip_courtesy_tokens(rest)
    allowed = _allowed_tokens(callsign, number, extra)
    station = set(normalize(extra).split()) if extra else set()
    return all(_token_allowed(tok, allowed, station) for tok in rest)
