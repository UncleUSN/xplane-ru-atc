"""АТИС: буква информации и русский текст сводки.

Буква идёт по кругу A–Z (альфа … зулу). Первая за сеанс — альфа.
Следующая — когда меняется отпечаток погоды или местный час.

Частота берётся из apt.dat (ряд 1050, в кэше navdata поле kind=atis)
или из ``atis_freq`` в data/airports.yaml, если кэша ещё нет.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from .airspace import Airport
from .phraseology.names import PHONETIC
from .phraseology.numbers import int_to_words, runway_to_words
from .weather import CloudLayer, Weather, qfe_mmhg

LETTERS: Tuple[Tuple[str, str], ...] = tuple(PHONETIC.items())

_COVERAGE = {
    "FEW": ("незначительная", "незначительная"),
    "SCT": ("рассеянная", "рассеянная"),
    "BKN": ("значительная", "значительная"),
    "OVC": ("сплошная", "сплошная"),
    "VV": ("вертикальная видимость", "вертикальная видимость"),
}

# Винительный для «информацию … получил»: альфу, дельту, индию.
def _accusative(word: str) -> str:
    if word.endswith("а"):
        return word[:-1] + "у"
    if word.endswith("я"):
        return word[:-1] + "ю"
    return word


_WORD_INDEX = {}
for _i, (_lat, _word) in enumerate(LETTERS):
    _WORD_INDEX[_word] = _i
    _WORD_INDEX[_accusative(_word)] = _i


class AtisBoard:
    """Буква по аэродрому. Живёт, пока запущена программа."""

    def __init__(self) -> None:
        self._state: Dict[str, dict] = {}

    def current(self, icao: str, weather: Weather, hour: int) -> Tuple[int, str]:
        hour = int(hour) % 24
        sig = weather.signature()
        state = self._state.get(icao)
        if state is None:
            state = {"index": 0, "sig": sig, "hour": hour}
            self._state[icao] = state
        elif state["sig"] != sig or state["hour"] != hour:
            state["index"] = (state["index"] + 1) % len(LETTERS)
            state["sig"] = sig
            state["hour"] = hour
        index = state["index"]
        return index, _title(LETTERS[index][1])


def letter_index(word: str) -> Optional[int]:
    token = (word or "").lower().replace("ё", "е").strip()
    return _WORD_INDEX.get(token)


def _title(word: str) -> str:
    return word[:1].upper() + word[1:] if word else word


def _ms_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if 10 <= n100 < 20 or n10 == 0 or n10 >= 5:
        return "метров"
    if n10 == 1:
        return "метр"
    return "метра"


def _deg_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if 10 <= n100 < 20 or n10 == 0 or n10 >= 5:
        return "градусов"
    if n10 == 1:
        return "градус"
    return "градуса"


def _km_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if 10 <= n100 < 20 or n10 == 0 or n10 >= 5:
        return "километров"
    if n10 == 1:
        return "километр"
    return "километра"


def _mm_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if 10 <= n100 < 20 or n10 == 0 or n10 >= 5:
        return "миллиметров"
    if n10 == 1:
        return "миллиметр"
    return "миллиметра"


def _hpa_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if 10 <= n100 < 20 or n10 == 0 or n10 >= 5:
        return "гектопаскалей"
    if n10 == 1:
        return "гектопаскаль"
    return "гектопаскаля"


def _temp_words(value: int) -> str:
    if value < 0:
        return "минус " + int_to_words(-value)
    return int_to_words(value)


def _vis_display(meters: int) -> str:
    if meters >= 9999:
        return "видимость более 10 километров"
    if meters >= 5000 and meters % 1000 == 0:
        km = meters // 1000
        return f"видимость {km} {_km_word(km)}"
    return f"видимость {meters} метров"


def _vis_speech(meters: int) -> str:
    if meters >= 9999:
        return "видимость более десяти километров"
    if meters >= 5000 and meters % 1000 == 0:
        km = meters // 1000
        return f"видимость {int_to_words(km)} {_km_word(km)}"
    return f"видимость {int_to_words(meters)} метров"


def _cloud_display(layer: CloudLayer) -> str:
    name = _COVERAGE.get(layer.coverage, (layer.coverage, layer.coverage))[0]
    if layer.coverage == "VV":
        if layer.base_ft:
            meters = int(round(layer.base_ft * 0.3048))
            return f"вертикальная видимость {meters} метров"
        return "вертикальная видимость"
    if layer.base_ft:
        meters = int(round(layer.base_ft * 0.3048 / 30.0) * 30)
        return f"облачность {name}, нижняя граница {meters} метров"
    return f"облачность {name}"


def _cloud_speech(layer: CloudLayer) -> str:
    name = _COVERAGE.get(layer.coverage, (layer.coverage, layer.coverage))[0]
    if layer.base_ft:
        meters = int(round(layer.base_ft * 0.3048 / 30.0) * 30) or int(round(layer.base_ft * 0.3048))
        if layer.coverage == "VV":
            return f"вертикальная видимость {int_to_words(meters)} метров"
        return f"облачность {name}, нижняя граница {int_to_words(meters)} метров"
    if layer.coverage == "VV":
        return "вертикальная видимость"
    return f"облачность {name}"


def render_broadcast(airport: Airport, weather: Weather, letter: str, runway: str,
                     remarks: str = "", mode: str = "atis") -> Tuple[str, str]:
    """Текст на экран и текст для Silero. В речи нет голых цифр.

    ``mode="weather"`` — короткий ответ диспетчера на «сообщите погоду», без буквы АТИС.
    """
    name = airport.name or airport.icao
    if mode == "weather":
        disp = [f"Фактическая погода {name}."]
        speech = [f"Фактическая погода {name}."]
    else:
        disp = [f"{name}, АТИС, информация {letter}."]
        speech = [f"{name}, атис, информация {letter.lower()}."]
    if runway:
        disp.append(f"Рабочая ВПП {runway}.")
        speech.append(f"Рабочая вэ пэ пэ {runway_to_words(runway)}.")
    if weather.wind_ms is not None and weather.wind_ms <= 0 and not weather.wind_dir:
        disp.append("Ветер слабый.")
        speech.append("Ветер слабый.")
    elif weather.wind_dir is not None and weather.wind_ms is not None:
        direction = int(round(weather.wind_dir / 10.0) * 10) % 360 or 360
        disp.append(f"Ветер {direction:03d} градусов {weather.wind_ms} метров в секунду.")
        speech.append(
            f"Ветер {int_to_words(direction)} {_deg_word(direction)} "
            f"{int_to_words(weather.wind_ms)} {_ms_word(weather.wind_ms)} в секунду."
        )
        if weather.wind_gust_ms:
            disp[-1] = disp[-1][:-1] + f", порывы {weather.wind_gust_ms}."
            speech[-1] = speech[-1] + f", порывы {int_to_words(weather.wind_gust_ms)}."
    if weather.cavok and not weather.clouds:
        disp.append("Видимость более 10 километров, облачности нет.")
        speech.append("Видимость более десяти километров, облачности нет.")
    else:
        if weather.visibility_m is not None:
            disp.append(_vis_display(weather.visibility_m).capitalize() + ".")
            speech.append(_vis_speech(weather.visibility_m).capitalize() + ".")
        if weather.clouds:
            disp.append(_cloud_display(weather.clouds[0]).capitalize() + ".")
            speech.append(_cloud_speech(weather.clouds[0]).capitalize() + ".")
        elif weather.visibility_m is not None:
            disp.append("Облачности нет.")
            speech.append("Облачности нет.")
    if weather.temp_c is not None:
        if weather.dew_c is not None:
            disp.append(f"Температура {weather.temp_c}, точка росы {weather.dew_c}.")
            speech.append(f"Температура {_temp_words(weather.temp_c)}, точка росы {_temp_words(weather.dew_c)}.")
        else:
            disp.append(f"Температура {weather.temp_c}.")
            speech.append(f"Температура {_temp_words(weather.temp_c)}.")
    if weather.qnh_hpa is not None:
        qfe = qfe_mmhg(weather.qnh_hpa, airport.elevation_ft)
        disp.append(
            f"Давление QNH {weather.qnh_hpa} гектопаскалей"
            + (f", QFE {qfe} миллиметров." if qfe is not None else ".")
        )
        speech.append(
            f"Давление кью эн эйч {int_to_words(weather.qnh_hpa)} {_hpa_word(weather.qnh_hpa)}"
            + (f", кью эф и {int_to_words(qfe)} {_mm_word(qfe)}." if qfe is not None else ".")
        )
    if weather.qnh_hpa is not None and airport.transition_levels:
        level = airport.transition_level(weather.qnh_hpa)
        disp.append(f"Эшелон перехода {level}.")
        speech.append(f"Эшелон перехода {int_to_words(level)}.")
    if remarks:
        disp.append(remarks.rstrip(".") + ".")
        speech.append(remarks.rstrip(".") + ".")
    elif weather.source:
        note = "Погода по данным симулятора." if weather.source == "sim" else "Погода по сводке METAR."
        disp.append(note)
        speech.append(note)
    if mode != "weather":
        disp.append(f"Подтвердите получение информации {letter}.")
        speech.append(f"Подтвердите получение информации {letter.lower()}.")
    return " ".join(disp), " ".join(speech)
