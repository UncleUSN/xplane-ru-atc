"""Журнал компактной панели: 5 последних реплик, новые снизу, кто говорит — видно по префиксу."""
from ru_atc.radio_log import RadioHistory


def test_keeps_last_five_newest_at_the_bottom():
    h = RadioHistory(limit=5, max_len=80)
    h.add_atc("Вышка", "сообщение 0")
    for i in range(1, 7):
        if i % 2:
            h.add_pilot(f"сообщение {i}")
        else:
            h.add_atc("Круг", f"сообщение {i}")
    lines = h.lines()
    assert len(lines) == 5
    assert [text.split()[-1] for _, text in lines] == ["2", "3", "4", "5", "6"]
    assert lines[0][0] == "atc" and lines[0][1].startswith("▶ Круг:")
    assert lines[1] == ("pilot", "◀ ПИЛОТ: сообщение 3")
    assert lines[-1][0] == "atc" and lines[-1][1].endswith("сообщение 6")
    assert "сообщение 0" not in lines[0][1] and "сообщение 1" not in "".join(t for _, t in lines)


def test_display_slots_pad_empty_rows_above():
    h = RadioHistory(limit=5, max_len=80)
    h.add_pilot("понял")
    h.add_atc("Старт", "взлёт разрешаю")
    slots = h.display_slots()
    assert len(slots) == 5
    assert slots[:3] == [("", ""), ("", ""), ("", "")]
    assert slots[3][0] == "pilot" and "ПИЛОТ" in slots[3][1] and "понял" in slots[3][1]
    assert slots[4][0] == "atc" and slots[4][1].startswith("▶ Старт:")
    assert "взлёт разрешаю" in slots[4][1]


def test_long_line_is_truncated_to_one_row():
    h = RadioHistory(limit=5, max_len=24)
    h.add_atc("Шереметьево-Деливери", "разрешено до Пулково по плану, взлёт ВПП 24 центральная")
    role, line = h.lines()[0]
    assert role == "atc"
    assert line.startswith("▶ Шереметьево-Деливери:")
    assert line.endswith("…")
    assert len(line) <= 24
    # переводы строк из текста не раздувают панель
    h.add_pilot("подтверждаю\nнабор\nшесть тысяч")
    assert "\n" not in h.lines()[-1][1]


def test_empty_history():
    assert RadioHistory().lines() == []
    assert RadioHistory(limit=5).display_slots() == [("", "")] * 5
